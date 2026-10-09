"""Browser controls stay usable across slow loads, page wrapping and resizing."""
import curses
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from desktop.apps.browser_data import Bookmark, BookmarkStore
from desktop.apps.web_browser import Link, Page, render_html
from desktop.apps.web_layout import LayoutNode
from desktop.core.web_browser_view import MAX_FIND_MATCHES, WebBrowserView, wrap_lines


def controller(page=None, dimensions=(16, 60), bookmarks=None):
    desktop = SimpleNamespace(page='web', message='', text=Mock(), prompt=Mock(), confirm=Mock(),
                              screen=SimpleNamespace(getmaxyx=lambda: dimensions))
    browser = SimpleNamespace(page=page, busy=False, error='', loading_url='',
                              poll=Mock(return_value=False), navigate=Mock(return_value=True),
                              follow=Mock(return_value=True), back=Mock(return_value=False),
                              forward=Mock(return_value=False), reload=Mock(return_value=True),
                              cancel=Mock(return_value=False), close=Mock())
    if bookmarks is None:
        bookmarks = SimpleNamespace(entries=[], load=Mock(return_value=[]), add=Mock(), remove=Mock())
    view = WebBrowserView(desktop, browser, bookmarks)
    view.opened()
    return desktop, browser, view


class BrowserViewTests(unittest.TestCase):
    def test_opening_a_blank_browser_makes_no_request_and_reports_supported_content(self):
        desktop, browser, view = controller()
        view.opened()
        view.render(16, 60)
        browser.navigate.assert_not_called()
        browser.reload.assert_not_called()
        output = '\n'.join(call.args[2] for call in desktop.text.call_args_list)
        self.assertIn('G opens a URL', output)
        self.assertIn('No scripts, external styles, media, or forms.', output)

    def test_reopening_and_failed_background_load_preserve_page_scroll_and_link(self):
        page = Page('https://example.com/', 'Initial', tuple('line ' + str(i) for i in range(30)),
                    (Link(1, 'First', 'https://example.com/first'),
                     Link(2, 'Second', 'https://example.com/second')))
        desktop, browser, view = controller(page)
        view.handle(curses.KEY_NPAGE)
        view.handle('\t')
        self.assertEqual(view.offset, 4)
        self.assertEqual(view.link_selected, 1)
        desktop.page = 'home'
        browser.error = 'HTTP 404 Not Found'
        view.tick()
        self.assertIs(browser.page, page)
        self.assertEqual(view.offset, 4)
        desktop.page = 'web'
        view.opened()
        self.assertEqual(view.offset, 4)
        self.assertEqual(view.link_selected, 1)
        self.assertIn('404', desktop.message)
        view.handle('\r')
        browser.follow.assert_called_once_with(2)

    def test_address_prompt_cancel_and_invalid_input_leave_selection_and_page(self):
        page = Page('https://example.com/', 'Page', ('Original',))
        desktop, browser, view = controller(page)
        desktop.prompt.return_value = None
        view.handle('g')
        browser.navigate.assert_not_called()
        desktop.prompt.assert_called_once_with('Open web URL', page.url)
        desktop.prompt.return_value = 'file:///etc/passwd'
        browser.navigate.side_effect = ValueError('Only HTTP and HTTPS pages can be opened.')
        view.handle('g')
        self.assertIs(browser.page, page)
        self.assertIn('Only HTTP and HTTPS', desktop.message)

    def test_ascii_rendering_wraps_without_losing_text_at_minimum_size(self):
        lines = ('Café\x1b[31m \t' + 'A very long line ' * 16, '', '漢字')
        page = Page('https://example.com/', 'Café 漢字', lines)
        desktop, _, view = controller(page)
        view.render(16, 60)
        output = [call.args[2] for call in desktop.text.call_args_list]
        self.assertTrue(all(text.isascii() and all(' ' <= c <= '~' for c in text) for text in output))
        self.assertIn('Title: Cafe ??', output)
        body = view._body(54)
        self.assertTrue(all(len(text) <= 54 for text, _, _, _ in body))
        self.assertEqual(''.join(text for text, index, _, _ in body if index == 0),
                         'Cafe [31m   ' + 'A very long line ' * 16)
        self.assertTrue(all(4 <= call.args[0] <= 12 for call in desktop.text.call_args_list))

    def test_find_crosses_wrapped_rows_and_reflows_after_resize(self):
        line = ('A' * 50) + 'Needle' + ('B' * 80) + 'needle'
        desktop, _, view = controller(Page('https://example.com/', 'Long', (line,)))
        desktop.prompt.return_value = 'NEEDLE'
        view.handle('/')
        self.assertEqual(view.matches, [(0, 50), (0, 136)])
        self.assertEqual(desktop.message, 'Match 1/2')
        view.handle('n')
        self.assertEqual(desktop.message, 'Match 2/2')
        self.assertEqual(view.match_index, 1)
        desktop.screen.getmaxyx = lambda: (16, 100)
        view.render(16, 100)
        self.assertEqual(view.offset, 0)
        self.assertEqual(view.match_index, 1)

    def test_find_match_collection_is_bounded_for_repeated_text(self):
        desktop, _, view = controller(Page('https://example.com/', 'Large', ('a' * 50000,)))
        desktop.prompt.return_value = 'a'
        view.handle('/')
        self.assertEqual(len(view.matches), MAX_FIND_MATCHES)
        self.assertTrue(view.matches_truncated)
        self.assertEqual(desktop.message, 'Match 1/4096+')

    def test_layout_toggle_preserves_selected_link_search_and_loaded_page(self):
        page = render_html('<header>Site</header><nav><a href="/one">One</a>'
                           '<a href="/two">Two</a></nav><main><p>First needle</p>'
                           '<p>' + 'padding text ' * 25 + '</p><p>Second needle</p></main>',
                           'https://example.com/')
        desktop, browser, view = controller(page, dimensions=(16, 100))
        view.handle('\t')
        desktop.prompt.return_value = 'needle'
        view.handle('/')
        view.handle('n')
        self.assertEqual(view.match_index, 1)
        for mode in (False, True):
            view.handle('l')
            self.assertEqual(view.layout_enabled, mode)
            self.assertEqual(view.query, 'needle')
            self.assertEqual(view.match_index, 1)
            self.assertEqual(view.link_selected, 1)
            view.render(16, 100)
            highlighted = [call.args[2] for call in desktop.text.call_args_list
                           if len(call.args) > 3 and call.args[3] == curses.A_REVERSE]
            self.assertTrue(any('Second needle' in line for line in highlighted))
            desktop.text.reset_mock()
        self.assertIs(browser.page, page)
        browser.navigate.assert_not_called()
        browser.reload.assert_not_called()
        view.handle('\r')
        browser.follow.assert_called_once_with(2)

    def test_oversized_layout_falls_back_to_searchable_text_with_correct_mode(self):
        root = LayoutNode('#text', text='Unreachable layout')
        for _ in range(55):
            root = LayoutNode('section', children=(root,))
        page = Page('https://example.com/', 'Complex', ('Readable fallback needle',), layout=root)
        desktop, browser, view = controller(page)
        self.assertIn('showing text', desktop.message)
        desktop.prompt.return_value = 'needle'
        view.handle('/')
        self.assertEqual(desktop.message, 'Match 1/1')
        view.render(16, 60)
        output = [call.args[2] for call in desktop.text.call_args_list]
        self.assertIn('Readable fallback needle', output)
        self.assertTrue(any(line.startswith('L Text |') for line in output))
        self.assertIs(browser.page, page)
        browser.reload.assert_not_called()

    def test_loading_while_terminal_is_tiny_keeps_reflow_at_usable_width(self):
        text = 'word ' * 2000
        for page in (Page('https://example.com/', 'Text', (text,)),
                     render_html('<main>' + text + '</main>', 'https://example.com/')):
            with self.subTest(layout=page.layout is not None):
                desktop, browser, view = controller(page, dimensions=(5, 7))
                self.assertLess(len(view._body(view._dimensions()[1])), 250)
                view.handle(curses.KEY_END)
                desktop.screen.getmaxyx = lambda: (16, 60)
                view.render(16, 60)
                self.assertIs(browser.page, page)
                browser.reload.assert_not_called()

    def test_resize_clamps_scroll_without_resetting_page(self):
        desktop, browser, view = controller(Page('https://example.com/', 'List', tuple(map(str, range(30)))))
        view.handle(curses.KEY_END)
        self.assertEqual(view.offset, 26)
        desktop.screen.getmaxyx = lambda: (40, 110)
        view.render(40, 110)
        self.assertEqual(view.offset, 2)
        view.opened()
        self.assertEqual(view.offset, 2)
        browser.navigate.assert_not_called()

    def test_busy_request_can_be_cancelled_and_poll_does_not_wait_for_worker(self):
        desktop, browser, view = controller(Page('https://example.com/', 'Current', ('Current body',)))
        browser.busy, browser.loading_url = True, 'https://slow.example/'
        view.render(16, 60)
        self.assertIn('Loading: https://slow.example/', [call.args[2] for call in desktop.text.call_args_list])
        browser.cancel.return_value = True
        view.handle('x')
        self.assertEqual(desktop.message, 'Page load cancelled')
        view.tick()
        browser.poll.assert_called_once_with()
        view.close()
        browser.close.assert_called_once_with()

    def test_bookmarks_are_persisted_opened_and_removed_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BookmarkStore(Path(directory) / 'bookmarks.json')
            page = Page('https://example.com/', 'Saved title', ('Body',))
            desktop, browser, view = controller(page, bookmarks=store)
            view.handle('b')
            self.assertEqual(desktop.message, 'Bookmarked: Saved title')
            view.handle('m')
            self.assertTrue(view.show_bookmarks)
            desktop.confirm.return_value = False
            view.handle('d')
            self.assertEqual(store.entries, [Bookmark('Saved title', page.url)])
            view.handle('\r')
            browser.navigate.assert_called_once_with(page.url)
            self.assertFalse(view.show_bookmarks)
            view.handle('m')
            desktop.confirm.return_value = True
            view.handle('d')
            self.assertEqual(store.entries, [])
            self.assertEqual(BookmarkStore(store.path).load(), [])
            self.assertEqual(desktop.message, 'Bookmark removed: Saved title')

    def test_long_page_title_can_be_bookmarked_and_bad_storage_keeps_browser_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bookmarks.json'
            page = Page('https://example.com/', 'T' * 512, ('Body',))
            desktop, _, view = controller(page, bookmarks=BookmarkStore(path))
            view.handle('b')
            self.assertEqual(len(view.bookmarks.entries[0].name), 256)
            original = b'{"not": "bookmarks"}'
            path.write_bytes(original)
            view.handle('m')
            self.assertTrue(view.show_bookmarks)
            self.assertTrue(view.bookmark_error)
            view.handle('b')
            self.assertTrue(desktop.message.startswith('Web:'))
            self.assertEqual(path.read_bytes(), original)
            view.handle('m')
            self.assertFalse(view.show_bookmarks)

    def test_word_wrapping_retains_empty_lines_long_urls_and_whitespace(self):
        logical = ('word  word words', '', 'https://example.com/' + 'x' * 80, '    indented')
        wrapped = wrap_lines(logical, 8)
        self.assertEqual([''.join(text for text, i, _, _ in wrapped if i == index)
                          for index in range(len(logical))], list(logical))
        self.assertTrue(all(len(text) <= 8 for text, _, _, _ in wrapped))


if __name__ == '__main__':
    unittest.main()
