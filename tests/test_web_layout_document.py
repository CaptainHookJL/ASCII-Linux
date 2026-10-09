import dataclasses
import unittest
from unittest.mock import patch

from desktop.apps.web_browser import Page, render_html
from desktop.apps.web_layout import LayoutNode, document_size


URL = 'https://example.com/start'


def walk(root):
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def text(root):
    return ''.join(node.text for node in walk(root))


class LayoutDocumentTests(unittest.TestCase):
    def test_semantic_structure_inline_whitespace_and_numbered_links(self):
        page = render_html('''<html><head><title>Layout</title></head><body>
          <header><h1>Example</h1><nav><a href="/same">One</a> <a href="/same">Two</a></nav></header>
          <div><aside><p>Menu</p></aside><main><p>Hello <b>bold</b> world.</p></main></div>
          <footer>Copyright</footer></body></html>''', URL)
        self.assertIsInstance(page.layout, LayoutNode)
        tags = [node.tag for node in walk(page.layout)]
        for expected in ('header', 'nav', 'aside', 'main', 'footer', 'h1', 'p', 'b'):
            self.assertIn(expected, tags)
        self.assertNotIn('head', tags)
        self.assertNotIn('body', tags)
        self.assertIn('Hello bold world.', text(page.layout))
        self.assertIn('One [1] Two [2]', text(page.layout))
        self.assertEqual([link.url for link in page.links], ['https://example.com/same'] * 2)
        self.assertTrue(text(page.layout).isascii())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            page.layout.tag = 'changed'

    def test_css_specificity_inline_hints_and_unexecuted_resources(self):
        page = render_html('''<head><style>
          div { display: flex; width: 10ch; }
          .cards { display:grid; grid-template-columns: 1fr 3fr; }
          div.cards { width: 80%; border: 1px solid; }
          #container { display:flex; }
          .cards { gap:2ch; }
        </style><link href="https://unloaded.example/style.css" rel="stylesheet"></head>
        <div id="container" class="cards" style="display:grid; width:90%; flex-direction:column">
          <section>First</section><section>Second</section></div>''', URL)
        div = next(node for node in walk(page.layout) if node.tag == 'div')
        self.assertEqual(dict(div.hints), {
            'border': '1px solid', 'display': 'grid', 'flex-direction': 'column',
            'gap': '2ch', 'grid-template-columns': '1fr 3fr', 'width': '90%'})
        self.assertNotIn('unloaded.example', text(page.layout))
        self.assertNotIn('display:', text(page.layout))

    def test_body_css_applies_to_explicit_and_implicit_document(self):
        for body in ('<body class="page">Visible</body>', '<p>Visible</p>'):
            page = render_html('<style>body {display:grid;grid-template-columns:1fr 2fr}</style>'
                               + body, URL)
            self.assertEqual(dict(page.layout.hints)['display'], 'grid')
            self.assertEqual(dict(page.layout.hints)['grid-template-columns'], '1fr 2fr')
            self.assertIn('Visible', text(page.layout))
        hidden = render_html('<style>body {display:none}</style><main>Hidden</main>', URL)
        self.assertIsNotNone(hidden.layout)
        self.assertEqual(text(hidden.layout), '')

    def test_hidden_css_links_keep_original_duplicate_numbers(self):
        page = render_html('''<style>.hidden {display:none!important} #secret {visibility:hidden}</style>
          <a class="hidden" href="/same">Hidden first</a>
          <a href="/same">Visible second</a><div id="secret"><a href="/same">Hidden third</a></div>
          <a href="/last">Visible fourth</a>''', URL)
        rendered = text(page.layout)
        self.assertNotIn('Hidden', rendered)
        self.assertIn('Visible second [2]', rendered)
        self.assertIn('Visible fourth [4]', rendered)
        # The original reading view remains available without changing its data.
        self.assertIn('Hidden first [1]', page.text)
        self.assertEqual([link.number for link in page.links], [1, 2, 3, 4])

    def test_legacy_hidden_rules_and_base_do_not_change_link_mapping(self):
        page = render_html('''<head><base href="/manual/"><title>Heading</title>
          <main><div hidden><a href="no">Hidden</a></div>
          <div style="display:none"><a href="no">Hidden</a></div>
          <a href="javascript:bad()">Unsupported</a><a href="next"><img alt="Caf&eacute;"></a>
          <a href="last"></a></main>''', URL)
        rendered = text(page.layout)
        self.assertNotIn('Hidden', rendered)
        self.assertIn('[image: Cafe] [1]', rendered)
        self.assertIn('https://example.com/manual/last [2]', rendered)
        self.assertEqual(page.links[0].url, 'https://example.com/manual/next')

    def test_long_href_and_base_keep_following_link_numbers(self):
        long_path = '/' + 'a' * 5000
        page = render_html(f'<a href="{long_path}">Long</a><a href="/next">Next</a>', URL)
        self.assertEqual(page.links[0].url, 'https://example.com' + long_path)
        self.assertIn('Long [1]', text(page.layout))
        self.assertIn('Next [2]', text(page.layout))
        page = render_html(f'<head><base href="{long_path}/"></head>'
                           '<a href="next">Relative</a><a href="/last">Last</a>', URL)
        self.assertEqual(page.links[0].url, 'https://example.com' + long_path + '/next')
        self.assertIn('Relative [1]', text(page.layout))
        self.assertIn('Last [2]', text(page.layout))
        page = render_html('<a href="/' + 'a' * 8193 + '">Invalid</a>'
                           '<a href="/good">Good</a>', URL)
        self.assertEqual(len(page.links), 1)
        self.assertIn('Good [1]', text(page.layout))

    def test_table_cells_and_spans_preserve_all_content(self):
        page = render_html('''<table><thead><tr><th colspan="2">Title</th></tr></thead>
          <tbody><tr><td rowspan="2">Alpha</td><td>One</td></tr>
          <tr><td colspan="invalid">Two</td></tr></tbody></table>''', URL)
        cells = [node for node in walk(page.layout) if node.tag in ('td', 'th')]
        self.assertEqual([text(node) for node in cells], ['Title', 'Alpha', 'One', 'Two'])
        self.assertEqual(dict(cells[0].hints)['colspan'], '2')
        self.assertEqual(dict(cells[1].hints)['rowspan'], '2')
        self.assertEqual(dict(cells[-1].hints)['colspan'], 'unsupported')

    def test_pre_list_optional_endings_and_terminal_controls(self):
        page = render_html('''<ul><li>First<li>Second<ul><li>Nested</ul></ul>
          <pre>line one\n  line two\n\tline three</pre>
          <p>Safe\x1b[31m\x00\u202e caf&eacute;<br>Next</p>''', URL)
        ul = next(node for node in walk(page.layout) if node.tag == 'ul')
        self.assertEqual([child.tag for child in ul.children], ['li', 'li'])
        self.assertIn('Nested', text(ul.children[1]))
        pre = next(node for node in walk(page.layout) if node.tag == 'pre')
        self.assertEqual(text(pre), 'line one\n  line two\n    line three')
        rendered = text(page.layout)
        self.assertNotIn('\x1b', rendered)
        self.assertNotIn('\x00', rendered)
        self.assertNotIn('\u202e', rendered)
        self.assertTrue(rendered.isascii())

    def test_unsupported_css_nested_rules_and_scripts_are_ignored(self):
        page = render_html('''<style>
          @media (min-width: 1000px) { .cards { display:none } }
          main > .cards { display:none }
          .cards:hover { display:none }
          .cards { border: url(https://unused.example/image); display:grid }
        </style><main><section class="cards">Visible</section></main>
          <script>NEVER EXECUTE</script><iframe>NEVER LOAD</iframe>''', URL)
        section = next(node for node in walk(page.layout) if node.tag == 'section')
        self.assertEqual(dict(section.hints)['display'], 'grid')
        self.assertNotIn('border', dict(section.hints))
        self.assertIn('Visible', text(page.layout))
        self.assertNotIn('NEVER', text(page.layout))

    def test_layout_limits_keep_the_ordinary_page_readable(self):
        for setting, maximum, html in (
                ('MAX_LAYOUT_NODES', 5, '<p>One</p><p>Two</p><p>Three</p>'),
                ('MAX_LAYOUT_DEPTH', 4, '<div>' * 5 + 'Deep' + '</div>' * 5),
                ('MAX_LAYOUT_TEXT', 4, '<p>Still readable</p>')):
            with self.subTest(setting=setting), patch('desktop.apps.web_layout.' + setting, maximum):
                page = render_html(html, URL)
                self.assertIsNone(page.layout)
                self.assertTrue(page.text)

    def test_page_history_size_includes_structure_but_plain_pages_do_not(self):
        page = render_html('<main><p>Small page</p></main>', URL)
        plain = Page(page.url, page.title, page.lines, page.links)
        self.assertEqual(page.size - plain.size, document_size(page.layout))
        self.assertGreater(page.size, plain.size)
        self.assertIsNone(plain.layout)


if __name__ == '__main__':
    unittest.main()
