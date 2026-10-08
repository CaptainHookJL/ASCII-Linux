"""Cursor and clipping checks for Unicode and ASCII fallback rendering."""
import curses
import unittest
from unittest import mock

from desktop.apps.catalog import Application
from desktop.apps.text_editor import TextEditor
from desktop.core.desktop import Desktop
from desktop.widgets.dialog import Dialog
from desktop.widgets.apps import AppsSection


class DrawingScreen:
    """Record curses drawing without requiring an interactive terminal."""

    def __init__(self, height=28, width=110):
        self.size = height, width
        self.drawn = []

    def getmaxyx(self):
        return self.size

    def addstr(self, y, x, text, attr=0):
        self.drawn.append((y, x, text, attr))


def desktop_for_drawing(ascii_only=False, width=110):
    desktop = Desktop.__new__(Desktop)
    desktop.screen = DrawingScreen(width=width)
    desktop.ascii_only = ascii_only
    desktop.editor = TextEditor()
    desktop.editor_top = desktop.editor_left = 0
    return desktop


class UnicodeRenderingTests(unittest.TestCase):
    def test_user_app_wide_names_and_descriptions_stay_inside_home_panel(self):
        catalog = mock.Mock()
        catalog.load.return_value = [Application('mine', '界' * 50, ('true',), '界' * 70)]
        apps = AppsSection(catalog)
        for height, width in ((16, 86), (20, 86), (28, 110)):
            for ascii_only in (False, True):
                with self.subTest(height=height, width=width, ascii_only=ascii_only):
                    desktop = desktop_for_drawing(ascii_only, width)
                    desktop.screen.size = height, width
                    apps.render_home(desktop, height, width)
                    right_border = width - 5
                    content = [(x, text) for _, x, text, _ in desktop.screen.drawn
                               if 42 < x < right_border]
                    self.assertTrue(content)
                    for x, text in content:
                        self.assertLessEqual(x + desktop.width(text), right_border)

    def test_editor_cursor_aligns_with_wide_and_combining_text(self):
        for ascii_only, content, rendered, cells in [
                (False, '漢字', '漢字', 4),
                (True, '漢字', '??', 2),
                (False, 'e\u0301', 'e\u0301', 1),
                (True, 'e\u0301', 'e?', 2)]:
            with self.subTest(ascii_only=ascii_only, content=content):
                desktop = desktop_for_drawing(ascii_only)
                desktop.editor.insert(content)
                cursor = desktop.render_editor(28, 110)
                row, x, actual, _ = next(
                    item for item in desktop.screen.drawn if item[0] == 4 and item[1] == 7)
                self.assertEqual(actual, rendered)
                self.assertEqual(cursor, (row, x + cells))
                self.assertEqual(desktop.editor.lines, [content])

    def test_dialog_cursor_uses_cells_and_matches_ascii_fallback(self):
        for ascii_only, content, rendered, cells in [
                (False, '漢字é', '漢字é', 5),
                (True, '漢字é', '???', 3),
                (False, 'e\u0301', 'e\u0301', 1),
                (True, 'e\u0301', 'e?', 2)]:
            with self.subTest(ascii_only=ascii_only, content=content):
                desktop = desktop_for_drawing(ascii_only)
                dialog = Dialog('Save as', content)
                dialog.render(desktop.text, 28, 110, desktop.width)
                row, x, actual, _ = next(
                    item for item in desktop.screen.drawn if item[3] == curses.A_REVERSE)
                self.assertEqual(actual, rendered)
                self.assertEqual(dialog.cursor_position, (row, x + cells))
                self.assertEqual(dialog.value, content)

    def test_wide_editor_text_scrolls_and_keeps_cursor_inside_frame(self):
        desktop = desktop_for_drawing(width=60)
        desktop.editor.insert('界' * 40)
        row, cursor_x = desktop.render_editor(28, 60)
        _, x, text, _ = next(
            item for item in desktop.screen.drawn if item[0] == row and item[1] == 7)
        self.assertGreater(desktop.editor_left, 0)
        self.assertEqual(cursor_x, x + len(text) * 2)
        self.assertLess(cursor_x, 60 - 3)
        self.assertEqual(desktop.editor.lines, ['界' * 40])

    def test_long_wide_dialog_input_scrolls_inside_its_box(self):
        desktop = desktop_for_drawing()
        content = '界' * 50
        dialog = Dialog('Filename', content)
        dialog.render(desktop.text, 28, 110, desktop.width)
        row, x, text, _ = next(
            item for item in desktop.screen.drawn if item[3] == curses.A_REVERSE)
        self.assertLess(len(text), len(content))
        self.assertLess(len(text) * 2, 72)  # Interior of the 76-cell dialog.
        self.assertEqual(dialog.cursor_position, (row, x + len(text) * 2))
        self.assertEqual(dialog.value, content)


if __name__ == '__main__':
    unittest.main()
