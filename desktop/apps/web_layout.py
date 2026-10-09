"""A bounded, immutable document for approximate ASCII website layout.

This is a small HTML layout description, not a CSS or JavaScript engine. Only
semantic structure and a few local CSS hints are retained; no resources load.
Pages which exceed its limits continue to use the ordinary text view.
"""
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re


MAX_LAYOUT_NODES = 4096
MAX_LAYOUT_DEPTH = 64
MAX_LAYOUT_TEXT = 2 * 1024 * 1024
MAX_STYLE_TEXT = 65536
MAX_STYLE_RULES = 256
_PROPERTIES = frozenset(('display', 'visibility', 'grid-template-columns',
                         'flex-direction', 'flex-wrap', 'width', 'max-width',
                         'border', 'border-width', 'border-style', 'gap'))


@dataclass(frozen=True)
class LayoutNode:
    """An HTML tag, ASCII text, children and restricted CSS/span hints."""

    tag: str
    text: str = ''
    children: tuple['LayoutNode', ...] = ()
    hints: tuple[tuple[str, str], ...] = ()


def document_size(root):
    """Charge retained layout strings and node overhead to page history."""
    size = 0
    pending = [root]
    while pending:
        node = pending.pop()
        size += 64 + len(node.tag) + len(node.text)
        size += sum(len(key) + len(value) + 16 for key, value in node.hints)
        pending.extend(node.children)
    return size


class _LayoutLimit(ValueError):
    pass


@dataclass
class _Node:
    tag: str
    text: str = ''
    children: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)


def _declarations(value):
    result = {}
    for declaration in value[:4096].split(';')[:64]:
        key, separator, val = declaration.partition(':')
        key = key.strip().lower()
        val = val.strip().lower()
        if separator and key in _PROPERTIES and val and len(val) <= 256:
            # CSS URLs, expression syntax and escapes have no useful meaning
            # in this layout model. They are never resolved or evaluated.
            if (val.isascii() and val.isprintable()
                    and not any(char in val for char in '\\{}')
                    and 'url(' not in val and 'expression(' not in val):
                result[key] = re.sub(r'\s*!important\s*$', '', re.sub(r'\s+', ' ', val))
    return result


def _selector(value):
    """Only tag, class, ID and their simple compounds; no combinators."""
    value = value.strip()
    if not re.fullmatch(r'(?:[A-Za-z][\w-]*|\*)?(?:[.#][A-Za-z_][\w-]*)*', value):
        return None
    if not value:
        return None
    tag = re.match(r'^[A-Za-z][\w-]*|^\*', value)
    ids = re.findall(r'#([\w-]+)', value)
    classes = re.findall(r'\.([\w-]+)', value)
    return (tag.group().lower() if tag else '', tuple(ids), tuple(classes))


def _style_rules(styles):
    """Read flat rules; skip at-rules and nested/media blocks entirely."""
    css = re.sub(r'/\*.*?\*/', '', styles[:MAX_STYLE_TEXT], flags=re.S)
    rules = []
    start = 0
    depth = 0
    selector = ''
    body_start = 0
    nested = False
    for index, char in enumerate(css):
        if char == '{':
            if depth == 0:
                selector = css[start:index].strip()
                body_start = index + 1
                nested = False
            else:
                nested = True
            depth += 1
        elif char == '}' and depth:
            depth -= 1
            if depth == 0:
                if not nested and '@' not in selector:
                    declarations = _declarations(css[body_start:index])
                    for candidate in selector.split(',')[:16]:
                        match = _selector(candidate)
                        if match and declarations:
                            rules.append((match, declarations))
                            if len(rules) >= MAX_STYLE_RULES:
                                return rules
                start = index + 1
        elif char == ';' and depth == 0:
            start = index + 1
    return rules


def _hints(node, rules):
    attributes = node.attributes
    classes = set((attributes.get('class') or '').split())
    chosen = {}
    ranks = {}
    for order, (selector, declarations) in enumerate(rules):
        tag, ids, needed_classes = selector
        if tag not in ('', '*', node.tag):
            continue
        if any(identifier != attributes.get('id') for identifier in ids):
            continue
        if any(name not in classes for name in needed_classes):
            continue
        rank = (len(ids), len(needed_classes), int(tag not in ('', '*')), order)
        for key, value in declarations.items():
            if key not in ranks or rank >= ranks[key]:
                chosen[key], ranks[key] = value, rank
    chosen.update(_declarations(attributes.get('style') or ''))
    if node.tag in ('td', 'th'):
        for key in ('colspan', 'rowspan'):
            value = attributes.get(key) or '1'
            if re.fullmatch(r'[0-9]{1,4}', value):
                chosen[key] = str(max(1, min(1000, int(value))))
            else:
                # An unsupported span forces the renderer's lossless fallback.
                chosen[key] = 'unsupported'
    return tuple(sorted(chosen.items()))


class _DocumentParser(HTMLParser):
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _IGNORE = {'script', 'style', 'template', 'svg', 'canvas', 'iframe', 'object'}
    _HEAD_TAGS = {'base', 'basefont', 'bgsound', 'head', 'html', 'link',
                  'meta', 'noframes', 'script', 'style', 'template', 'title'}
    _BLOCK = {'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl',
              'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form',
              'header', 'main', 'nav', 'ol', 'p', 'section', 'table', 'ul',
              'li', 'pre', 'tr'}

    def __init__(self, url, links, ascii_text, normalize, browser_error, max_url_length):
        super().__init__(convert_charrefs=True)
        self.root = _Node('document')
        self._stack = [self.root]
        self._nodes = 1
        self._characters = 0
        self._suppressed = []
        self._head = False
        self._title = False
        self._css = []
        self._css_size = 0
        self._style = False
        self._url = url
        self._base = url
        self._base_seen = False
        self._links = links
        self._next_link = 0
        self._anchor = None
        self._ascii = ascii_text
        self._normalize = normalize
        self._browser_error = browser_error
        self._max_url_length = max_url_length

    def _node(self, tag, text='', attributes=None, parent=None):
        if len(tag) > 64:
            raise _LayoutLimit()
        tag = self._ascii(tag)
        self._nodes += 1
        self._characters += len(text)
        if self._nodes > MAX_LAYOUT_NODES or self._characters > MAX_LAYOUT_TEXT:
            raise _LayoutLimit()
        node = _Node(tag, text, attributes=attributes or {})
        (parent or self._stack[-1]).children.append(node)
        return node

    def _text(self, data, parent=None):
        parent = parent or self._stack[-1]
        pre = any(node.tag == 'pre' for node in self._stack)
        if pre:
            data = self._ascii(data, preserve_lines=True)
            data = data.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
        else:
            data = re.sub(r'\s+', ' ', self._ascii(data))
        if not data:
            return
        if parent.children and parent.children[-1].tag == 'text':
            self._characters += len(data)
            if self._characters > MAX_LAYOUT_TEXT:
                raise _LayoutLimit()
            parent.children[-1].text += data
        else:
            self._node('text', data, parent=parent)

    def _end_anchor(self):
        if self._anchor is None:
            return
        node, link = self._anchor
        pending = [node]
        visible = False
        while pending:
            current = pending.pop()
            if current.text.strip():
                visible = True
                break
            pending.extend(current.children)
        if not visible:
            self._text(link.label, parent=node)
        self._text(f' [{link.number}]', parent=node)
        self._anchor = None

    def _close(self, tag):
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                if (self._anchor is not None
                        and any(node is self._anchor[0] for node in self._stack[index:])):
                    self._end_anchor()
                del self._stack[index:]
                return

    def _implicit_close(self, tag, boundaries):
        for node in reversed(self._stack[1:]):
            if node.tag in boundaries:
                return
            if node.tag == tag:
                self._close(tag)
                return

    def handle_starttag(self, tag, attrs):
        # Keep only metadata useful to this layout. Attribute values are never
        # echoed, interpreted as commands or used for resource downloads.
        raw_attributes = dict(attrs)
        attributes = {key: (value or '')[:4096] for key, value in attrs
                      if key in ('class', 'id', 'style', 'hidden', 'aria-hidden',
                                 'href', 'alt', 'type', 'colspan', 'rowspan')}
        # Invalid long hrefs must stay invalid rather than becoming a different
        # truncated address which could steal the next link's number.
        href = raw_attributes.get('href') or ''
        if len(href) <= self._max_url_length:
            attributes['href'] = href
        else:
            attributes['href'] = ''
        if self._head and tag not in self._HEAD_TAGS:
            self._head = False
            self._title = False
        if self._suppressed:
            if tag not in self._VOID and len(self._suppressed) < 1024:
                self._suppressed.append(tag)
            return
        style = re.sub(r'\s+', '', (raw_attributes.get('style') or '').lower())
        hidden = ('hidden' in attributes
                  or attributes.get('aria-hidden', '').lower() == 'true'
                  or 'display:none' in style or 'visibility:hidden' in style)
        if tag in self._IGNORE or hidden:
            if tag == 'style' and not hidden:
                self._style = True
            if tag not in self._VOID:
                self._suppressed = [tag]
            return
        if tag == 'head':
            self._head = True
            return
        if tag == 'title':
            self._title = True
            return
        if tag == 'base' and not self._base_seen and attributes.get('href'):
            try:
                self._base = self._normalize(attributes['href'], self._url)
                self._base_seen = True
            except self._browser_error:
                pass
        if tag == 'body' and not self._head:
            self.root.attributes = attributes
        if self._head or self._title or tag in ('html', 'body'):
            return
        if tag in ('base', 'link', 'meta', 'area', 'source', 'param', 'col'):
            return
        if tag in self._BLOCK or re.fullmatch(r'h[1-6]', tag):
            self._close('p')
        if tag == 'li':
            self._implicit_close('li', ('ul', 'ol'))
        elif tag == 'tr':
            self._implicit_close('tr', ('table',))
        elif tag in ('td', 'th'):
            self._implicit_close('td', ('tr',))
            self._implicit_close('th', ('tr',))
        if tag == 'a':
            self._end_anchor()
            self._close('a')
        node = self._node(tag, attributes=attributes)
        if tag == 'img':
            alt = self._ascii(attributes.get('alt', '')).strip()
            if alt:
                self._text('[image: ' + alt + ']', parent=node)
        elif tag == 'input' and attributes.get('type', '').lower() != 'hidden':
            self._text('[form input]', parent=node)
        if tag not in self._VOID:
            if len(self._stack) >= MAX_LAYOUT_DEPTH:
                raise _LayoutLimit()
            self._stack.append(node)
        if tag == 'a' and attributes.get('href') and self._next_link < len(self._links):
            try:
                target = self._normalize(attributes['href'], self._base)
            except self._browser_error:
                return
            link = self._links[self._next_link]
            if link.url == target:
                self._next_link += 1
                self._anchor = (node, link)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._suppressed:
            if tag in self._suppressed:
                index = len(self._suppressed) - 1 - self._suppressed[::-1].index(tag)
                del self._suppressed[index:]
                if not self._suppressed:
                    self._style = False
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
        self._close(tag)

    def handle_data(self, data):
        if self._style:
            remaining = MAX_STYLE_TEXT - self._css_size
            if remaining > 0:
                self._css.append(data[:remaining])
                self._css_size += len(data[:remaining])
            return
        if self._suppressed or self._title:
            return
        if self._head and data.strip():
            self._head = False
        if not self._head:
            self._text(data)

    def document(self):
        self._end_anchor()
        rules = _style_rules(''.join(self._css))
        # Freeze iteratively: malformed deeply nested markup cannot recurse.
        frozen = {}
        pending = [(self.root, False)]
        while pending:
            node, visited = pending.pop()
            if not visited:
                pending.append((node, True))
                pending.extend((child, False) for child in reversed(node.children))
                continue
            # The synthetic document represents the explicit or implicit body.
            # This keeps body CSS and its class/ID useful without a redundant
            # wrapper around every semantic region.
            styled = (_Node('body', attributes=node.attributes)
                      if node is self.root else node)
            hints = _hints(styled, rules)
            properties = dict(hints)
            if properties.get('display') == 'none' or properties.get('visibility') == 'hidden':
                frozen[id(node)] = LayoutNode('document') if node is self.root else None
                continue
            children = tuple(frozen[id(child)] for child in node.children
                             if frozen[id(child)] is not None)
            frozen[id(node)] = LayoutNode(node.tag, node.text, children, hints)
        return frozen[id(self.root)]


def build_layout(content, url, links):
    """Return a structured document, or None for a safe plain-text fallback."""
    # Local import keeps the shared ASCII/URL rules authoritative without a
    # module import cycle: render_html invokes this after both modules load.
    from .web_browser import BrowserError, MAX_URL_LENGTH, _ascii, normalize_url
    parser = _DocumentParser(url, links, _ascii, normalize_url, BrowserError, MAX_URL_LENGTH)
    try:
        parser.feed(content)
        parser.close()
        return parser.document()
    except (_LayoutLimit, RecursionError, AssertionError):
        return None
