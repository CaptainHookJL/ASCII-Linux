"""ASCII browser controls over asynchronously fetched, text-only web pages."""
import curses
import unicodedata

from desktop.apps.browser_data import BookmarkStore, MAX_NAME_CHARS
from desktop.apps.web_browser import WebBrowser
from desktop.utils.ascii_layout import LayoutError, render_layout

MAX_FIND_MATCHES = 4096


def ascii_text(value):
    """Keep web text and addresses from emitting terminal control characters."""
    value = unicodedata.normalize('NFKD', str(value))
    value = ''.join(character for character in value if not unicodedata.combining(character))
    value = value.encode('ascii', 'replace').decode('ascii')
    return ''.join(character if ' ' <= character <= '~' else ' ' for character in value)


def wrap_lines(lines, width):
    """Wrap at words without discarding text; retain source positions for Find."""
    width = max(1, width)
    wrapped = []
    for index, source in enumerate(lines):
        source = ascii_text(source.expandtabs(4))
        if not source:
            wrapped.append(('', index, 0, 0))
            continue
        start = 0
        while start < len(source):
            end = min(len(source), start + width)
            if end < len(source):
                space = source.rfind(' ', start, end)
                if space > start:
                    end = space + 1
            wrapped.append((source[start:end], index, start, end))
            start = end
    return wrapped


class WebBrowserView:
    def __init__(self, desktop, browser=None, bookmarks=None):
        self.desktop = desktop
        self.browser = browser if browser is not None else WebBrowser()
        self.bookmarks = bookmarks if bookmarks is not None else BookmarkStore()
        self.bookmark_error = ''
        self.show_bookmarks = False
        self.bookmark_selected = 0
        self.offset = 0
        self.link_selected = 0
        self.query = ''
        self.matches = []
        self.match_index = -1
        self.matches_truncated = False
        self._page = None
        self._last_error = ''
        self._cached_wrap = None
        self._wrapped = []
        self.layout_enabled = True
        self.layout_notice = ''
        self._search_lines = ()
        self._load_bookmarks()

    def _load_bookmarks(self):
        try:
            self.bookmarks.load()
            self.bookmark_error = ''
        except (OSError, ValueError) as error:
            self.bookmark_error = str(error)
        self.bookmark_selected = min(self.bookmark_selected, max(0, len(self.bookmarks.entries) - 1))

    def opened(self):
        """Opening the tool never contacts a site or discards its current page."""
        self._sync_page()
        if self.browser.error:
            self.desktop.message = 'Web: ' + ascii_text(self.browser.error)

    def close(self):
        self.browser.close()

    def _sync_page(self):
        if self._page is self.browser.page:
            return False
        self._page = self.browser.page
        self.offset = self.link_selected = 0
        self._cached_wrap = None
        self._find_matches()
        if self._page is not None and self.desktop.page == 'web':
            self.desktop.message = (self.layout_notice or
                                    'Loaded: ' + ascii_text(self._page.title or self._page.url))
        return True

    def tick(self):
        self.browser.poll()
        self._sync_page()
        if self.browser.error != self._last_error:
            self._last_error = self.browser.error
            if self.browser.error and self.desktop.page == 'web':
                self.desktop.message = 'Web: ' + ascii_text(self.browser.error)

    def _body(self, width):
        page = self.browser.page
        key = (id(page), width, self.layout_enabled)
        if key != self._cached_wrap:
            lines = page.lines if page is not None else (
                'ASCII Web',
                'G opens a URL; example: https://example.com',
                'L switches ASCII layout and flowing text.',
                'No scripts, external styles, media, or forms.',
            )
            document = getattr(page, 'layout', None)
            self.layout_notice = ''
            if self.layout_enabled and document is not None:
                try:
                    laid_out = render_layout(document, width)
                    self._wrapped = [(line, index, 0, len(line)) for index, line in enumerate(laid_out)]
                    self._search_lines = laid_out
                except LayoutError:
                    self.layout_notice = 'Complex layout: showing text.'
                    if self.desktop.page == 'web':
                        self.desktop.message = self.layout_notice
                    self._wrapped = wrap_lines(lines, width)
                    self._search_lines = lines
            else:
                self._wrapped = wrap_lines(lines, width)
                self._search_lines = lines
            self._cached_wrap = key
            self._collect_matches(self._search_lines, preserve=True)
            if 0 <= self.match_index < len(self.matches):
                index, position = self.matches[self.match_index]
                count, _ = self._dimensions()
                for row, (_, logical, start, end) in enumerate(self._wrapped):
                    if logical == index and start <= position < end:
                        if row < self.offset or row >= self.offset + count:
                            self.offset = min(row, max(0, len(self._wrapped) - count))
                        break
        return self._wrapped

    def _dimensions(self):
        height, width = self.desktop.screen.getmaxyx()
        # The desktop pauses drawing below 60x16. Background page loads still
        # reflow, so retain its minimum usable width rather than allocating
        # one row per character while the terminal is temporarily tiny.
        return max(1, height - 12), max(54, width - 6)

    def _max_offset(self):
        count, width = self._dimensions()
        return max(0, len(self._body(width)) - count)

    def _draw(self, row, value, attr=0):
        self.desktop.text(row, 3, ascii_text(value), attr)

    def render(self, height, width):
        if self.show_bookmarks:
            self._render_bookmarks(height, width)
            return
        page = self.browser.page
        address = self.browser.loading_url if self.browser.busy else page.url if page else '[no page]'
        self._draw(4, 'URL: ' + address)
        self._draw(5, ('Loading: ' + self.browser.loading_url if self.browser.busy else
                       'Title: ' + (page.title or page.url) if page else 'ASCII web browser'), curses.A_BOLD)
        body = self._body(max(1, width - 6))
        count = max(1, height - 12)
        self.offset = min(self.offset, max(0, len(body) - count))
        match = self.matches[self.match_index] if 0 <= self.match_index < len(self.matches) else None
        for row, (line, index, start, end) in enumerate(body[self.offset:self.offset + count], 6):
            attr = curses.A_REVERSE if match and index == match[0] and start <= match[1] < end else 0
            self._draw(row, line, attr)
        if page and page.links:
            self.link_selected %= len(page.links)
            link = page.links[self.link_selected]
            self._draw(height - 6, f'Link {link.number}/{len(page.links)}: {link.label} -> {link.url}')
        else:
            self._draw(height - 6, 'No links on this page.' if page else 'Enter a URL to begin browsing.')
        self._draw(height - 5, 'G URL | Tab Link | Enter Open | Backspace Back | ] Fwd')
        mode = ('Layout' if self.layout_enabled and getattr(page, 'layout', None) is not None
                and not self.layout_notice else 'Text')
        self._draw(height - 4, f'L {mode} | R Reload | / Find | n Next | B Save')

    def _render_bookmarks(self, height, width):
        entries = self.bookmarks.entries
        self._draw(4, f'Bookmarks ({len(entries)})', curses.A_BOLD)
        self._draw(5, self.bookmark_error or 'Saved pages; Enter opens the selected address.')
        count = max(1, (height - 12) // 2)
        self.bookmark_selected = min(self.bookmark_selected, max(0, len(entries) - 1))
        start = max(0, self.bookmark_selected - count + 1)
        for index, entry in enumerate(entries[start:start + count], start):
            row = 6 + (index - start) * 2
            attr = curses.A_REVERSE if index == self.bookmark_selected else 0
            self._draw(row, f'{index + 1}. {entry.name}', attr)
            self._draw(row + 1, entry.url, curses.A_DIM)
        if not entries:
            self._draw(6, 'No bookmarks yet. B saves the current page.')
        self._draw(height - 6, 'D removes a bookmark; it does not change the website.')
        self._draw(height - 5, 'Arrows/Tab Select | Enter Open | D Delete')
        self._draw(height - 4, 'M Return to page | R Reload bookmarks | G URL')

    def footer(self):
        ending = 'Exit' if getattr(self.desktop, 'browser_only', False) else 'Desktop'
        return ('M Page | Esc ' + ending if self.show_bookmarks else
                'M Bookmarks | X Cancel | Esc ' + ending)

    def _start(self, operation):
        if operation():
            self.show_bookmarks = False
            self._sync_page()
            if self.browser.busy:
                self.desktop.message = 'Loading web page...'
        else:
            self.desktop.message = 'No page in that direction.'

    def _open_url(self):
        page = self.browser.page
        value = self.desktop.prompt('Open web URL', page.url if page else '')
        if value is not None and value.strip():
            self._start(lambda: self.browser.navigate(value))

    def _find_matches(self):
        self._body(self._dimensions()[1])
        self._collect_matches(self._search_lines)

    def _collect_matches(self, lines, preserve=False):
        previous = self.match_index
        self.matches, self.match_index = [], -1
        self.matches_truncated = False
        if self.query and self.browser.page:
            needle = ascii_text(self.query).lower()
            for index, line in enumerate(lines):
                text = ascii_text(line.expandtabs(4)).lower()
                start = 0
                while True:
                    found = text.find(needle, start)
                    if found < 0:
                        break
                    if len(self.matches) == MAX_FIND_MATCHES:
                        self.matches_truncated = True
                        if preserve:
                            self.match_index = min(previous, len(self.matches) - 1)
                        return
                    self.matches.append((index, found))
                    start = found + max(1, len(needle))
        if preserve:
            self.match_index = min(previous, len(self.matches) - 1)

    def _next_match(self):
        self._body(self._dimensions()[1])
        if not self.query:
            self.desktop.message = 'Use / to find page text.'
            return
        if not self.matches:
            self.desktop.message = 'No matches found.'
            return
        self.match_index = (self.match_index + 1) % len(self.matches)
        index, position = self.matches[self.match_index]
        _, width = self._dimensions()
        for row, (_, logical, start, end) in enumerate(self._body(width)):
            if logical == index and start <= position < end:
                self.offset = min(row, self._max_offset())
                break
        self.desktop.message = (f'Match {self.match_index + 1}/{len(self.matches)}'
                                + ('+' if self.matches_truncated else ''))

    def _save_bookmark(self):
        page = self.browser.page
        if page is None:
            self.desktop.message = 'Open a page before bookmarking it.'
            return
        entry = self.bookmarks.add((page.title or page.url)[:MAX_NAME_CHARS], page.url)
        self.bookmark_error = ''
        self.desktop.message = 'Bookmarked: ' + ascii_text(entry.name)

    def _handle_bookmarks(self, key):
        entries = self.bookmarks.entries
        amount = max(1, self._dimensions()[0] // 2)
        if key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE, '\t', curses.KEY_BTAB):
            direction = -1 if key in (curses.KEY_UP, curses.KEY_PPAGE, curses.KEY_BTAB) else 1
            self.bookmark_selected = max(0, min(max(0, len(entries) - 1), self.bookmark_selected +
                                              direction * (amount if key in (curses.KEY_PPAGE, curses.KEY_NPAGE) else 1)))
        elif key in (curses.KEY_HOME, curses.KEY_END):
            self.bookmark_selected = 0 if key == curses.KEY_HOME else max(0, len(entries) - 1)
        elif key in ('\r', '\n', curses.KEY_ENTER) and entries:
            entry = entries[self.bookmark_selected]
            self._start(lambda: self.browser.navigate(entry.url))
        elif key in ('d', 'D') and entries:
            entry = entries[self.bookmark_selected]
            if self.desktop.confirm('Delete bookmark: ' + entry.name + '?'):
                self.bookmarks.remove(entry.url)
                self.bookmark_selected = min(self.bookmark_selected, max(0, len(self.bookmarks.entries) - 1))
                self.desktop.message = 'Bookmark removed: ' + ascii_text(entry.name)
        elif key in ('r', 'R'):
            self._load_bookmarks()
            self.desktop.message = ('Bookmarks: ' + self.bookmark_error if self.bookmark_error else 'Bookmarks reloaded')

    def handle(self, key):
        try:
            self._handle(key)
        except (OSError, ValueError) as error:
            self.desktop.message = 'Web: ' + ascii_text(error)

    def _handle(self, key):
        if key in ('g', 'G'):
            self._open_url()
        elif key in ('m', 'M'):
            self.show_bookmarks = not self.show_bookmarks
            if self.show_bookmarks:
                self._load_bookmarks()
        elif key in ('b', 'B'):
            self._save_bookmark()
        elif key in ('x', 'X'):
            if self.browser.cancel():
                self.desktop.message = 'Page load cancelled'
        elif key in ('l', 'L') and not self.show_bookmarks:
            self.layout_enabled = not self.layout_enabled
            self.offset = 0
            self._cached_wrap = None
            self._body(self._dimensions()[1])
            self.desktop.message = 'Layout: ASCII' if self.layout_enabled else 'Layout: Text'
        elif self.show_bookmarks:
            self._handle_bookmarks(key)
        elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
            self._start(self.browser.back)
        elif key == ']':
            self._start(self.browser.forward)
        elif key in ('r', 'R'):
            self._start(self.browser.reload)
        elif key in ('\r', '\n', curses.KEY_ENTER):
            page = self.browser.page
            if page and page.links:
                self.link_selected %= len(page.links)
                self._start(lambda: self.browser.follow(page.links[self.link_selected].number))
        elif key in ('\t', curses.KEY_BTAB, curses.KEY_LEFT, curses.KEY_RIGHT):
            page = self.browser.page
            if page and page.links:
                self.link_selected = (self.link_selected + (-1 if key in (curses.KEY_BTAB, curses.KEY_LEFT) else 1)) % len(page.links)
        elif key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            count, _ = self._dimensions()
            direction = -1 if key in (curses.KEY_UP, curses.KEY_PPAGE) else 1
            self.offset = max(0, min(self._max_offset(), self.offset + direction *
                                    (count if key in (curses.KEY_PPAGE, curses.KEY_NPAGE) else 1)))
        elif key in (curses.KEY_HOME, curses.KEY_END):
            self.offset = 0 if key == curses.KEY_HOME else self._max_offset()
        elif key == '/':
            value = self.desktop.prompt('Find page text', self.query)
            if value is not None:
                self.query = value
                self._find_matches()
                self._next_match()
        elif key in ('n', 'N'):
            self._next_match()
