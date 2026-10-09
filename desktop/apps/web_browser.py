"""Bounded HTTP(S) fetching and an ASCII page model for the desktop browser.

Pages contain text and numbered links. JavaScript, styles, forms and downloads
are deliberately not executed. Network work stays off the curses thread.
"""
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
import http.cookiejar
import ipaddress
import re
import socket
import ssl
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import (HTTPCookieProcessor, HTTPRedirectHandler,
                            HTTPSHandler, Request, build_opener)


MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_URL_LENGTH = 8192
MAX_LINKS = 2048
MAX_HISTORY = 100
MAX_HISTORY_BYTES = 8 * 1024 * 1024
NETWORK_TIMEOUT = 8
FETCH_DEADLINE = 20


class BrowserError(ValueError):
    """A page cannot be opened, with a message suitable for the desktop."""


class _Cancelled(Exception):
    pass


def normalize_url(value, base=None):
    """Validate HTTP(S), encode Unicode safely, and optionally resolve a link.

    An address without a scheme defaults to HTTPS. Supplying ``base`` instead
    makes scheme-less values relative links. Credentials and terminal controls
    are never accepted in addresses.
    """
    if not isinstance(value, str) or not value.strip():
        raise BrowserError('Enter a web address.')
    if len(value) > MAX_URL_LENGTH:
        raise BrowserError('Web addresses must be at most 8192 characters.')
    if any(unicodedata.category(char).startswith('C') for char in value):
        raise BrowserError('Web addresses cannot contain control characters.')
    value = value.strip()
    if '\\' in value:
        raise BrowserError('Web addresses cannot contain backslashes.')
    if base is not None:
        value = urljoin(normalize_url(base), value)
    elif value.startswith('//'):
        value = 'https:' + value
    elif not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value):
        value = 'https://' + value
    elif re.match(r'^[^/?#:]+:[0-9]+(?:[/?#]|$)', value):
        # A local hostname and port is an address, not a custom URL scheme.
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ('http', 'https'):
            raise BrowserError('Only HTTP and HTTPS pages can be opened.')
        if parts.username is not None or parts.password is not None:
            raise BrowserError('Put no username or password in the web address.')
        hostname = parts.hostname
        port = parts.port
        if not hostname or any(char.isspace() for char in parts.netloc):
            raise BrowserError('The web address needs a valid hostname.')
        if ':' in hostname:
            if not re.fullmatch(r'\[[^\]]+\](?::[0-9]+)?', parts.netloc):
                raise BrowserError('The web address has a malformed IPv6 hostname.')
            hostname = '[' + str(ipaddress.IPv6Address(hostname)) + ']'
        else:
            if parts.netloc.endswith(':'):
                raise BrowserError('The web address has an invalid port.')
            hostname = hostname.encode('idna').decode('ascii').lower()
            if (not re.fullmatch(r'[A-Za-z0-9_.-]+', hostname)
                    or not hostname.strip('.')
                    or any(not label for label in hostname.rstrip('.').split('.'))):
                raise BrowserError('The web address needs a valid hostname.')
        if port is not None and not 1 <= port <= 65535:
            raise BrowserError('The web address has an invalid port.')
        if re.search(r'%(?![0-9A-Fa-f]{2})', value):
            raise BrowserError('The web address contains an invalid percent escape.')
        netloc = hostname + (':' + str(port) if port is not None else '')
        safe = "/:@!$&'()*+,;=-._~%"
        result = urlunsplit((parts.scheme.lower(), netloc,
                            quote(parts.path or '/', safe=safe),
                            quote(parts.query, safe=safe + '?'),
                            quote(parts.fragment, safe=safe + '?')))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, BrowserError):
            raise
        raise BrowserError('The web address is malformed.') from error
    if len(result) > MAX_URL_LENGTH:
        raise BrowserError('The encoded web address is too long.')
    return result


_ASCII_REPLACEMENTS = str.maketrans({
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '--', '\u2026': '...', '\u2022': '*',
    '\u00a0': ' ', '\u00a9': '(c)', '\u00ae': '(R)',
})


def _ascii(value, preserve_lines=False):
    value = value.translate(_ASCII_REPLACEMENTS)
    if not preserve_lines:
        value = value.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    clean = ''.join(char for char in value
                    if not unicodedata.category(char).startswith('C')
                    or preserve_lines and char in '\r\n\t')
    clean = unicodedata.normalize('NFKD', clean)
    clean = ''.join(char for char in clean if not unicodedata.combining(char))
    return clean.encode('ascii', 'replace').decode('ascii')


@dataclass(frozen=True)
class Link:
    number: int
    label: str
    url: str


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    lines: tuple[str, ...]
    links: tuple[Link, ...] = ()

    @property
    def text(self):
        return '\n'.join(self.lines)

    @property
    def size(self):
        # ASCII text costs one byte per character; URLs are encoded ASCII too.
        return (sum(len(line) + 1 for line in self.lines) + len(self.url)
                + len(self.title)
                + sum(len(link.url) + len(link.label) + 32 for link in self.links))


class _HTMLText(HTMLParser):
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _IGNORE = {'script', 'style', 'template', 'svg', 'canvas', 'iframe', 'object'}
    _BLOCK = {'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl',
              'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form',
              'header', 'main', 'nav', 'ol', 'p', 'section', 'table', 'ul'}
    _HEAD_TAGS = {'base', 'basefont', 'bgsound', 'head', 'html', 'link',
                  'meta', 'noframes', 'script', 'style', 'template', 'title'}

    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.base = url
        self._base_seen = False
        self._suppressed = []
        self._head = False
        self._title = False
        self._title_parts = []
        self._pre = False
        self._lines = []
        self._line = ''
        self._space = False
        self._anchor = None
        self._links = []
        self._characters = 0

    def _append(self, value):
        if self._characters + len(value) > MAX_BODY_BYTES * 2:
            raise BrowserError('The rendered page is too large.')
        self._characters += len(value)
        if self._pre:
            chunks = _ascii(value, preserve_lines=True).replace('\r\n', '\n').replace('\r', '\n').expandtabs(4).split('\n')
            self._line += chunks[0]
            for chunk in chunks[1:]:
                self._break(force=True)
                self._line = chunk
            return
        value = _ascii(value)
        # Remember boundary whitespace so adjacent inline tags remain readable.
        if not value:
            return
        words = value.split()
        if words:
            if self._line and (self._space or value[0].isspace()):
                self._line += ' '
            self._line += ' '.join(words)
        self._space = value[-1].isspace()

    def _break(self, paragraph=False, force=False):
        if self._line or force:
            self._lines.append(self._line.rstrip())
        self._line = ''
        self._space = False
        if paragraph and self._lines and self._lines[-1] != '':
            self._lines.append('')

    def _end_anchor(self):
        if self._anchor is not None:
            number, url, label_parts = self._anchor
            label = ' '.join(_ascii(''.join(label_parts)).split()) or url
            self._links.append(Link(number, label[:1024], url))
            if not label_parts:
                self._append(label)
            self._append(f' [{number}]')
            self._anchor = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        # HTML permits omitting </head> and <body>. Visible content implicitly
        # closes the head, rather than disappearing until an explicit end tag.
        if self._head and tag not in self._HEAD_TAGS:
            self._head = False
            self._title = False
        if self._suppressed:
            if tag not in self._VOID and len(self._suppressed) < 1024:
                self._suppressed.append(tag)
            return
        hidden = ('hidden' in attributes
                  or (attributes.get('aria-hidden') or '').lower() == 'true')
        style = re.sub(r'\s+', '', (attributes.get('style') or '').lower())
        hidden = hidden or 'display:none' in style or 'visibility:hidden' in style
        if tag in self._IGNORE or hidden:
            if tag not in self._VOID:
                self._suppressed = [tag]
            return
        if tag == 'head':
            self._head = True
        if tag == 'title':
            self._title = True
            return
        if tag == 'base' and not self._base_seen and attributes.get('href'):
            try:
                self.base = normalize_url(attributes['href'], self.url)
                self._base_seen = True
            except BrowserError:
                pass
        if self._head:
            return
        if (self._anchor is not None
                and (tag in self._BLOCK or tag in ('br', 'li', 'pre', 'tr')
                     or re.fullmatch(r'h[1-6]', tag))):
            self._anchor[2].append(' ')
        if tag == 'a':
            self._end_anchor()
            if attributes.get('href') and len(self._links) < MAX_LINKS:
                try:
                    target = normalize_url(attributes['href'], self.base)
                    self._anchor = (len(self._links) + 1, target, [])
                except BrowserError:
                    pass
        elif tag in self._BLOCK:
            self._break(paragraph=True)
        elif re.fullmatch(r'h[1-6]', tag):
            self._break(paragraph=True)
            self._append('#' * int(tag[1]) + ' ')
        elif tag == 'li':
            self._break()
            self._append('* ')
        elif tag == 'br':
            self._break(force=True)
        elif tag == 'hr':
            self._break(paragraph=True)
            self._append('--------------------')
            self._break(paragraph=True)
        elif tag == 'pre':
            self._break(paragraph=True)
            self._pre = True
        elif tag == 'tr':
            self._break()
        elif tag in ('td', 'th') and self._line:
            self._append(' | ')
        elif tag == 'img':
            alt = (attributes.get('alt') or '').strip()
            if alt:
                self._append('[image: ' + alt + ']')
                if self._anchor is not None:
                    self._anchor[2].append(alt)
        elif tag in ('input', 'select', 'textarea', 'button'):
            # Forms are not actionable. Page text remains readable without
            # presenting a misleading editable control.
            if tag == 'input' and (attributes.get('type') or '').lower() != 'hidden':
                self._append('[form input]')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._suppressed:
            if tag in self._suppressed:
                index = len(self._suppressed) - 1 - self._suppressed[::-1].index(tag)
                del self._suppressed[index:]
            return
        if tag == 'title':
            self._title = False
            return
        if tag == 'head':
            self._head = False
            return
        if self._head:
            return
        if tag == 'a':
            self._end_anchor()
        elif tag == 'pre':
            self._break(paragraph=True)
            self._pre = False
        elif tag in self._BLOCK or re.fullmatch(r'h[1-6]', tag):
            self._break(paragraph=True)
        elif tag in ('li', 'tr'):
            self._break()

    def handle_data(self, data):
        if self._suppressed:
            return
        if self._title:
            self._title_parts.append(data)
        else:
            if self._head and data.strip():
                self._head = False
            if self._head:
                return
            self._append(data)
            if self._anchor is not None:
                self._anchor[2].append(data)

    def page(self):
        self._end_anchor()
        self._break()
        while self._lines and not self._lines[-1]:
            self._lines.pop()
        title = ' '.join(_ascii(''.join(self._title_parts)).split())[:512]
        return Page(self.url, title or self.url, tuple(self._lines), tuple(self._links))


def render_html(content, url):
    """Turn HTML into logical ASCII lines and relative, numbered HTTP links."""
    url = normalize_url(url)
    if len(content.encode('utf-8', 'replace')) > MAX_BODY_BYTES * 2:
        raise BrowserError('The page is too large to render.')
    parser = _HTMLText(url)
    try:
        parser.feed(content)
        parser.close()
        return parser.page()
    except (RecursionError, AssertionError) as error:
        raise BrowserError('This HTML page could not be read.') from error


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        try:
            new_url = normalize_url(new_url, request.full_url)
        except BrowserError:
            response.close()
            raise
        return super().redirect_request(request, response, code, message, headers, new_url)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise _Cancelled()


def fetch_page(url, cancel_event=None, opener=None):
    """Fetch one bounded text page using verified TLS and system proxy settings."""
    url = normalize_url(url)
    _check_cancel(cancel_event)
    opener = opener or build_opener(_SafeRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={
        'User-Agent': 'ASCII-Linux-Browser/0.1 (text-only)',
        'Accept': 'text/html, application/xhtml+xml, text/plain; q=0.9',
        'Accept-Encoding': 'identity',
    })
    started = time.monotonic()
    try:
        with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
            _check_cancel(cancel_event)
            final_url = normalize_url(response.geturl())
            mime = response.headers.get_content_type()
            if mime not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                raise BrowserError(f'This is {mime}, not a text page. Downloads are not supported.')
            encoding = response.headers.get('Content-Encoding', '').lower().strip()
            if encoding not in ('', 'identity'):
                raise BrowserError('The server returned compressed content despite a plain-text request.')
            length = response.headers.get('Content-Length')
            if length is not None:
                try:
                    if int(length) > MAX_BODY_BYTES:
                        raise BrowserError('Pages must be at most 2 MiB.')
                except ValueError as error:
                    if isinstance(error, BrowserError):
                        raise
            chunks = []
            size = 0
            read = getattr(response, 'read1', response.read)
            while True:
                _check_cancel(cancel_event)
                if time.monotonic() - started > FETCH_DEADLINE:
                    raise BrowserError('The page took too long to load.')
                chunk = read(min(65536, MAX_BODY_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise BrowserError('Pages must be at most 2 MiB.')
            _check_cancel(cancel_event)
            raw = b''.join(chunks)
            charset = response.headers.get_content_charset() or 'utf-8'
            try:
                content = raw.decode(charset, errors='replace')
            except LookupError:
                content = raw.decode('utf-8', errors='replace')
        if mime == 'text/plain':
            text = _ascii(content, preserve_lines=True).replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
            return Page(final_url, final_url, tuple(text.splitlines()))
        return render_html(content, final_url)
    except HTTPError as error:
        error.close()
        raise BrowserError(f'HTTP {error.code}: {_ascii(str(error.reason))[:200]}.') from error
    except URLError as error:
        if isinstance(error.reason, ssl.SSLCertVerificationError):
            raise BrowserError('The HTTPS certificate could not be verified.') from error
        raise BrowserError(f'Could not connect: {_ascii(str(error.reason))[:300]}.') from error
    except (TimeoutError, socket.timeout) as error:
        raise BrowserError('The connection timed out.') from error
    except (OSError, UnicodeError) as error:
        raise BrowserError(f'Could not read the page: {_ascii(str(error))[:300]}.') from error


class WebBrowser:
    """Responsive navigation with one worker and a latest-only pending request.

    A cancelled or replaced request cannot change the visible page. Back and
    forward use cached pages; loading failures retain both the page and history.
    Cookies stay in this browser's memory and are never persisted to disk.
    """

    def __init__(self, fetcher=None):
        self.page = None
        self.error = ''
        self.busy = False
        self.loading_url = ''
        self._history = []
        self._index = -1
        self._generation = 0
        self._condition = threading.Condition()
        self._pending = None
        self._results = deque(maxlen=1)
        self._cancel_event = None
        self._worker = None
        self._closed = False
        if fetcher is None:
            cookies = http.cookiejar.CookieJar()
            opener = build_opener(_SafeRedirects(),
                                  HTTPSHandler(context=ssl.create_default_context()),
                                  HTTPCookieProcessor(cookies))
            self._fetcher = lambda url, cancel: fetch_page(url, cancel, opener)
        else:
            self._fetcher = fetcher

    @property
    def can_back(self):
        return self._index > 0

    @property
    def can_forward(self):
        return 0 <= self._index < len(self._history) - 1

    def _request(self, url, replace=False):
        with self._condition:
            if self._closed:
                raise BrowserError('This browser has closed.')
            self._invalidate()
            event = threading.Event()
            self._cancel_event = event
            self._pending = (self._generation, url, replace, event)
            self.busy = True
            self.loading_url = url
            self.error = ''
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name='ascii-browser-fetch', daemon=True)
                self._worker.start()
            self._condition.notify()
        return True

    def navigate(self, value):
        return self._request(normalize_url(value))

    def follow(self, number):
        if self.page is None:
            raise BrowserError('Open a page first.')
        link = next((link for link in self.page.links if link.number == number), None)
        if link is None:
            raise BrowserError('Choose a link number from this page.')
        return self.navigate(link.url)

    def reload(self):
        return self._request(self.page.url, replace=True) if self.page else False

    def _invalidate(self):
        self._generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._pending = None
        self._results.clear()

    def cancel(self):
        with self._condition:
            changed = self.busy or bool(self.error)
            self._invalidate()
            self.busy = False
            self.loading_url = ''
            self.error = ''
        return changed

    def _move(self, index):
        if not 0 <= index < len(self._history):
            return False
        self.cancel()
        self._index = index
        self.page = self._history[index]
        return True

    def back(self):
        return self._move(self._index - 1)

    def forward(self):
        return self._move(self._index + 1)

    def _work(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._closed)
                if self._closed:
                    return
                generation, url, replace, cancel = self._pending
                self._pending = None
            page, error = None, ''
            try:
                page = self._fetcher(url, cancel)
                if not isinstance(page, Page):
                    raise BrowserError('The server response could not be read.')
            except _Cancelled:
                continue
            except Exception as failure:
                error = _ascii(str(failure))[:512] or 'The page could not be loaded.'
            with self._condition:
                if generation == self._generation and not cancel.is_set() and not self._closed:
                    self._results.append((generation, page, error, replace))

    def poll(self):
        with self._condition:
            if not self._results:
                return False
            generation, page, error, replace = self._results.popleft()
            if generation != self._generation:
                return False
            self.busy = False
            self.loading_url = ''
            self.error = error
            if page is None:
                return True
            if replace and self._index >= 0:
                self._history[self._index] = page
            else:
                self._history = self._history[:self._index + 1]
                self._history.append(page)
                self._index += 1
            while (len(self._history) > MAX_HISTORY
                   or sum(entry.size for entry in self._history) > MAX_HISTORY_BYTES):
                if len(self._history) <= 1:
                    break
                # Keep the current page; a reload in the middle may also have
                # forward entries, which are less useful than recent history.
                if self._index > 0:
                    self._history.pop(0)
                    self._index -= 1
                else:
                    self._history.pop()
            self.page = page
            return True

    def close(self):
        with self._condition:
            self._invalidate()
            self._closed = True
            self.busy = False
            self.loading_url = ''
            self._condition.notify()
