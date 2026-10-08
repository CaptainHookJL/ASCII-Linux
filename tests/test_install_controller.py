"""Install-controller checks keep command execution and launcher commits ordered."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from desktop.apps.catalog import AppCatalog
from desktop.core.desktop import Desktop
from desktop.widgets.apps import AppsSection


class InstallControllerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = mock.patch.dict(os.environ, {
            'HOME': str(self.root), 'XDG_DATA_HOME': str(self.root / 'data')})
        environment.start()
        self.addCleanup(environment.stop)
        self.path = self.root / 'data/ascii-linux/apps.json'
        self.command = 'printf "%s" "$HOME" && printf done | cat'
        self.launch = '"~/bin/my tool" --label "Café Tool" "$HOME" ";"'

    def controller(self, *, launch=None, result=0, review=True):
        desktop = Desktop.__new__(Desktop)
        desktop.apps = AppsSection(AppCatalog())
        desktop.page, desktop.lines, desktop.offset = 'apps', [], 0
        desktop.message = ''
        desktop.prompt = mock.Mock(side_effect=[
            'Café Tool', self.command, self.launch if launch is None else launch,
            'A personal application'])
        desktop.review_install = mock.Mock(return_value=review)
        desktop.external = mock.Mock(return_value=result)
        return desktop

    def test_invalid_launcher_prevents_review_execution_and_registration(self):
        for launch in ['tool "unfinished', '""', 'tool\x00argument']:
            with self.subTest(launch=launch):
                desktop = self.controller(launch=launch)
                with self.assertRaises(ValueError):
                    desktop.install_app()
                desktop.review_install.assert_not_called()
                desktop.external.assert_not_called()
                self.assertEqual(desktop.apps.entries, [])
                self.assertFalse(self.path.exists())

    def test_invalid_catalog_prevents_command_and_keeps_existing_data(self):
        self.path.parent.mkdir(parents=True)
        original = b'not valid JSON; preserve this file'
        self.path.write_bytes(original)
        desktop = self.controller()
        self.assertTrue(desktop.apps.error)
        with self.assertRaises(ValueError):
            desktop.install_app()
        desktop.review_install.assert_not_called()
        desktop.external.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(desktop.apps.entries, [])

    def test_invalid_install_command_prevents_external_execution(self):
        for command in ['', '  ', 'echo hello\nrm file', 'echo\x00bad']:
            with self.subTest(command=command):
                desktop = self.controller()
                desktop.prompt = mock.Mock(side_effect=['Tool', command])
                with self.assertRaises(ValueError):
                    desktop.install_app()
                desktop.review_install.assert_not_called()
                desktop.external.assert_not_called()
                self.assertFalse(self.path.exists())

    def test_cancelled_review_does_not_execute_or_create_launcher(self):
        desktop = self.controller(review=False)
        desktop.install_app()
        desktop.review_install.assert_called_once()
        entry, reviewed_command = desktop.review_install.call_args.args
        self.assertEqual(entry.name, 'Café Tool')
        self.assertEqual(reviewed_command, self.command)
        desktop.external.assert_not_called()
        self.assertEqual(desktop.apps.entries, [])
        self.assertFalse(self.path.exists())
        self.assertEqual(desktop.message, 'Install cancelled')

    def test_failed_or_interrupted_install_does_not_register_launcher(self):
        for result in [1, 7, 127, None]:
            with self.subTest(result=result):
                desktop = self.controller(result=result)
                if result is None:
                    desktop.message = '/bin/bash interrupted'
                desktop.install_app()
                desktop.external.assert_called_once_with(
                    ['/bin/bash', '-o', 'pipefail', '-c', self.command], cwd=self.root)
                self.assertEqual(desktop.apps.entries, [])
                self.assertFalse(self.path.exists())
                self.assertIn('launcher not added', desktop.message)
                self.assertIn('interrupted' if result is None else f'exit {result}', desktop.message)

    def test_success_runs_exact_bash_command_then_persists_parsed_launcher(self):
        desktop = self.controller()
        desktop.install_app()
        desktop.external.assert_called_once_with(
            ['/bin/bash', '-o', 'pipefail', '-c', self.command], cwd=self.root)
        saved, = AppCatalog().load()
        self.assertEqual(saved.name, 'Café Tool')
        self.assertEqual(saved.command, (
            str(self.root / 'bin/my tool'), '--label', 'Café Tool', '$HOME', ';'))
        self.assertEqual(saved.description, 'A personal application')
        self.assertEqual(desktop.apps.selected_entry, saved)
        self.assertEqual(desktop.message, 'Installed and added: Café Tool')

    def test_catalog_change_during_success_is_preserved_and_reported(self):
        catalog = AppCatalog()
        catalog.add('Original app', 'original --flag')
        desktop = self.controller()
        changed = []

        def successful_install(*args, **kwargs):
            AppCatalog().add('External app', 'external --option')
            changed.append(self.path.read_bytes())
            return 0

        desktop.external.side_effect = successful_install
        desktop.install_app()
        desktop.external.assert_called_once()
        self.assertEqual(self.path.read_bytes(), changed[0])
        self.assertEqual([entry.name for entry in AppCatalog().load()],
                         ['Original app', 'External app'])
        self.assertEqual([entry.name for entry in desktop.apps.entries], ['Original app'])
        self.assertTrue(desktop.message.startswith('Install succeeded; launcher not saved:'))
        self.assertIn('changed', desktop.message)

    def test_external_keyboard_interrupt_restores_curses_and_reports_interruption(self):
        desktop = Desktop.__new__(Desktop)
        desktop.screen = mock.Mock()
        desktop.message = ''
        command = ['/bin/bash', '-o', 'pipefail', '-c', self.command]
        with mock.patch('desktop.core.desktop.curses.def_prog_mode') as save_mode, \
                mock.patch('desktop.core.desktop.curses.endwin') as endwin, \
                mock.patch('desktop.core.desktop.curses.reset_prog_mode') as restore_mode, \
                mock.patch('desktop.core.desktop.subprocess.run', side_effect=KeyboardInterrupt) as run:
            result = desktop.external(command, cwd=self.root)
        self.assertIsNone(result)
        self.assertEqual(desktop.message, '/bin/bash interrupted')
        save_mode.assert_called_once_with()
        endwin.assert_called_once_with()
        run.assert_called_once_with(command, check=False, cwd=self.root)
        restore_mode.assert_called_once_with()
        desktop.screen.timeout.assert_called_once_with(200)
        desktop.screen.clear.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
