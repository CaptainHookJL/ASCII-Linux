"""Editing and filesystem safety checks for the plain-text editor."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from desktop.apps.text_editor import FileChangedError, MAX_FILE_BYTES, TextEditor


class TextEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_insert_split_join_delete_and_boundaries(self):
        editor = TextEditor()
        editor.backspace()
        editor.delete()
        self.assertFalse(editor.dirty)
        editor.insert('hello\nworld')
        self.assertEqual(editor.lines, ['hello', 'world'])
        self.assertEqual((editor.row, editor.column), (1, 5))
        editor.home()
        editor.backspace()
        self.assertEqual(editor.lines, ['helloworld'])
        self.assertEqual((editor.row, editor.column), (0, 5))
        editor.insert('\n')
        editor.move(dc=-1)
        self.assertEqual((editor.row, editor.column), (0, 5))
        editor.delete()
        self.assertEqual(editor.lines, ['helloworld'])
        editor.backspace()
        self.assertEqual(editor.lines, ['hellworld'])
        editor.move(dc=100)
        editor.delete()
        self.assertEqual((editor.row, editor.column), (0, 9))
        editor.move(dc=-100)
        self.assertEqual((editor.row, editor.column), (0, 0))

    def test_vertical_clamping_and_unicode_columns(self):
        editor = TextEditor()
        editor.insert('long line\n短\nlast')
        editor.move(dr=-2)
        self.assertEqual((editor.row, editor.column), (0, 4))
        editor.end()
        editor.move(dr=1)
        self.assertEqual((editor.row, editor.column), (1, 1))
        editor.move(dc=1)
        self.assertEqual((editor.row, editor.column), (2, 0))
        editor.insert('é')
        self.assertEqual(editor.lines[2], 'élast')
        self.assertEqual(editor.column, 1)
        editor.move(dr=100)
        self.assertEqual(editor.row, 2)

    def test_search_advances_wraps_and_can_cross_lines(self):
        editor = TextEditor()
        editor.insert('one\ntwo one')
        editor.move(dc=-100)
        self.assertTrue(editor.find('one'))
        self.assertEqual((editor.row, editor.column), (1, 4))
        self.assertTrue(editor.find('one'))
        self.assertEqual((editor.row, editor.column), (0, 0))
        self.assertTrue(editor.find('one\ntwo'))
        self.assertEqual((editor.row, editor.column), (0, 0))
        self.assertFalse(editor.find('missing'))
        self.assertFalse(editor.find(''))
        self.assertEqual((editor.row, editor.column), (0, 0))

    def test_new_files_require_name_and_remain_editable_after_save(self):
        editor = TextEditor()
        with self.assertRaisesRegex(ValueError, 'file name'):
            editor.save()
        editor.insert('snowman ☃\n')
        path = self.root / 'new.txt'
        editor.save(path)
        self.assertEqual(editor.path, path)
        self.assertEqual(path.read_bytes(), 'snowman ☃\n'.encode())
        self.assertFalse(editor.dirty)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        editor.insert('next')
        editor.save()
        self.assertEqual(path.read_bytes(), 'snowman ☃\nnext'.encode())
        self.assertEqual(list(self.root.glob('.ascii-editor-*')), [])

    def test_roundtrip_empty_unicode_final_newline_and_line_endings(self):
        path = self.root / 'example.txt'
        for content in [b'', b'\n', b'no final newline', 'café\n東京\n'.encode(),
                        'café\r\n東京\r\n'.encode(), b'\r\n\r\n']:
            with self.subTest(content=content):
                path.write_bytes(content)
                path.chmod(0o640)
                editor = TextEditor.open(path)
                self.assertGreaterEqual(len(editor.lines), 1)
                editor.save()
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_crlf_edits_preserve_line_convention(self):
        path = self.root / 'windows.txt'
        path.write_bytes(b'first\r\nlast')
        editor = TextEditor.open(path)
        editor.end()
        editor.insert('\nnew')
        editor.save()
        self.assertEqual(path.read_bytes(), b'first\r\nnew\r\nlast')

    def test_save_as_refuses_existing_destinations_and_retains_document(self):
        original = self.root / 'original.txt'
        original.write_text('original')
        destination = self.root / 'existing.txt'
        destination.write_text('valuable')
        editor = TextEditor.open(original)
        editor.insert('changed ')
        with self.assertRaises(FileExistsError):
            editor.save(destination)
        self.assertEqual(destination.read_text(), 'valuable')
        self.assertEqual(editor.path, original)
        self.assertTrue(editor.dirty)
        editor.save(self.root / 'copy.txt')
        self.assertEqual(original.read_text(), 'original')
        self.assertEqual(editor.path, self.root / 'copy.txt')

    def test_save_as_no_clobber_when_another_writer_wins_race(self):
        editor = TextEditor()
        editor.insert('ours')
        destination = self.root / 'race.txt'
        real_link = os.link

        def competing_writer(source, target):
            Path(target).write_text('theirs')
            return real_link(source, target)

        with mock.patch('desktop.apps.text_editor.os.link', side_effect=competing_writer):
            with self.assertRaises(FileExistsError):
                editor.save(destination)
        self.assertEqual(destination.read_text(), 'theirs')
        self.assertTrue(editor.dirty)
        self.assertIsNone(editor.path)
        self.assertEqual(list(self.root.glob('.ascii-editor-*')), [])

    def test_external_edits_are_not_overwritten_even_with_restored_mtime(self):
        path = self.root / 'shared.txt'
        path.write_text('before')
        editor = TextEditor.open(path)
        editor.insert('ours ')
        before = path.stat()
        path.write_text('theirs')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(FileChangedError, 'changed outside'):
            editor.save()
        self.assertEqual(path.read_text(), 'theirs')
        self.assertTrue(editor.dirty)
        editor.save(self.root / 'recovered.txt')
        self.assertEqual((self.root / 'recovered.txt').read_text(), 'ours before')

    def test_external_replacement_and_removal_are_not_overwritten(self):
        path = self.root / 'document.txt'
        path.write_text('old')
        editor = TextEditor.open(path)
        replacement = self.root / 'replacement.txt'
        replacement.write_text('replacement')
        replacement.replace(path)
        with self.assertRaises(FileChangedError):
            editor.save()
        self.assertEqual(path.read_text(), 'replacement')
        editor = TextEditor.open(path)
        path.unlink()
        with self.assertRaises(FileChangedError):
            editor.save()
        self.assertFalse(path.exists())

    def test_existing_symlink_resolves_and_dangling_save_target_is_refused(self):
        target = self.root / 'target.txt'
        target.write_text('target')
        link = self.root / 'link.txt'
        link.symlink_to(target)
        editor = TextEditor.open(link)
        self.assertEqual(editor.path, target)
        editor.insert('updated ')
        editor.save(link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), 'updated target')
        dangling = self.root / 'dangling.txt'
        dangling.symlink_to(self.root / 'missing.txt')
        with self.assertRaises(FileExistsError):
            editor.save(dangling)
        self.assertFalse((self.root / 'missing.txt').exists())

    def test_replaced_final_symlink_cannot_redirect_a_save(self):
        path = self.root / 'original.txt'
        path.write_text('old')
        victim = self.root / 'victim.txt'
        victim.write_text('valuable')
        editor = TextEditor.open(path)
        editor.insert('changed')
        path.unlink()
        path.symlink_to(victim)
        with self.assertRaises(FileExistsError):
            editor.save()
        self.assertEqual(victim.read_text(), 'valuable')
        self.assertTrue(path.is_symlink())

    def test_binary_invalid_utf8_mixed_endings_and_special_files_are_refused(self):
        path = self.root / 'unsafe'
        for content in [b'a\x00b', b'a\x01b', b'\xff\xfe', b'a\r\nb\n', b'a\rb']:
            with self.subTest(content=content):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    TextEditor.open(path)
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'regular'):
            TextEditor.open(fifo)
        with self.assertRaises((ValueError, IsADirectoryError)):
            TextEditor.open(self.root)

    def test_oversize_open_and_insert_are_bounded(self):
        path = self.root / 'large.txt'
        with path.open('wb') as stream:
            stream.truncate(MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            TextEditor.open(path)
        editor = TextEditor()
        editor.insert('keep')
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            editor.insert('x' * MAX_FILE_BYTES)
        self.assertEqual(editor.lines, ['keep'])
        self.assertEqual(editor.column, 4)

    def test_read_only_file_does_not_get_replaced(self):
        path = self.root / 'readonly.txt'
        path.write_text('protected')
        path.chmod(0o444)
        editor = TextEditor.open(path)
        editor.insert('changed ')
        with self.assertRaisesRegex(PermissionError, 'read-only'):
            editor.save()
        self.assertEqual(path.read_text(), 'protected')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)


if __name__ == '__main__':
    unittest.main()
