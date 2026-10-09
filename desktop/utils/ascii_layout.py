"""Render a bounded HTML layout tree into responsive, entirely ASCII rows.

This is a small text layout engine, not a CSS browser. Semantic regions and
simple grid/flex hints give a page its shape; narrow screens keep every region
by stacking columns. The caller can fall back to the page's plain text if a
tree exceeds the rendering limits.
"""
import re
import textwrap
import unicodedata


MAX_LAYOUT_NODES = 12000
MAX_LAYOUT_DEPTH = 48
MAX_LAYOUT_TEXT = 4 * 1024 * 1024
MAX_LAYOUT_ROWS = 30000
MAX_LAYOUT_OUTPUT = 4 * 1024 * 1024
MAX_TABLE_COLUMNS = 8


class LayoutError(ValueError):
    """This tree cannot be laid out within the browser's resource limits."""


_REGIONS = {'header', 'nav', 'main', 'aside', 'footer', 'article', 'section',
            'figure', 'fieldset'}
_BLOCKS = _REGIONS | {'document', 'html', 'body', 'div', 'p', 'pre', 'table',
                     'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'blockquote',
                     'address', 'figcaption', 'details', 'summary', 'form',
                     'tr', 'td', 'th', 'thead', 'tbody', 'tfoot', 'hr'}
_INLINE_BREAKS = {'br', 'hr'}
_REPLACEMENTS = str.maketrans({
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '--', '\u2026': '...', '\u2022': '*',
    '\u00a0': ' ', '\u00a9': '(c)', '\u00ae': '(R)',
})


def _ascii(value):
    value = unicodedata.normalize('NFKD', value.translate(_REPLACEMENTS))
    value = ''.join(char for char in value
                    if not unicodedata.combining(char)
                    and (not unicodedata.category(char).startswith('C')
                         or char in '\n\r\t'))
    return value.encode('ascii', 'replace').decode('ascii')


def _hints(node):
    return dict(node.hints)


def _is_block(node):
    return (node.tag in _BLOCKS or re.fullmatch(r'h[1-6]', node.tag)
            or _hints(node).get('display') in ('block', 'grid', 'flex'))


def _wrap(value, width, preserve=False):
    """Wrap every character, including long tokens, without clipping cells."""
    value = _ascii(value).replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
    if value.count('\n') >= MAX_LAYOUT_ROWS:
        raise LayoutError('The page has too many layout rows.')
    if preserve:
        result = []
        for line in value.split('\n'):
            if len(result) + max(1, (len(line) + width - 1) // width) > MAX_LAYOUT_ROWS:
                raise LayoutError('The page has too many layout rows.')
            # Slicing preserves indentation and spaces in code and diagrams.
            result.extend(line[pos:pos + width]
                          for pos in range(0, len(line), width))
            if not line:
                result.append('')
        return result
    result = []
    for line in value.split('\n'):
        words = ' '.join(line.split())
        if len(result) + max(1, (len(words) + width - 1) // width) > MAX_LAYOUT_ROWS:
            raise LayoutError('The page has too many layout rows.')
        result.extend(textwrap.wrap(words, width=width,
                                    break_long_words=True,
                                    break_on_hyphens=False) or [''])
        if len(result) > MAX_LAYOUT_ROWS:
            raise LayoutError('The page has too many layout rows.')
    return result


def _trim(rows):
    start, end = 0, len(rows)
    while start < end and not rows[start]:
        start += 1
    while end > start and not rows[end - 1]:
        end -= 1
    return rows[start:end]


def _join(parts, gap=1):
    rows = []
    characters = 0
    for part in parts:
        if not part:
            continue
        if rows and gap:
            rows.extend([''] * gap)
            characters += gap
        characters += sum(len(row) + 1 for row in part)
        if characters > MAX_LAYOUT_OUTPUT:
            raise LayoutError('The rendered layout is too large.')
        rows.extend(part)
        if len(rows) > MAX_LAYOUT_ROWS:
            raise LayoutError('The page has too many layout rows.')
    return rows


class _Parts:
    """Reject oversized sibling output while producing it, not afterwards."""

    def __init__(self):
        self.items = []
        self.rows = 0
        self.characters = 0

    def append(self, part):
        if not part:
            return
        gap = bool(self.items)
        self.rows += len(part) + gap
        self.characters += sum(len(row) + 1 for row in part) + gap
        if self.rows > MAX_LAYOUT_ROWS or self.characters > MAX_LAYOUT_OUTPUT:
            raise LayoutError('The rendered layout is too large.')
        self.items.append(part)


def _inline(node):
    if node.tag == 'br':
        return '\n'
    if node.tag == 'hr':
        return '\n--------------------\n'
    return node.text + ''.join(_inline(child) for child in node.children)


def _cell_text(node):
    """Flatten table content, retaining paragraph and explicit line breaks."""
    if node.tag in _INLINE_BREAKS:
        return '\n'
    value = node.text + ''.join(_cell_text(child) for child in node.children)
    if _is_block(node) and node.tag not in ('td', 'th'):
        value = '\n' + value + '\n'
    return value


def _box(label, rows, width):
    if width < 10:
        return _join([_wrap(label, width), rows]) if label else rows
    if len(rows) + 2 > MAX_LAYOUT_ROWS or (len(rows) + 2) * (width + 1) > MAX_LAYOUT_OUTPUT:
        raise LayoutError('The rendered layout is too large.')
    inside = width - 2
    title = (' ' + label + ' ') if label else ''
    if len(title) > inside:
        title = ''
    border = '+' + title + '-' * (inside - len(title)) + '+'
    bottom = '+' + '-' * inside + '+'
    return [border] + ['| ' + row.ljust(width - 4) + ' |' for row in rows or ['']] + [bottom]


def _shares(total, weights, minimum=1):
    """Distribute the exact available character count among columns."""
    remaining = total - minimum * len(weights)
    if remaining < 0:
        raise LayoutError('Columns cannot fit in this screen width.')
    weight_sum = sum(weights)
    portions = [remaining * weight / weight_sum for weight in weights]
    shares = [minimum + int(part) for part in portions]
    for index in sorted(range(len(shares)),
                        key=lambda item: portions[item] - int(portions[item]),
                        reverse=True)[:total - sum(shares)]:
        shares[index] += 1
    return shares


def _grid_weights(template):
    """Understand common explicit column counts; leave other CSS stacked."""
    template = template.strip().lower()
    repeated = re.fullmatch(r'repeat\(\s*([1-8])\s*,\s*[^;]+\)', template)
    if repeated:
        return [1.0] * int(repeated.group(1))
    # minmax and auto-fit require a full CSS sizing engine; simple fractions
    # and fixed CSS widths are enough to approximate ordinary two-column sites.
    if '(' in template or ')' in template:
        return None
    tokens = template.split()
    if not 1 <= len(tokens) <= MAX_TABLE_COLUMNS:
        return None
    weights = []
    for token in tokens:
        match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(fr|px|%|em|rem)', token)
        if token == 'auto':
            weights.append(1.0)
        elif match and float(match.group(1)) > 0:
            # Mixed fixed/fraction units are intentionally approximated.
            number = float(match.group(1))
            if match.group(2) == 'px':
                number /= 160
            elif match.group(2) == '%':
                number /= 50
            elif match.group(2) in ('em', 'rem'):
                number /= 20
            weights.append(min(1000.0, max(0.01, number)))
        else:
            return None
    return weights


class _Renderer:
    def _content(self, node, width):
        parts = []
        if node.text:
            parts.append(_wrap(node.text, width))
        parts.append(self._sequence(node.children, width))
        return _join(parts)

    def _sequence(self, children, width):
        parts, inline = _Parts(), ''
        index = 0

        def flush():
            nonlocal inline
            if inline.strip():
                parts.append(_trim(_wrap(inline, width)))
            inline = ''

        while index < len(children):
            child = children[index]
            # A site's semantic main/sidebar pair gives useful columns even
            # when its layout comes from an external stylesheet we do not fetch.
            following = index + 1
            while (following < len(children)
                   and children[following].tag == 'text'
                   and not children[following].text.strip()):
                following += 1
            if (child.tag in ('main', 'aside') and following < len(children)
                    and {child.tag, children[following].tag} == {'main', 'aside'}
                    and width >= 72):
                flush()
                pair = [child, children[following]]
                weights = [3.0 if item.tag == 'main' else 1.0 for item in pair]
                parts.append(self._columns(pair, width, weights))
                index = following + 1
                continue
            if _is_block(child):
                flush()
                parts.append(self.render(child, width))
            else:
                inline += _inline(child)
            index += 1
        flush()
        return _join(parts.items)

    def _columns(self, children, width, weights):
        gap = 2
        count = len(weights)
        if count < 2 or width < max(56, count * 22 + gap * (count - 1)):
            return _join(self.render(child, width) for child in children)
        sizes = _shares(width - gap * (count - 1), weights, minimum=18)
        parts = _Parts()
        for start in range(0, len(children), count):
            group = children[start:start + count]
            columns = []
            characters = 0
            for index, child in enumerate(group):
                column = self.render(child, sizes[index])
                characters += sum(len(row) + 1 for row in column)
                if characters > MAX_LAYOUT_OUTPUT:
                    raise LayoutError('The rendered layout is too large.')
                columns.append(column)
            if not columns:
                continue
            height = max(len(column) for column in columns)
            if height > MAX_LAYOUT_ROWS or height * (width + 1) > MAX_LAYOUT_OUTPUT:
                raise LayoutError('The rendered layout is too large.')
            rows = []
            for row in range(height):
                rows.append((' ' * gap).join(
                    (column[row] if row < len(column) else '').ljust(sizes[index])
                    for index, column in enumerate(columns)).rstrip())
            parts.append(rows)
        return _join(parts.items)

    def _flow(self, node, width):
        hints = _hints(node)
        children = [child for child in node.children
                    if child.tag != 'text' or child.text.strip()]
        display = hints.get('display')
        weights = None
        if display == 'grid':
            weights = _grid_weights(hints.get('grid-template-columns', ''))
        elif display == 'flex' and hints.get('flex-direction', 'row') not in ('column', 'column-reverse'):
            if len(children) <= MAX_TABLE_COLUMNS:
                weights = [1.0] * len(children)
        if weights and len(weights) > 1 and not node.text.strip():
            return self._columns(children, width, weights)
        return self._content(node, width)

    def _nav(self, node, width):
        # Lists of links become a compact navigation bar. Everything else uses
        # ordinary flow so descriptive text and headings are never discarded.
        children = [child for child in node.children
                    if child.tag != 'text' or child.text.strip()]
        if len(children) == 1 and children[0].tag in ('ul', 'ol'):
            children = [child for child in children[0].children
                        if child.tag != 'text' or child.text.strip()]
        if children and all(child.tag in ('a', 'li') for child in children):
            return _wrap(' | '.join(_inline(child).strip() for child in children), width)
        return self._flow(node, width)

    def _table_rows(self, node):
        rows = []
        pending = list(reversed(node.children))
        while pending:
            child = pending.pop()
            if child.tag == 'tr':
                cells = [cell for cell in child.children if cell.tag in ('td', 'th')]
                if cells:
                    rows.append(cells)
            elif child.tag != 'table':
                pending.extend(reversed(child.children))
        return rows

    def _table(self, node, width):
        rows = self._table_rows(node)
        if not rows:
            return self._content(node, width)
        # Captions remain visible. Other text outside table rows is retained
        # too, since malformed documents must not silently lose their content.
        extras = _Parts()

        def outside_rows(item):
            if item.tag == 'tr':
                for child in item.children:
                    if child.tag not in ('td', 'th'):
                        outside_rows(child)
                return
            if item.text.strip():
                extras.append(_wrap(item.text, width))
            for child in item.children:
                outside_rows(child)

        outside_rows(node)
        count = max(len(row) for row in rows)
        spans = any(_hints(cell).get('colspan', '1') != '1'
                    or _hints(cell).get('rowspan', '1') != '1'
                    for row in rows for cell in row)
        if count > MAX_TABLE_COLUMNS or width < count * 11 + 1 or spans:
            parts = _Parts()
            for index, row in enumerate(rows, 1):
                cells = _Parts()
                for column, cell in enumerate(row, 1):
                    cells.append(_wrap(f'{column}: ' + _cell_text(cell).strip(),
                                       max(1, width - 4) if width >= 10 else width))
                parts.append(_box(f'ROW {index}', _join(cells.items), width))
            return _join(extras.items + parts.items)
        # Borders plus one space on either side of each column consume 3n+1.
        available = width - 3 * count - 1
        natural = [1] * count
        for row in rows:
            for index, cell in enumerate(row):
                lines = _ascii(_cell_text(cell)).split('\n')
                natural[index] = max(natural[index], min(60, max(map(len, lines), default=1)))
        sizes = _shares(available, natural, minimum=4)
        border = '+' + '+'.join('-' * (size + 2) for size in sizes) + '+'
        result = [border]
        for row in rows:
            cells = [_wrap(_cell_text(cell).strip(), sizes[index],
                           preserve=any(child.tag == 'pre' for child in cell.children))
                     for index, cell in enumerate(row)]
            cells.extend([['']] * (count - len(cells)))
            height = max(map(len, cells))
            new_rows = len(result) + height + 1
            if new_rows > MAX_LAYOUT_ROWS or new_rows * (width + 1) > MAX_LAYOUT_OUTPUT:
                raise LayoutError('The rendered layout is too large.')
            for line in range(height):
                result.append('|' + '|'.join(
                    ' ' + (cell[line] if line < len(cell) else '').ljust(sizes[index]) + ' '
                    for index, cell in enumerate(cells)) + '|')
            fill = '=' if any(cell.tag == 'th' for cell in row) else '-'
            result.append('+' + '+'.join(fill * (size + 2) for size in sizes) + '+')
        return _join(extras.items + [result])

    def render(self, node, width):
        tag = node.tag
        if tag == 'text' or tag == 'img':
            return _trim(_wrap(_inline(node), width))
        if tag == 'br':
            return ['']
        if tag == 'hr':
            return ['-' * width]
        if tag == 'table':
            return self._table(node, width)
        if tag == 'pre':
            inside = max(1, width - 4) if width >= 10 else width
            return _box('PRE', _wrap(_inline(node), inside, preserve=True), width)
        if re.fullmatch(r'h[1-6]', tag):
            return _wrap('#' * int(tag[1]) + ' ' + _inline(node), width)
        if tag == 'li':
            if width < 4:
                return _wrap('* ' + _inline(node), width)
            rows = self._content(node, width - 2) or ['']
            return ['* ' + rows[0]] + ['  ' + row for row in rows[1:]]
        hints = _hints(node)
        border = hints.get('border', '').strip().lower()
        boxed = tag in _REGIONS or border and border not in ('none', '0', '0px')
        if boxed:
            inside = max(1, width - 4) if width >= 10 else width
            rows = self._nav(node, inside) if tag == 'nav' else self._flow(node, inside)
            return _box(tag.upper() if tag in _REGIONS else 'PANEL', rows, width)
        return self._flow(node, width)


def _validate(root):
    pending = [(root, 0)]
    seen, characters = 0, 0
    while pending:
        node, depth = pending.pop()
        if depth > MAX_LAYOUT_DEPTH:
            raise LayoutError('The page layout is nested too deeply.')
        if (not isinstance(getattr(node, 'tag', None), str)
                or not isinstance(getattr(node, 'text', None), str)
                or not isinstance(getattr(node, 'children', None), tuple)
                or not isinstance(getattr(node, 'hints', None), tuple)):
            raise LayoutError('The page has an invalid layout tree.')
        if len(node.tag) > 64 or not re.fullmatch(r'[a-z][a-z0-9-]*', node.tag):
            raise LayoutError('The page has an invalid layout tag.')
        for hint in node.hints:
            if (not isinstance(hint, tuple) or len(hint) != 2
                    or not all(isinstance(value, str) for value in hint)):
                raise LayoutError('The page has invalid layout hints.')
            characters += sum(map(len, hint))
        seen += 1
        characters += len(node.text)
        if seen > MAX_LAYOUT_NODES or characters > MAX_LAYOUT_TEXT:
            raise LayoutError('The page layout is too large.')
        pending.extend((child, depth + 1) for child in node.children)


def render_layout(root, width):
    """Return printable ASCII rows of at most ``width`` terminal cells.

    ``root`` is a ``desktop.apps.web_layout.LayoutNode``. Explicit failure
    allows the view to retain its plain-text alternative on oversized pages.
    """
    if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4096:
        raise LayoutError('The layout width is invalid.')
    _validate(root)
    rows = _trim(_Renderer().render(root, width))
    if len(rows) > MAX_LAYOUT_ROWS or sum(len(row) + 1 for row in rows) > MAX_LAYOUT_OUTPUT:
        raise LayoutError('The rendered layout is too large.')
    if any(len(row) > width or any(ord(char) < 32 or ord(char) > 126 for char in row)
           for row in rows):
        raise LayoutError('The rendered layout contains invalid terminal rows.')
    return tuple(rows)
