"""Undo/redo correctness, save baselines and bounded editor history."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from desktop.apps.text_editor import (
    FileChangedError, MAX_FILE_BYTES, MAX_HISTORY_BYTES,
    MAX_HISTORY_SNAPSHOTS, TextEditor,
)


class EditorHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def assert_document(self, editor, lines, cursor, dirty):
        self.assertEqual(editor.lines, lines)
        self.assertEqual((editor.row, editor.column), cursor)
        self.assertEqual(editor.dirty, dirty)

    def state(self, editor):
        return (tuple(editor.lines), editor.row, editor.column, editor.path,
                editor.dirty, editor._version, editor._saved_content,
                tuple(editor._undo), tuple(editor._redo), editor._history_bytes)

    def test_empty_history_is_a_no_op(self):
        editor = TextEditor()
        before = self.state(editor)
        self.assertFalse(editor.can_undo)
        self.assertFalse(editor.can_redo)
        self.assertFalse(editor.undo())
        self.assertFalse(editor.redo())
        self.assertEqual(self.state(editor), before)

    def test_unicode_insert_restores_before_and_after_cursors(self):
        editor = TextEditor()
        editor.insert('café\n猫😀')
        self.assert_document(editor, ['café', '猫😀'], (1, 2), True)
        editor.home()
        self.assertTrue(editor.undo())
        self.assert_document(editor, [''], (0, 0), False)
        self.assertFalse(editor.can_undo)
        self.assertTrue(editor.can_redo)
        self.assertTrue(editor.redo())
        self.assert_document(editor, ['café', '猫😀'], (1, 2), True)
        self.assertTrue(editor.can_undo)
        self.assertFalse(editor.can_redo)

    def test_insert_split_backspace_join_and_delete_join_replay(self):
        editor = TextEditor()
        editor.insert('hello\nworld')
        editor.home()
        editor.backspace()
        self.assert_document(editor, ['helloworld'], (0, 5), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['hello', 'world'], (1, 0), True)
        self.assertTrue(editor.redo())
        self.assert_document(editor, ['helloworld'], (0, 5), True)
        editor.insert('\n')
        self.assert_document(editor, ['hello', 'world'], (1, 0), True)
        editor.move(dc=-1)
        editor.delete()
        self.assert_document(editor, ['helloworld'], (0, 5), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['hello', 'world'], (0, 5), True)
        self.assertTrue(editor.redo())
        self.assert_document(editor, ['helloworld'], (0, 5), True)

    def test_unicode_backspace_and_delete_each_have_one_undo_step(self):
        editor = TextEditor()
        editor.insert('é猫😀')
        editor.backspace()
        self.assert_document(editor, ['é猫'], (0, 2), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['é猫😀'], (0, 3), True)
        self.assertTrue(editor.redo())
        self.assert_document(editor, ['é猫'], (0, 2), True)
        editor.home()
        editor.delete()
        self.assert_document(editor, ['猫'], (0, 0), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['é猫'], (0, 0), True)
        self.assertTrue(editor.redo())
        self.assert_document(editor, ['猫'], (0, 0), True)

    def test_open_and_crlf_history_preserve_original_baseline_and_endings(self):
        path = self.root / 'windows.txt'
        original = 'café\r\n猫\r\n'.encode()
        path.write_bytes(original)
        editor = TextEditor.open(path)
        self.assertFalse(editor.can_undo)
        self.assertFalse(editor.can_redo)
        editor.end()
        editor.insert('\r\n😀\r\n')
        self.assert_document(editor, ['café', '😀', '', '猫', ''], (2, 0), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['café', '猫', ''], (0, 4), False)
        self.assertTrue(editor.redo())
        editor.save()
        self.assertEqual(path.read_bytes(), 'café\r\n😀\r\n\r\n猫\r\n'.encode())
        self.assertFalse(editor.dirty)
        self.assertTrue(editor.undo())
        self.assertTrue(editor.dirty)
        self.assertEqual(editor._bytes(), original)
        self.assertTrue(editor.redo())
        self.assertFalse(editor.dirty)

    def test_dirty_is_content_comparison_even_without_undo(self):
        path = self.root / 'document.txt'
        path.write_text('abc')
        editor = TextEditor.open(path)
        editor.delete()
        self.assertTrue(editor.dirty)
        editor.insert('a')
        self.assertFalse(editor.dirty)
        self.assertTrue(editor.undo())
        self.assertTrue(editor.dirty)
        self.assertTrue(editor.redo())
        self.assertFalse(editor.dirty)

    def test_undo_and_redo_across_save_keep_correct_clean_state(self):
        editor = TextEditor()
        editor.insert('first')
        editor.save(self.root / 'document.txt')
        editor.insert(' second')
        editor.save()
        editor.insert(' third')
        self.assertTrue(editor.dirty)
        self.assertTrue(editor.undo())
        self.assertFalse(editor.dirty)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['first'], (0, 5), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, [''], (0, 0), True)
        self.assertTrue(editor.redo())
        self.assertTrue(editor.dirty)
        self.assertTrue(editor.redo())
        self.assertFalse(editor.dirty)
        self.assertTrue(editor.redo())
        self.assertTrue(editor.dirty)
        self.assertEqual((self.root / 'document.txt').read_text(), 'first second')

    def test_save_after_undo_preserves_redo_and_updates_clean_baseline(self):
        editor = TextEditor()
        editor.insert('one')
        editor.insert('two')
        editor.undo()
        editor.save(self.root / 'document.txt')
        self.assertFalse(editor.dirty)
        self.assertTrue(editor.can_redo)
        self.assertTrue(editor.redo())
        self.assert_document(editor, ['onetwo'], (0, 6), True)
        self.assertTrue(editor.undo())
        self.assert_document(editor, ['one'], (0, 3), False)

    def test_new_edit_invalidates_redo_for_all_edit_operations(self):
        for operation in ('insert', 'backspace', 'delete'):
            with self.subTest(operation=operation):
                editor = TextEditor()
                editor.insert('abc')
                editor.insert('d')
                editor.undo()
                self.assertTrue(editor.can_redo)
                if operation == 'insert':
                    editor.insert('!')
                    expected, cursor = ['abc!'], (0, 4)
                elif operation == 'backspace':
                    editor.backspace()
                    expected, cursor = ['ab'], (0, 2)
                else:
                    editor.home()
                    editor.delete()
                    expected, cursor = ['bc'], (0, 0)
                self.assertFalse(editor.can_redo)
                self.assertFalse(editor.redo())
                self.assert_document(editor, expected, cursor, True)
                self.assertTrue(editor.undo())
                self.assertEqual(editor.lines, ['abc'])
                self.assertTrue(editor.redo())
                self.assert_document(editor, expected, cursor, True)

    def test_navigation_search_and_save_do_not_add_history(self):
        editor = TextEditor()
        editor.insert('one\ntwo one')
        before = len(editor._undo), editor._history_bytes
        editor.move(dr=-1, dc=-100)
        editor.end()
        editor.home()
        editor.find('one')
        editor.find('missing')
        editor.save(self.root / 'document.txt')
        self.assertEqual((len(editor._undo), editor._history_bytes), before)
        self.assertTrue(editor.undo())
        self.assert_document(editor, [''], (0, 0), True)
        self.assertFalse(editor.can_undo)

    def test_no_op_edits_do_not_add_history_or_invalidate_redo(self):
        editor = TextEditor()
        editor.insert('abc')
        editor.undo()
        before = self.state(editor)
        editor.insert('')
        editor.backspace()
        editor.delete()
        self.assertEqual(self.state(editor), before)
        self.assertTrue(editor.redo())
        editor.delete()
        self.assertEqual(len(editor._undo), 1)
        self.assertEqual(editor.lines, ['abc'])

    def test_failed_insert_preserves_cursor_dirty_and_history(self):
        editor = TextEditor()
        editor.insert('keep')
        editor.insert(' next')
        editor.undo()
        before = self.state(editor)
        for text in ('\x00', '\x7f', 'x' * MAX_FILE_BYTES):
            with self.subTest(text_length=len(text)):
                with self.assertRaises(ValueError):
                    editor.insert(text)
                self.assertEqual(self.state(editor), before)
        self.assertTrue(editor.redo())
        self.assertEqual(editor.lines, ['keep next'])

    def test_snapshot_count_limit_discards_only_oldest_edits(self):
        editor = TextEditor()
        retained_edits = MAX_HISTORY_SNAPSHOTS // 2
        for _ in range(retained_edits + 5):
            editor.insert('x')
        self.assertEqual(len(editor._undo), retained_edits)
        for _ in range(retained_edits):
            self.assertTrue(editor.undo())
        self.assertEqual(editor.lines, ['xxxxx'])
        self.assertFalse(editor.undo())
        self.assertTrue(editor.dirty)
        self.assertLessEqual(2 * (len(editor._undo) + len(editor._redo)),
                             MAX_HISTORY_SNAPSHOTS)
        for _ in range(retained_edits):
            self.assertTrue(editor.redo())
        self.assertFalse(editor.redo())
        self.assertEqual(editor.lines, ['x' * (retained_edits + 5)])

    def test_byte_limit_retains_useful_history_for_one_mib_document(self):
        path = self.root / 'large.txt'
        path.write_bytes(b'x' * MAX_FILE_BYTES)
        editor = TextEditor.open(path)
        editor.end()
        for _ in range(8):
            editor.backspace()
        self.assertEqual(len(editor._undo), 4)
        self.assertLessEqual(editor._history_bytes, MAX_HISTORY_BYTES)
        expected_bytes = sum(change.utf8_bytes for change in editor._undo)
        self.assertEqual(editor._history_bytes, expected_bytes)
        for _ in range(4):
            self.assertTrue(editor.undo())
        self.assertFalse(editor.undo())
        self.assertEqual(len(editor.lines[0]), MAX_FILE_BYTES - 4)
        self.assertTrue(editor.dirty)
        self.assertEqual(editor._history_bytes, expected_bytes)
        for _ in range(4):
            self.assertTrue(editor.redo())
        self.assertEqual(len(editor.lines[0]), MAX_FILE_BYTES - 8)

    def test_history_byte_accounting_uses_utf8_and_drops_discarded_redo(self):
        editor = TextEditor()
        editor.insert('é')
        editor.insert('😀')
        self.assertEqual(editor._history_bytes, 2 + 2 + 6)
        editor.undo()
        editor.insert('猫')
        self.assertEqual(editor._history_bytes, 2 + 2 + 5)
        self.assertFalse(editor.can_redo)
        with mock.patch('desktop.apps.text_editor.MAX_HISTORY_BYTES', 16):
            editor.insert('界')
        self.assertLessEqual(editor._history_bytes, 16)
        self.assertEqual(len(editor._undo), 1)

    def test_failed_atomic_overwrite_preserves_history_and_saved_baseline(self):
        for failing_operation in ('os.fsync', 'os.replace'):
            with self.subTest(operation=failing_operation):
                path = self.root / 'document.txt'
                path.write_text('original')
                editor = TextEditor.open(path)
                editor.end()
                editor.insert(' next')
                editor.insert('!')
                editor.undo()
                before = self.state(editor)
                with mock.patch('desktop.apps.text_editor.' + failing_operation,
                                side_effect=OSError('simulated failure')):
                    with self.assertRaisesRegex(OSError, 'simulated failure'):
                        editor.save()
                self.assertEqual(self.state(editor), before)
                self.assertEqual(path.read_text(), 'original')
                self.assertEqual(list(self.root.glob('.ascii-editor-*')), [])
                self.assertTrue(editor.undo())
                self.assertFalse(editor.dirty)
                self.assertTrue(editor.redo())
                self.assertTrue(editor.dirty)
                self.assertTrue(editor.redo())
                self.assertEqual(editor.lines, ['original next!'])

    def test_failed_atomic_save_as_preserves_untitled_history(self):
        editor = TextEditor()
        editor.insert('ours')
        editor.insert('!')
        editor.undo()
        before = self.state(editor)
        path = self.root / 'new.txt'
        with mock.patch('desktop.apps.text_editor.os.link',
                        side_effect=OSError('simulated failure')):
            with self.assertRaisesRegex(OSError, 'simulated failure'):
                editor.save(path)
        self.assertEqual(self.state(editor), before)
        self.assertFalse(path.exists())
        self.assertEqual(list(self.root.glob('.ascii-editor-*')), [])
        self.assertTrue(editor.undo())
        self.assertFalse(editor.dirty)
        self.assertTrue(editor.redo())
        self.assertTrue(editor.redo())
        self.assertEqual(editor.lines, ['ours!'])

    def test_conflict_and_read_only_save_failures_preserve_history(self):
        for failure in ('conflict', 'read_only'):
            with self.subTest(failure=failure):
                path = self.root / 'document.txt'
                path.write_text('original')
                editor = TextEditor.open(path)
                editor.end()
                editor.insert(' ours')
                before = self.state(editor)
                if failure == 'conflict':
                    path.write_text('theirs')
                    exception = FileChangedError
                else:
                    path.chmod(0o444)
                    # Reopen after changing mode so the version check passes
                    # and the save specifically reaches the permission check.
                    editor = TextEditor.open(path)
                    editor.end()
                    editor.insert(' ours')
                    before = self.state(editor)
                    exception = PermissionError
                with self.assertRaises(exception):
                    editor.save()
                self.assertEqual(self.state(editor), before)
                self.assertTrue(editor.undo())
                self.assertFalse(editor.dirty)
                self.assertTrue(editor.redo())
                self.assertTrue(editor.dirty)
                path.chmod(0o600)


if __name__ == '__main__':
    unittest.main()
