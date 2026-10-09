"""Behavioral fixtures for the browser's responsive ASCII page layout."""
import unittest
from unittest.mock import patch

from desktop.apps.web_browser import render_html
from desktop.apps.web_layout import LayoutNode
from desktop.utils import ascii_layout
from desktop.utils.ascii_layout import LayoutError, render_layout


class AsciiLayoutTests(unittest.TestCase):
    def render(self, html, width=100):
        page = render_html(html, 'https://example.test/index')
        self.assertIsNotNone(page.layout)
        rows = render_layout(page.layout, width)
        self.assertTrue(all(len(row) <= width for row in rows))
        self.assertTrue(all(all(32 <= ord(char) <= 126 for char in row)
                            for row in rows))
        return page, rows

    def test_semantic_regions_and_sidebar_approximate_page_shape(self):
        html = '''<header><h1>Site title</h1></header>
                  <nav><a href="/news">News</a><a href="/about">About</a></nav>
                  <main><h2>Main story</h2><p>The article content.</p></main>
                  <aside><h2>Related</h2><p>Sidebar content.</p></aside>
                  <footer>Contact us</footer>'''
        page, rows = self.render(html)
        self.assertIn('HEADER', rows[0])
        self.assertTrue(any('MAIN' in row and 'ASIDE' in row for row in rows))
        self.assertTrue(any('Main story' in row and 'Related' in row for row in rows))
        self.assertTrue(any('News [1] | About [2]' in row for row in rows))
        self.assertIn('FOOTER', '\n'.join(rows))
        self.assertEqual([link.url for link in page.links],
                         ['https://example.test/news', 'https://example.test/about'])

    def test_narrow_terminal_stacks_sidebar_without_losing_text_or_links(self):
        html = '''<main>Main content <a href="/one">one</a></main>
                  <aside>Sidebar content <a href="/two">two</a></aside>'''
        _, rows = self.render(html, width=54)
        self.assertFalse(any('MAIN' in row and 'ASIDE' in row for row in rows))
        output = '\n'.join(rows)
        self.assertLess(output.index('MAIN'), output.index('ASIDE'))
        self.assertIn('Main content one [1]', output)
        self.assertIn('Sidebar content two [2]', output)

    def test_embedded_grid_css_gives_weighted_columns_and_stacks_on_resize(self):
        html = '''<style>.columns { display: grid; grid-template-columns: 1fr 3fr; }</style>
                  <div class="columns"><aside>Left panel</aside>
                  <main>Right panel with a longer article.</main></div>'''
        _, wide = self.render(html, width=110)
        row = next(row for row in wide if 'Left panel' in row)
        self.assertIn('Right panel', row)
        self.assertLess(row.index('Left panel'), row.index('Right panel'))
        _, narrow = self.render(html, width=54)
        self.assertFalse(any('Left panel' in row and 'Right panel' in row for row in narrow))
        self.assertIn('longer article.', '\n'.join(narrow))

    def test_grid_cards_wrap_into_additional_rows(self):
        html = '''<div style="display:grid;grid-template-columns:repeat(2, 1fr)">
                    <article>First card</article><article>Second card</article>
                    <article>Third card</article><article>Fourth card</article>
                  </div>'''
        _, rows = self.render(html)
        self.assertTrue(any('First card' in row and 'Second card' in row for row in rows))
        self.assertTrue(any('Third card' in row and 'Fourth card' in row for row in rows))
        _, narrow = self.render(html, width=54)
        output = '\n'.join(narrow)
        self.assertLess(output.index('First card'), output.index('Second card'))
        self.assertLess(output.index('Second card'), output.index('Third card'))

    def test_flex_row_and_column_preserve_source_content(self):
        html = '''<div style="display:flex"><section>First panel</section>
                  <section>Second panel</section></div>'''
        _, rows = self.render(html)
        self.assertTrue(any('First panel' in row and 'Second panel' in row for row in rows))
        html = html.replace('display:flex', 'display:flex;flex-direction:column')
        _, rows = self.render(html)
        self.assertFalse(any('First panel' in row and 'Second panel' in row for row in rows))

    def test_table_aligns_multiline_cells_and_link_markers(self):
        html = '''<table><caption>Team directory</caption>
                  <thead><tr><th>Name</th><th>Details</th></tr></thead>
                  <tbody><tr><td>Ada</td><td>First line<br>Second line
                  <a href="/ada">Profile</a></td></tr>
                  <tr><td>Grace</td><td>Another person</td></tr></tbody></table>'''
        page, rows = self.render(html, width=66)
        table_rows = [row for row in rows if row.startswith('|')]
        positions = [{index for index, char in enumerate(row) if char == '|'}
                     for row in table_rows]
        self.assertTrue(positions)
        self.assertTrue(all(position == positions[0] for position in positions))
        output = '\n'.join(rows)
        for text in ('Team directory', 'Name', 'Details', 'Ada', 'First line',
                     'Second line', 'Profile [1]', 'Grace', 'Another person'):
            self.assertIn(text, output)
        self.assertTrue(any(row.startswith('+') and '=' in row for row in rows))
        self.assertEqual(page.links[0].url, 'https://example.test/ada')

    def test_narrow_table_retains_every_cell_by_stacking(self):
        html = '<table><tr>' + ''.join(f'<th>Header {n}</th>' for n in range(4))
        html += '</tr><tr>' + ''.join(f'<td>Value {n}</td>' for n in range(4)) + '</tr></table>'
        _, rows = self.render(html, width=24)
        output = '\n'.join(rows)
        self.assertIn('ROW 1', output)
        self.assertIn('ROW 2', output)
        for number in range(4):
            self.assertIn(f'Header {number}', output)
            self.assertIn(f'Value {number}', output)

    def test_many_column_table_preserves_all_columns(self):
        html = '<table><tr>' + ''.join(f'<td>column-{n}</td>' for n in range(12)) + '</tr></table>'
        _, rows = self.render(html)
        output = '\n'.join(rows)
        for number in range(12):
            self.assertIn(f'column-{number}', output)

    def test_table_spans_use_lossless_stacked_rows(self):
        html = '''<table><tr><th colspan="2">Entire heading</th></tr>
                  <tr><td rowspan="2">Tall cell</td><td>Top cell</td></tr>
                  <tr><td>Bottom cell</td></tr></table>'''
        _, rows = self.render(html)
        output = '\n'.join(rows)
        for text in ('Entire heading', 'Tall cell', 'Top cell', 'Bottom cell'):
            self.assertIn(text, output)
        self.assertIn('ROW 3', output)

    def test_preformatted_diagram_preserves_spaces_and_breaks_long_lines(self):
        html = '<pre>  left    right\n    +---+\nabcdefghijklmno</pre>'
        _, rows = self.render(html, width=14)
        self.assertIn('|   left     |', rows)
        self.assertIn('| right      |', rows)
        self.assertIn('|     +---+  |', rows)
        self.assertIn('| abcdefghij |', rows)
        self.assertIn('| klmno      |', rows)

    def test_nested_boxes_and_lists_keep_every_paragraph(self):
        html = '''<main><section><h2>Features</h2><ul>
                  <li>First feature <a href="/a">details</a></li>
                  <li>Second feature<ol><li>Nested option</li></ol></li>
                  </ul><p>Last paragraph.</p></section></main>'''
        _, rows = self.render(html, width=54)
        output = '\n'.join(rows)
        for text in ('MAIN', 'SECTION', 'Features', '* First feature details [1]',
                     '* Second feature', 'Nested option', 'Last paragraph.'):
            self.assertIn(text, output)

    def test_ascii_sanitization_and_duplicate_link_numbers_are_retained(self):
        html = '''<section><p>Caf\u00e9 \u2014 Unicode \x1b[31m\x00</p>
                  <a href="/same">First link</a> <a href="/same">Second link</a>
                  <img alt="Map of the city"></section>'''
        page, rows = self.render(html)
        output = '\n'.join(rows)
        self.assertIn('Cafe -- Unicode', output)
        self.assertIn('First link [1]', output)
        self.assertIn('Second link [2]', output)
        self.assertIn('Map of the city', output)
        self.assertEqual([link.number for link in page.links], [1, 2])

    def test_css_hidden_content_does_not_reappear_in_layout(self):
        html = '''<style>.hidden {display:none}</style><main><p>Visible text</p>
                  <p class="hidden">Invisible text</p></main>'''
        _, rows = self.render(html)
        self.assertIn('Visible text', '\n'.join(rows))
        self.assertNotIn('Invisible text', '\n'.join(rows))

    def test_image_alts_survive_direct_grid_child_rendering(self):
        html = '''<div style="display:grid;grid-template-columns:1fr 1fr">
                  <img alt="Street map"><img alt="Building plan"></div>'''
        _, rows = self.render(html)
        self.assertTrue(any('Street map' in row and 'Building plan' in row for row in rows))

    def test_long_unbroken_content_is_wrapped_without_loss(self):
        token = 'abcdefghijklmnopqrstuvwxyz' * 8
        _, rows = self.render(f'<main>{token}</main>', width=23)
        content = ''.join(row[2:-2].rstrip() for row in rows if row.startswith('| '))
        self.assertEqual(content, token)

    def test_invalid_or_deep_tree_explicitly_requests_plain_text_fallback(self):
        with self.assertRaises(LayoutError):
            render_layout(None, 80)
        deep = LayoutNode('text', 'Visible content')
        for _ in range(60):
            deep = LayoutNode('div', children=(deep,))
        with self.assertRaisesRegex(LayoutError, 'deeply'):
            render_layout(deep, 80)
        for width in (0, -1, True, '80'):
            with self.assertRaises(LayoutError):
                render_layout(LayoutNode('document'), width)

    def test_resource_limits_allow_caller_to_keep_plain_text_view(self):
        root = LayoutNode('main', children=(LayoutNode('text', 'still readable'),))
        with patch('desktop.utils.ascii_layout.MAX_LAYOUT_NODES', 1):
            with self.assertRaisesRegex(LayoutError, 'too large'):
                render_layout(root, 80)
        with patch('desktop.utils.ascii_layout.MAX_LAYOUT_OUTPUT', 4):
            with self.assertRaisesRegex(LayoutError, 'too large'):
                render_layout(root, 80)

    def test_large_wrapped_words_and_padded_boxes_stop_at_resource_limits(self):
        root = LayoutNode('document', children=(LayoutNode('text', 'x' * 400),))
        with patch('desktop.utils.ascii_layout.MAX_LAYOUT_ROWS', 5):
            with self.assertRaisesRegex(LayoutError, 'too many'):
                render_layout(root, 20)
        root = LayoutNode('header', children=(LayoutNode('text', 'hello\nworld\nagain'),))
        with patch('desktop.utils.ascii_layout.MAX_LAYOUT_OUTPUT', 100):
            with self.assertRaisesRegex(LayoutError, 'too large'):
                render_layout(root, 40)

    def test_sibling_and_grid_outputs_stop_before_allocating_all_boxes(self):
        children = tuple(LayoutNode('pre', '\n' * 5) for _ in range(10))
        grid = LayoutNode('div', children=children,
                          hints=(('display', 'grid'),
                                 ('grid-template-columns', '1fr 1fr')))
        for root, width in ((LayoutNode('document', children=children), 100),
                            (grid, 100), (grid, 54)):
            with self.subTest(width=width, tag=root.tag):
                with patch('desktop.utils.ascii_layout.MAX_LAYOUT_OUTPUT', 1000), \
                        patch('desktop.utils.ascii_layout._box', wraps=ascii_layout._box) as boxes:
                    with self.assertRaisesRegex(LayoutError, 'too large'):
                        render_layout(root, width)
                    # Each box fits by itself; the combined budget must stop
                    # subsequent siblings instead of rendering all ten first.
                    self.assertLessEqual(boxes.call_count, 4)


if __name__ == '__main__':
    unittest.main()
