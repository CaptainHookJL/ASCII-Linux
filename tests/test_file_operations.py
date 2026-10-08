"""Filesystem behavior: collisions, tree operations, search and failure cleanup."""
import errno
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest import mock

from desktop.apps.file_manager import FileManager, _rename_no_replace, preview


class FileOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.browser = FileManager(self.root)

    def select(self, path):
        self.browser.set_query('')
        self.browser.refresh()
        self.browser.selected = self.browser.entries.index(self.root / path)

    def test_preview_supports_symlinks_and_rejects_fifo_swap_without_blocking(self):
        source = self.root / 'text'
        source.write_text('read through the link')
        link = self.root / 'link'
        link.symlink_to(source.name)
        self.assertEqual(preview(link), ['read through the link'])
        actual_open = os.open

        def swapped_before_open(path, flags, *args, **kwargs):
            self.assertEqual(Path(path), source)
            # Check before attempting the open, so this regression test never
            # hangs if blocking flags are accidentally reintroduced.
            self.assertTrue(flags & os.O_NONBLOCK)
            self.assertTrue(flags & os.O_NOFOLLOW)
            source.unlink()
            os.mkfifo(source)
            return actual_open(path, flags, *args, **kwargs)

        with mock.patch('desktop.apps.file_manager.os.open', side_effect=swapped_before_open):
            self.assertEqual(preview(link), ['Preview is available for regular files only.'])

    def test_casefold_filter_hidden_files_and_navigation(self):
        (self.root / 'Folder').mkdir()
        (self.root / 'Straße.txt').write_text('text')
        (self.root / '.STRASSE').touch()
        self.browser.refresh()
        self.browser.set_query('STRASSE')
        self.assertEqual(self.browser.selected_entry.name, 'Straße.txt')
        self.browser.hidden = True
        self.browser.refresh()
        self.assertEqual([p.name for p in self.browser.entries], ['.STRASSE', 'Straße.txt'])
        self.browser.set_query('missing')
        self.assertIsNone(self.browser.selected_entry)
        with self.assertRaisesRegex(ValueError, 'Select'):
            self.browser.delete_selected()
        self.browser.navigate(self.root / 'Folder')
        self.assertEqual(self.browser.query, '')
        self.assertIsNone(self.browser.selected_entry)

    def test_create_rename_and_reject_unsafe_or_existing_names(self):
        created = self.browser.mkdir('work')
        self.assertEqual(created, self.browser.selected_entry)
        created.chmod(0o750)
        renamed = self.browser.rename_to('renamed')
        self.assertFalse(created.exists())
        self.assertEqual(renamed, self.browser.selected_entry)
        self.assertEqual(stat.S_IMODE(renamed.stat().st_mode), 0o750)
        for name in ('', '.', '..', '../outside', '/absolute', 'nested/name', 'bad\x00name'):
            with self.assertRaises(ValueError):
                self.browser.mkdir(name)
            with self.assertRaises(ValueError):
                self.browser.rename_to(name)
        (self.root / 'taken').symlink_to('does-not-exist')
        with self.assertRaises(FileExistsError):
            self.browser.rename_to('taken')
        self.assertTrue(renamed.is_dir())
        self.assertTrue((self.root / 'taken').is_symlink())
        with self.assertRaises(FileExistsError):
            self.browser.mkdir('taken')

    def test_file_copy_progress_permissions_and_existing_directory_target(self):
        source = self.root / 'source.txt'
        content = b'abc' * 800000
        source.write_bytes(content)
        source.chmod(0o751)
        os.utime(source, ns=(1234567890000000000, 1234567891234567890))
        destination = self.root / 'target'
        destination.mkdir()
        self.select('source.txt')
        reports = []
        copied = self.browser.copy_to('target', lambda done, total: reports.append((done, total)))
        self.assertEqual(copied, destination / 'source.txt')
        self.assertEqual(copied.read_bytes(), content)
        self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o751)
        self.assertEqual(copied.stat().st_mtime_ns, source.stat().st_mtime_ns)
        self.assertEqual(reports[0], (0, len(content)))
        self.assertEqual(reports[-1], (len(content), len(content)))
        self.assertTrue(all(before[0] <= after[0] for before, after in zip(reports, reports[1:])))
        self.assertEqual(source.read_bytes(), content)

    def test_tree_copy_preserves_links_and_delete_never_follows_them(self):
        external = self.root / 'external'
        external.mkdir()
        (external / 'keep.txt').write_text('keep')
        source = self.root / 'tree'
        (source / 'nested').mkdir(parents=True)
        (source / 'nested' / 'text').write_text('tree content')
        (source / 'linked-folder').symlink_to(external, target_is_directory=True)
        (source / 'dangling').symlink_to('missing')
        (source / 'self-link').symlink_to('.', target_is_directory=True)
        self.select('tree')
        copied = self.browser.copy_to('tree-copy')
        self.assertEqual((copied / 'nested' / 'text').read_text(), 'tree content')
        self.assertTrue((copied / 'linked-folder').is_symlink())
        self.assertEqual(os.readlink(copied / 'linked-folder'), str(external))
        self.assertEqual(os.readlink(copied / 'dangling'), 'missing')
        reports = []
        self.browser.delete_selected(lambda done, total: reports.append((done, total)))
        self.assertFalse(copied.exists())
        self.assertTrue(source.exists())
        self.assertEqual((external / 'keep.txt').read_text(), 'keep')
        self.assertEqual(reports[-1], (len('tree content'), len('tree content')))

    def test_copy_symlink_itself_including_dangling_link(self):
        link = self.root / 'link'
        link.symlink_to('missing')
        self.select('link')
        duplicate = self.browser.copy_to('duplicate')
        self.assertTrue(duplicate.is_symlink())
        self.assertEqual(os.readlink(duplicate), 'missing')
        self.browser.delete_selected()
        self.assertFalse(os.path.lexists(duplicate))
        self.assertTrue(link.is_symlink())

    def test_copy_move_collision_and_directory_recursion_are_rejected(self):
        source = self.root / 'tree'
        source.mkdir()
        (source / 'content').write_text('unchanged')
        (source / 'nested').mkdir()
        (self.root / 'taken').symlink_to('missing')
        self.select('tree')
        for method in (self.browser.copy_to, self.browser.move_to):
            with self.assertRaises(FileExistsError):
                method('taken')
            with self.assertRaisesRegex(ValueError, 'into itself'):
                method('tree/nested')
            with self.assertRaises(NotADirectoryError):
                method('missing/child')
        self.assertEqual((source / 'content').read_text(), 'unchanged')
        self.assertTrue((self.root / 'taken').is_symlink())
        (self.root / 'alias').symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'into itself'):
            self.browser.copy_to('alias/new')

    def test_special_files_rejected_before_copy_and_can_be_deleted(self):
        source = self.root / 'tree'
        source.mkdir()
        (source / 'ordinary').write_text('preserve')
        os.mkfifo(source / 'pipe')
        unix_socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(unix_socket.close)
        unix_socket.bind(str(source / 'socket'))
        self.select('tree')
        with self.assertRaisesRegex(ValueError, 'special file'):
            self.browser.copy_to('copy')
        self.assertFalse((self.root / 'copy').exists())
        self.assertEqual((source / 'ordinary').read_text(), 'preserve')
        self.browser.delete_selected()
        self.assertFalse(source.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_copy_cleans_staging_and_preserves_original(self):
        source = self.root / 'original'
        source.write_bytes(b'x' * (2 * 1024 * 1024))
        self.select('original')

        def fail_after_first_chunk(done, total):
            if done:
                raise OSError(errno.ENOSPC, 'Simulated full disk')

        with self.assertRaisesRegex(OSError, 'full disk'):
            self.browser.copy_to('copy', fail_after_first_chunk)
        self.assertEqual(source.stat().st_size, 2 * 1024 * 1024)
        self.assertFalse((self.root / 'copy').exists())
        self.assertEqual([p.name for p in self.root.iterdir()], ['original'])

    def test_destination_created_during_copy_is_preserved(self):
        source = self.root / 'original'
        source.write_text('source content')
        self.select('original')
        target = self.root / 'copy'

        def concurrent_destination(done, total):
            if done and not target.exists():
                target.write_text('keep concurrent file')

        with self.assertRaises(FileExistsError):
            self.browser.copy_to('copy', concurrent_destination)
        self.assertEqual(target.read_text(), 'keep concurrent file')
        self.assertEqual(source.read_text(), 'source content')
        self.assertFalse(any(path.name.startswith('.ascii-copy-') for path in self.root.iterdir()))

    def test_local_move_with_fifo_does_not_scan_or_read_children(self):
        source = self.root / 'tree'
        source.mkdir()
        (source / 'ordinary').write_text('keep')
        os.mkfifo(source / 'pipe')
        inode = source.stat().st_ino
        self.select('tree')
        reports = []
        with mock.patch('desktop.apps.file_manager._copy_size',
                        side_effect=AssertionError('Local move must not scan the tree')):
            moved = self.browser.move_to('moved', lambda done, total: reports.append((done, total)))
        self.assertFalse(source.exists())
        self.assertEqual(moved.stat().st_ino, inode)
        self.assertTrue(stat.S_ISFIFO((moved / 'pipe').lstat().st_mode))
        self.assertEqual((moved / 'ordinary').read_text(), 'keep')
        self.assertEqual(moved, self.browser.selected_entry)
        self.assertEqual(reports[-1], (0, 0))
        with self.assertRaisesRegex(ValueError, 'special file'):
            self.browser.copy_to('copy')
        self.assertFalse((self.root / 'copy').exists())

    def test_move_local_and_cross_device_tree_preserve_contents(self):
        source = self.root / 'original'
        source.mkdir()
        (source / 'text').write_text('move me')
        (source / 'link').symlink_to('text')
        self.select('original')
        first = self.browser.move_to('local')
        self.assertFalse(source.exists())
        self.assertEqual(first, self.browser.selected_entry)
        with mock.patch('desktop.apps.file_manager._rename_no_replace') as rename:
            def cross_device_once(src, dst):
                if src == first:
                    raise OSError(errno.EXDEV, 'Simulated cross-device move')
                return _rename_no_replace(src, dst)
            rename.side_effect = cross_device_once
            moved = self.browser.move_to('across')
        self.assertFalse(first.exists())
        self.assertEqual((moved / 'text').read_text(), 'move me')
        self.assertEqual(os.readlink(moved / 'link'), 'text')
        self.assertEqual(moved, self.browser.selected_entry)

    def test_cross_device_move_keeps_copy_if_source_removal_fails(self):
        source = self.root / 'original'
        source.write_text('keep data')
        self.select('original')
        with mock.patch('desktop.apps.file_manager._rename_no_replace') as rename:
            def cross_device_once(src, dst):
                if src == source:
                    raise OSError(errno.EXDEV, 'Simulated cross-device move')
                return _rename_no_replace(src, dst)
            rename.side_effect = cross_device_once
            with mock.patch('desktop.apps.file_manager._delete_node',
                            side_effect=PermissionError(errno.EACCES, 'Cannot remove original')):
                with self.assertRaisesRegex(OSError, 'Copy retained'):
                    self.browser.move_to('moved')
        self.assertEqual(source.read_text(), 'keep data')
        self.assertEqual((self.root / 'moved').read_text(), 'keep data')
        self.assertEqual(self.browser.selected_entry, self.root / 'moved')

    def test_expanduser_destination_and_failed_move_leave_original(self):
        source = self.root / 'original'
        source.write_text('keep')
        self.select('original')
        with mock.patch.dict(os.environ, HOME=str(self.root)):
            copied = self.browser.copy_to('~/copy')
        self.assertEqual(copied, self.root / 'copy')
        self.select('original')
        with mock.patch('desktop.apps.file_manager._rename_no_replace', side_effect=PermissionError('Denied')):
            with self.assertRaises(PermissionError):
                self.browser.move_to('moved')
        self.assertEqual(source.read_text(), 'keep')
        self.assertFalse((self.root / 'moved').exists())


if __name__ == '__main__':
    unittest.main()
