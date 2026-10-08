"""User application persistence, command parsing and catalog write integrity."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from desktop.apps.catalog import (Application, AppCatalog, MAX_APPS, MAX_COMMAND_CHARS,
                                  MAX_FILE_BYTES, validate_install_command)


class AppCatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'data/ascii-linux/apps.json'
        self.catalog = AppCatalog(self.path)

    def write_records(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records), encoding='utf-8')

    def record(self, app_id='1'):
        return {'id': app_id, 'name': 'Personal app', 'command': ['my-app', 'argument'],
                'description': 'My tool'}

    def test_missing_catalog_starts_empty_without_creating_files(self):
        self.assertEqual(self.catalog.entries, [])
        self.assertEqual(self.catalog.load(), [])
        self.assertFalse(self.path.parent.exists())

    def test_default_path_uses_absolute_xdg_data_home_and_ignores_relative_paths(self):
        for data_home, expected in [
                (str(self.root / 'shared'), self.root / 'shared/ascii-linux/apps.json'),
                ('relative/data', self.root / '.local/share/ascii-linux/apps.json'),
                ('', self.root / '.local/share/ascii-linux/apps.json')]:
            with self.subTest(data_home=data_home), mock.patch.dict(
                    os.environ, {'HOME': str(self.root), 'XDG_DATA_HOME': data_home}):
                self.assertEqual(AppCatalog().path, expected)

    def test_add_persists_unicode_and_parses_quoted_arguments_without_shell_expansion(self):
        entry = self.catalog.add('Café 東京', 'python3 -c "print(\'hello world\')" "" "$HOME" ";"',
                                 'A personal text tool')
        self.assertEqual(entry.command, ('python3', '-c', "print('hello world')", '', '$HOME', ';'))
        self.assertEqual(AppCatalog(self.path).load(), [entry])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertIn('Café 東京', self.path.read_text())
        self.assertEqual(set(json.loads(self.path.read_text())[0]),
                         {'id', 'name', 'command', 'description'})

    def test_tilde_executable_expands_but_relative_executable_stays_relative(self):
        with mock.patch.dict(os.environ, {'HOME': str(self.root)}):
            expanded = self.catalog.add('Home tool', '"~/my tools/run" "a b"')
        relative = self.catalog.add('Relative tool', './app.sh --option')
        self.assertEqual(expanded.command, (str(self.root / 'my tools/run'), 'a b'))
        self.assertEqual(relative.command, ('./app.sh', '--option'))

    def test_add_remove_roundtrip_and_existing_mode_is_preserved(self):
        first = self.catalog.add('First', 'first')
        self.path.chmod(0o640)
        self.catalog.load()
        second = self.catalog.add('Second', 'second --flag')
        self.catalog.remove(first.id)
        self.assertEqual(AppCatalog(self.path).load(), [second])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.catalog.remove(second.id)
        self.assertEqual(json.loads(self.path.read_text()), [])
        self.assertEqual(AppCatalog(self.path).load(), [])
        self.assertEqual(list(self.path.parent.glob('.ascii-apps-*')), [])

    def test_empty_and_invalid_names_commands_and_descriptions_do_not_create_data(self):
        cases = [(None, 'app', ''), ('', 'app', ''), ('   ', 'app', ''),
                 ('bad\x00name', 'app', ''), ('bad\nname', 'app', ''),
                 ('App', None, ''), ('App', '', ''), ('App', '   ', ''),
                 ('App', 'app\x00', ''), ('App', 'app\nother', ''),
                 ('App', 'app', None), ('App', 'app', 'hidden\x1b'),
                 ('x' * 129, 'app', ''), ('App', 'app', 'x' * 1025)]
        for name, command, description in cases:
            with self.subTest(name=name, command=command, description=description):
                with self.assertRaises(ValueError):
                    self.catalog.add(name, command, description)
                self.assertEqual(self.catalog.entries, [])
                self.assertFalse(self.path.exists())

    def test_unmatched_quotes_and_quoted_empty_executable_are_rejected(self):
        for command in ['app "unfinished', 'app \\', '""', '"" argument', '"   " argument']:
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.catalog.add('App', command)
        self.assertFalse(self.path.exists())

    def test_invalid_existing_records_are_never_replaced(self):
        good = self.record()
        cases = [None, {}, [None], [dict(good, name=7)], [dict(good, command='app')],
                 [dict(good, command=[])], [dict(good, command=[''])],
                 [dict(good, command=['app', 7])], [dict(good, command=['app', '\n'])],
                 [dict(good, name='bad\x00')], [dict(good, description=[])],
                 [dict(good, id='')], [dict(good, unexpected='keep this')], [good, good]]
        for records in cases:
            with self.subTest(records=records):
                self.write_records(records)
                original = self.path.read_bytes()
                catalog = AppCatalog(self.path)
                with self.assertRaises(ValueError):
                    catalog.load()
                with self.assertRaises(ValueError):
                    catalog.add('New', 'new')
                self.assertEqual(self.path.read_bytes(), original)

    def test_malformed_utf8_json_duplicate_fields_and_deep_nesting_are_preserved(self):
        self.path.parent.mkdir(parents=True)
        cases = [b'not JSON', b'\xff', b'[{"id":"1","id":"2"}]',
                 b'[' * 2000 + b']' * 2000]
        for raw in cases:
            with self.subTest(raw=raw[:50]):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    AppCatalog(self.path).add('App', 'app')
                self.assertEqual(self.path.read_bytes(), raw)

    def test_size_and_entry_limits_protect_existing_files(self):
        self.path.parent.mkdir(parents=True)
        oversized = b' ' * (MAX_FILE_BYTES + 1)
        self.path.write_bytes(oversized)
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.catalog.load()
        self.assertEqual(self.path.read_bytes(), oversized)
        self.write_records([self.record(str(index)) for index in range(MAX_APPS + 1)])
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'at most'):
            self.catalog.add('New', 'new')
        self.assertEqual(self.path.read_bytes(), original)

    def test_simple_external_ids_and_optional_description_load(self):
        record = self.record('1')
        del record['description']
        self.write_records([record, self.record('8')])
        entries = self.catalog.load()
        self.assertEqual([entry.id for entry in entries], ['1', '8'])
        self.assertEqual(entries[0].description, '')

    def test_external_catalog_creation_is_detected_before_add(self):
        self.catalog.load()
        self.write_records([self.record()])
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.add('New', 'new')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.catalog.entries, [])

    def test_external_edits_block_add_and_remove_until_reload(self):
        saved = self.catalog.add('Saved', 'saved')
        records = json.loads(self.path.read_text())
        records[0]['description'] = 'Changed in another program'
        self.write_records(records)
        changed = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.add('New', 'new')
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.remove(saved.id)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(self.catalog.entries, [saved])
        self.catalog.load()
        self.catalog.add('New', 'new')
        self.assertEqual(AppCatalog(self.path).load()[0].description, 'Changed in another program')

    def test_external_delete_and_same_content_replacement_are_detected(self):
        saved = self.catalog.add('Saved', 'saved')
        original = self.path.read_bytes()
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.add('New', 'new')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.catalog.entries, [saved])
        self.path.write_bytes(original)
        self.catalog.load()
        replacement = self.root / 'replacement.json'
        replacement.write_bytes(original)
        replacement.replace(self.path)
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.remove(saved.id)
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_reload_keeps_memory_and_refuses_to_erase_corrupt_data(self):
        saved = self.catalog.add('Saved', 'saved')
        self.path.write_text('broken JSON')
        with self.assertRaises(ValueError):
            self.catalog.load()
        self.assertEqual(self.catalog.entries, [saved])
        with self.assertRaises(ValueError):
            self.catalog.remove(saved.id)
        self.assertEqual(self.path.read_text(), 'broken JSON')

    def test_write_failure_keeps_saved_data_and_cleans_temporary_file(self):
        saved = self.catalog.add('Saved', 'saved')
        original = self.path.read_bytes()
        with mock.patch('desktop.apps.catalog.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                self.catalog.add('New', 'new')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.catalog.entries, [saved])
        self.assertEqual(list(self.path.parent.glob('.ascii-apps-*')), [])
        self.catalog.add('New', 'new')
        self.assertEqual(len(AppCatalog(self.path).load()), 2)

    def test_new_catalog_publish_failure_keeps_memory_empty(self):
        with mock.patch('desktop.apps.catalog.os.link', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.catalog.add('New', 'new')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.catalog.entries, [])
        self.assertEqual(list(self.path.parent.glob('.ascii-apps-*')), [])

    def test_concurrent_creator_during_publication_is_never_overwritten(self):
        original_link = os.link
        competing = json.dumps([self.record()]).encode()

        def concurrent_link(source, destination):
            self.path.write_bytes(competing)
            return original_link(source, destination)

        with mock.patch('desktop.apps.catalog.os.link', side_effect=concurrent_link):
            with self.assertRaisesRegex(ValueError, 'created outside'):
                self.catalog.add('New', 'new')
        self.assertEqual(self.path.read_bytes(), competing)
        self.assertEqual(self.catalog.entries, [])
        self.assertEqual(list(self.path.parent.glob('.ascii-apps-*')), [])

    def test_external_edit_during_temporary_write_is_detected_before_replace(self):
        saved = self.catalog.add('Saved', 'saved')
        original_fsync = os.fsync
        competing = json.dumps([self.record()]).encode()

        def concurrent_edit(descriptor):
            self.path.write_bytes(competing)
            return original_fsync(descriptor)

        with mock.patch('desktop.apps.catalog.os.fsync', side_effect=concurrent_edit):
            with self.assertRaisesRegex(ValueError, 'changed outside'):
                self.catalog.remove(saved.id)
        self.assertEqual(self.path.read_bytes(), competing)
        self.assertEqual(self.catalog.entries, [saved])
        self.assertEqual(list(self.path.parent.glob('.ascii-apps-*')), [])

    def test_symlink_catalog_is_refused_without_altering_target(self):
        target = self.root / 'valuable.json'
        target.write_text('valuable data')
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.catalog.add('App', 'app')
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(), 'valuable data')

    def test_removing_unknown_id_keeps_existing_catalog(self):
        saved = self.catalog.add('Saved', 'saved')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'no longer'):
            self.catalog.remove('absent')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.catalog.entries, [saved])

    def test_prepare_validates_launcher_without_creating_files_or_adding_entries(self):
        self.catalog.load()
        entries = self.catalog.entries
        prepared = self.catalog.prepare_add('Downloaded tool', './tool "literal argument"',
                                            'A tool I downloaded')
        self.assertEqual(prepared.command, ('./tool', 'literal argument'))
        self.assertEqual(self.catalog.entries, [])
        self.assertIs(self.catalog.entries, entries)
        self.assertFalse(self.path.parent.exists())

    def test_prepare_leaves_existing_file_and_entries_unchanged_until_commit(self):
        saved = self.catalog.add('Saved', 'saved')
        original = self.path.read_bytes()
        entries = self.catalog.entries
        prepared = self.catalog.prepare_add('New tool', 'new-tool --option')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.catalog.entries, [saved])
        self.assertIs(self.catalog.entries, entries)
        self.assertEqual(self.catalog.commit_add(prepared), prepared)
        self.assertEqual(AppCatalog(self.path).load(), [saved, prepared])

    def test_invalid_launch_inputs_cannot_be_prepared(self):
        cases = [(' ', 'app', ''), ('App', '"" argument', ''),
                 ('App', 'app "unfinished', ''), ('App', 'app', 'bad\x00description')]
        for name, command, description in cases:
            with self.subTest(command=command, name=name), self.assertRaises(ValueError):
                self.catalog.prepare_add(name, command, description)
        self.assertEqual(self.catalog.entries, [])
        self.assertFalse(self.path.exists())

    def test_commit_revalidates_application_fields_and_does_not_write_invalid_records(self):
        invalid = [None, {'name': 'App'}, Application('', 'App', ('app',)),
                   Application('1', ' ', ('app',)), Application('1', 'App', ()),
                   Application('1', 'App', None), Application('1', 'App', ('app', '\n')),
                   Application('1', 'App', ('app',), 'bad\x00description')]
        for entry in invalid:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.catalog.commit_add(entry)
        self.assertEqual(self.catalog.entries, [])
        self.assertFalse(self.path.exists())

    def test_commit_refuses_application_id_collision_without_changing_data(self):
        saved = self.catalog.add('Saved', 'saved')
        original = self.path.read_bytes()
        colliding = Application(saved.id, 'Replacement', ('replacement',))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.catalog.commit_add(colliding)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.catalog.entries, [saved])

    def test_commit_refuses_external_changes_after_preparation(self):
        prepared = self.catalog.prepare_add('Prepared', 'prepared')
        competing = AppCatalog(self.path).add('Competing', 'competing')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.commit_add(prepared)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(AppCatalog(self.path).load(), [competing])
        self.assertEqual(self.catalog.entries, [])

    def test_preparation_refuses_stale_catalog_before_installation_can_begin(self):
        self.catalog.add('Saved', 'saved')
        AppCatalog(self.path).add('Competing', 'competing')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.catalog.prepare_add('New tool', 'new-tool')
        self.assertEqual(self.path.read_bytes(), original)

    def test_prepare_and_commit_check_entry_capacity_before_writing(self):
        self.write_records([self.record(str(index)) for index in range(MAX_APPS)])
        self.catalog.load()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'at most'):
            self.catalog.prepare_add('New', 'new')
        with self.assertRaisesRegex(ValueError, 'at most'):
            self.catalog.commit_add(Application('new-id', 'New', ('new',)))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(self.catalog.entries), MAX_APPS)

    def test_prepare_and_commit_check_serialized_size_before_writing(self):
        self.write_records([self.record()])
        self.catalog.load()
        original = self.path.read_bytes()
        with mock.patch('desktop.apps.catalog.MAX_FILE_BYTES', len(original) + 30):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                self.catalog.prepare_add('New', 'new')
            with self.assertRaisesRegex(ValueError, 'size limit'):
                self.catalog.commit_add(Application('new-id', 'New', ('new',)))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(self.catalog.entries), 1)

    def test_install_command_preserves_bash_pipeline_and_quotes_for_review(self):
        command = 'curl -fsS "https://example.invalid/app installer.sh" | sh'
        self.assertEqual(validate_install_command('  ' + command + '  '), command)
        self.assertEqual(validate_install_command('x' * MAX_COMMAND_CHARS), 'x' * MAX_COMMAND_CHARS)
        self.assertFalse(self.path.exists())

    def test_install_command_rejects_empty_multiline_controls_and_oversize_input(self):
        for command in [None, '', '  ', 'curl URL\nsh installer', 'curl URL\r',
                        'curl URL\x00', 'curl\tURL', 'x' * (MAX_COMMAND_CHARS + 1)]:
            with self.subTest(command=str(command)[:50]), self.assertRaises(ValueError):
                validate_install_command(command)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
