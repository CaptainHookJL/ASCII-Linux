"""Bookmark persistence, validation, and protection of externally edited data."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from desktop.apps.browser_data import (Bookmark, BookmarkStore, MAX_BOOKMARKS,
                                       MAX_FILE_BYTES, MAX_NAME_CHARS, MAX_URL_CHARS)
from desktop.apps.web_browser import normalize_url


class BookmarkStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'data/ascii-linux/browser-bookmarks.json'
        self.store = BookmarkStore(self.path)

    def write_records(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records), encoding='utf-8')

    def record(self, number=1):
        return {'name': f'Site {number}', 'url': f'https://example.test/{number}'}

    def test_missing_bookmarks_do_not_create_files(self):
        self.assertEqual(self.store.load(), [])
        self.assertFalse(self.path.parent.exists())

    def test_default_path_uses_absolute_xdg_data_home_with_home_fallback(self):
        for data_home, expected in [
                (str(self.root / 'shared'), self.root / 'shared/ascii-linux/browser-bookmarks.json'),
                ('relative/data', self.root / '.local/share/ascii-linux/browser-bookmarks.json'),
                ('', self.root / '.local/share/ascii-linux/browser-bookmarks.json')]:
            with self.subTest(data_home=data_home), mock.patch.dict(
                    os.environ, {'HOME': str(self.root), 'XDG_DATA_HOME': data_home}):
                self.assertEqual(BookmarkStore().path, expected)

    def test_roundtrip_preserves_names_normalizes_urls_and_creates_private_file(self):
        bookmark = self.store.add('  Café 東京  ', 'HTTPS://EXAMPLE.TEST/café?q=東京')
        self.assertEqual(bookmark, Bookmark('Café 東京',
                                          normalize_url('HTTPS://EXAMPLE.TEST/café?q=東京')))
        self.assertEqual(BookmarkStore(self.path).load(), [bookmark])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertIn('Café 東京', self.path.read_text())
        self.assertEqual(set(json.loads(self.path.read_text())[0]), {'name', 'url'})

    def test_existing_url_does_not_duplicate_or_rename_bookmark(self):
        saved = self.store.add('Original', 'https://EXAMPLE.TEST/1')
        original = self.path.read_bytes()
        identity = self.path.stat().st_ino
        duplicate = self.store.add('Different title', 'https://example.test/1')
        self.assertEqual(duplicate, saved)
        self.assertEqual(self.store.entries, [saved])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_ino, identity)

    def test_remove_preserves_permissions_and_cleans_temporary_files(self):
        first = self.store.add('First', 'https://example.test/1')
        self.path.chmod(0o640)
        self.store.load()
        second = self.store.add('Second', 'https://example.test/2')
        self.store.remove(first.url)
        self.assertEqual(BookmarkStore(self.path).load(), [second])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.store.remove(second.url)
        self.assertEqual(json.loads(self.path.read_text()), [])
        self.assertEqual(list(self.path.parent.glob('.ascii-bookmarks-*')), [])

    def test_invalid_inputs_do_not_create_bookmark_file(self):
        cases = [(None, 'https://example.test'), (' ', 'https://example.test'),
                 ('bad\nname', 'https://example.test'), ('bad\x1bname', 'https://example.test'),
                 ('x' * (MAX_NAME_CHARS + 1), 'https://example.test'),
                 ('Site', None), ('Site', ''), ('Site', 'https://example.test/\npath'),
                 ('Site', 'file:///etc/passwd'), ('Site', 'javascript:alert(1)'),
                 ('Site', 'ftp://example.test/file'),
                 ('Site', 'https://user:password@example.test'),
                 ('Site', 'https://example.test:99999'),
                 ('Site', 'https://example.test/' + 'x' * MAX_URL_CHARS)]
        for name, url in cases:
            with self.subTest(name=name[:40] if isinstance(name, str) else name,
                              url=url[:80] if isinstance(url, str) else url):
                with self.assertRaises(ValueError):
                    self.store.add(name, url)
                self.assertFalse(self.path.exists())
                self.assertEqual(self.store.entries, [])

    def test_invalid_existing_records_are_preserved(self):
        good = self.record()
        cases = [None, {}, [None], [dict(good, name=7)], [dict(good, url=7)],
                 [dict(good, name='')], [dict(good, name='bad\x00name')],
                 [dict(good, url='example.test')], [dict(good, url='file:///etc/passwd')],
                 [dict(good, url='https://example.test/\n')],
                 [dict(good, extra='preserve me')], [good, good]]
        for records in cases:
            with self.subTest(records=records):
                self.write_records(records)
                original = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    BookmarkStore(self.path).add('New', 'https://example.test/new')
                self.assertEqual(self.path.read_bytes(), original)

    def test_malformed_json_unicode_duplicate_fields_and_deep_nesting_are_preserved(self):
        self.path.parent.mkdir(parents=True)
        for raw in [b'not JSON', b'\xff', b'[{"name":"one","name":"two","url":"https://example.test"}]',
                    b'[' * 2000 + b']' * 2000]:
            with self.subTest(raw=raw[:60]):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    BookmarkStore(self.path).add('New', 'https://example.test/new')
                self.assertEqual(self.path.read_bytes(), raw)

    def test_limits_protect_existing_bookmarks(self):
        self.path.parent.mkdir(parents=True)
        oversized = b' ' * (MAX_FILE_BYTES + 1)
        self.path.write_bytes(oversized)
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.store.load()
        self.assertEqual(self.path.read_bytes(), oversized)
        self.write_records([self.record(number) for number in range(MAX_BOOKMARKS)])
        self.store.load()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'at most'):
            self.store.add('Extra', 'https://example.test/extra')
        self.assertEqual(self.path.read_bytes(), original)
        self.write_records([self.record(number) for number in range(MAX_BOOKMARKS + 1)])
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'at most'):
            self.store.load()
        self.assertEqual(self.path.read_bytes(), original)

    def test_external_creation_edits_delete_and_replacement_require_reload(self):
        self.store.load()
        self.write_records([self.record()])
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.store.add('New', 'https://example.test/new')
        self.assertEqual(self.path.read_bytes(), original)
        saved, = self.store.load()
        self.write_records([dict(self.record(), name='External title')])
        changed = self.path.read_bytes()
        for action in [lambda: self.store.add('New', 'https://example.test/new'),
                       lambda: self.store.add('Duplicate', saved.url),
                       lambda: self.store.remove(saved.url)]:
            with self.assertRaisesRegex(ValueError, 'changed outside'):
                action()
            self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(self.store.entries, [saved])
        reloaded, = self.store.load()
        self.assertEqual(reloaded.name, 'External title')
        replacement = self.root / 'replacement.json'
        replacement.write_bytes(changed)
        replacement.replace(self.path)
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.store.remove(saved.url)
        self.store.load()
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.store.add('New', 'https://example.test/new')
        self.assertFalse(self.path.exists())

    def test_prospective_encoded_size_is_checked_before_replacing_existing_file(self):
        records = [{'name': f'Site {number}',
                    'url': f'https://example.test/{number}/' + 'x' * 4020}
                   for number in range(MAX_BOOKMARKS - 1)]
        self.write_records(records)
        self.assertLess(self.path.stat().st_size, MAX_FILE_BYTES)
        self.store.load()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.store.add('Extra', 'https://example.test/' + 'x' * 8100)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(self.store.entries), MAX_BOOKMARKS - 1)
        self.assertEqual(list(self.path.parent.glob('.ascii-bookmarks-*')), [])

    def test_failed_reload_keeps_memory_and_refuses_to_erase_corrupt_data(self):
        saved = self.store.add('Saved', 'https://example.test/saved')
        self.path.write_text('broken JSON')
        with self.assertRaises(ValueError):
            self.store.load()
        self.assertEqual(self.store.entries, [saved])
        with self.assertRaises(ValueError):
            self.store.remove(saved.url)
        self.assertEqual(self.path.read_text(), 'broken JSON')

    def test_failed_write_preserves_file_and_memory_and_cleans_temporary_file(self):
        saved = self.store.add('Saved', 'https://example.test/saved')
        original = self.path.read_bytes()
        with mock.patch('desktop.apps.browser_data.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                self.store.add('New', 'https://example.test/new')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.store.entries, [saved])
        self.assertEqual(list(self.path.parent.glob('.ascii-bookmarks-*')), [])

    def test_concurrent_creation_before_publication_is_never_overwritten(self):
        original_link = os.link
        competing = json.dumps([self.record()]).encode()

        def concurrent_link(source, destination):
            self.path.write_bytes(competing)
            return original_link(source, destination)

        with mock.patch('desktop.apps.browser_data.os.link', side_effect=concurrent_link):
            with self.assertRaisesRegex(ValueError, 'created outside'):
                self.store.add('New', 'https://example.test/new')
        self.assertEqual(self.path.read_bytes(), competing)
        self.assertEqual(self.store.entries, [])
        self.assertEqual(list(self.path.parent.glob('.ascii-bookmarks-*')), [])

    def test_edit_during_temporary_write_is_detected_before_replace(self):
        saved = self.store.add('Saved', 'https://example.test/saved')
        original_fsync = os.fsync
        competing = json.dumps([self.record()]).encode()

        def concurrent_edit(descriptor):
            self.path.write_bytes(competing)
            return original_fsync(descriptor)

        with mock.patch('desktop.apps.browser_data.os.fsync', side_effect=concurrent_edit):
            with self.assertRaisesRegex(ValueError, 'changed outside'):
                self.store.remove(saved.url)
        self.assertEqual(self.path.read_bytes(), competing)
        self.assertEqual(self.store.entries, [saved])
        self.assertEqual(list(self.path.parent.glob('.ascii-bookmarks-*')), [])

    def test_symlinks_directories_and_fifos_are_refused_without_touching_them(self):
        self.path.parent.mkdir(parents=True)
        target = self.root / 'valuable.json'
        target.write_text('valuable data')
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.store.add('New', 'https://example.test/new')
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(), 'valuable data')
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.store.load()
        self.path.rmdir()
        os.mkfifo(self.path)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.store.load()
        self.assertTrue(stat.S_ISFIFO(self.path.lstat().st_mode))

    def test_removing_unknown_url_does_not_change_bookmarks(self):
        saved = self.store.add('Saved', 'https://example.test/saved')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'no longer'):
            self.store.remove('https://example.test/missing')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.store.entries, [saved])


if __name__ == '__main__':
    unittest.main()
