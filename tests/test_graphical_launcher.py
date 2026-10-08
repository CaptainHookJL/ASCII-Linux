"""Native launch behavior and responsive desktop workflows."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from desktop.apps.catalog import Application
from desktop.apps.launcher import GraphicalLauncher
from desktop.core.desktop import Desktop
from test_workflows import Terminal


class GraphicalLauncherTests(unittest.TestCase):
    def test_no_display_refuses_launch_without_spawning(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch('desktop.apps.launcher.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'No graphical display'):
                GraphicalLauncher().launch(Application('1', 'Browser', ('browser',)))
            spawn.assert_not_called()

    def test_native_child_inherits_display_and_runs_without_a_shell_or_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / 'result.json'
            payload = ('import json,os,sys,time\nfrom pathlib import Path\n'
                       'print("GUI_OUTPUT", flush=True)\n'
                       'Path(sys.argv[1]).write_text(json.dumps([os.getcwd(), '
                       'os.environ["DISPLAY"], os.environ["DBUS_SESSION_BUS_ADDRESS"], '
                       'sys.argv[2:], sys.stdin.read()]))\n'
                       'time.sleep(30)\n')
            launcher = GraphicalLauncher()
            with mock.patch.dict(os.environ, HOME=directory, DISPLAY=':99',
                                 DBUS_SESSION_BUS_ADDRESS='unix:path=/tmp/test-bus'):
                app = Application('1', 'Browser', (sys.executable, '-c', payload,
                                  str(result), '$(touch PWNED)', ';'), launch_mode='graphical')
                launcher.launch(app)
            child = launcher.children[0][1]
            try:
                deadline = time.monotonic() + 5
                while not result.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(json.loads(result.read_text()),
                                 [directory, ':99', 'unix:path=/tmp/test-bus',
                                  ['$(touch PWNED)', ';'], ''])
                self.assertEqual(launcher.poll(), [])
                self.assertFalse((root / 'PWNED').exists())
                child.terminate()
                child.wait(timeout=5)
                self.assertEqual(launcher.poll(), [(app, child.returncode)])
                self.assertEqual(launcher.poll(), [])
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)

    def test_terminal_mode_keeps_foreground_launch_behavior(self):
        desktop = Desktop.__new__(Desktop)
        app = Application('1', 'Editor', ('nano',))
        desktop.apps = mock.Mock(selected_entry=app)
        desktop.external = mock.Mock()
        desktop.graphical_launcher = mock.Mock()
        desktop.launch_app()
        desktop.external.assert_called_once_with(app.command, cwd=Path.home())
        desktop.graphical_launcher.launch.assert_not_called()

    def test_mode_prompt_uses_display_default_and_rejects_invalid_values(self):
        desktop = Desktop.__new__(Desktop)
        desktop.prompt = mock.Mock(return_value='g')
        with mock.patch.dict(os.environ, DISPLAY=':99'):
            self.assertEqual(desktop.app_launch_mode(), 'graphical')
        self.assertEqual(desktop.prompt.call_args.args[1], 'g')
        desktop.prompt.return_value = 'bogus'
        with self.assertRaisesRegex(ValueError, 'Choose g'):
            desktop.app_launch_mode('terminal')


class GraphicalWorkflowTests(unittest.TestCase):
    def test_default_cli_renders_only_ascii(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(Path(directory), ascii_only=None)
            try:
                terminal.wait('your console is your desktop')
                terminal.wait('F9 Editor')
                self.assertTrue(terminal.output.isascii())
            finally:
                terminal.close()

    def test_change_legacy_launcher_then_use_editor_while_native_child_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / '.local/share/ascii-linux/apps.json'
            catalog.parent.mkdir(parents=True)
            script = root / 'gui.py'
            script.write_text('from pathlib import Path\nimport time\n'
                              'print("DO_NOT_DRAW_GUI_OUTPUT", flush=True)\n'
                              'Path("opened").touch()\n'
                              'while not Path("close").exists(): time.sleep(.02)\n'
                              'raise SystemExit(42)\n')
            catalog.write_text(json.dumps([dict(id='legacy', name='Window app',
                                command=[sys.executable, str(script)], description='Native window')]))
            with mock.patch.dict(os.environ, DISPLAY=':99'):
                terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('Window app')
                terminal.send('a')
                terminal.wait('Terminal app')
                terminal.prompt('m', 'Launch mode:', 'g')
                terminal.wait('Window app: graphical')
                self.assertEqual(json.loads(catalog.read_text())[0]['launch_mode'], 'graphical')
                terminal.send('\r')
                terminal.wait('Opened: Window app')
                deadline = time.monotonic() + 5
                while not (root / 'opened').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'opened').exists())
                self.assertNotIn(b'DO_NOT_DRAW_GUI_OUTPUT', terminal.output)
                terminal.send(b'\x1b[20~')
                terminal.wait('Text editor: Untitled')
                terminal.send('Editor remains responsive')
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'responsive.txt')
                terminal.wait('Saved ' + str(root / 'responsive.txt'))
                self.assertEqual((root / 'responsive.txt').read_text(), 'Editor remains responsive')
                (root / 'close').touch()
                terminal.wait('Window app exited with status 42')
                terminal.send('\x11')
                terminal.wait('Window app')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                (root / 'close').touch()
                terminal.close()

    def test_new_graphical_launcher_can_be_registered_without_a_display(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict(os.environ):
                os.environ.pop('DISPLAY', None)
                os.environ.pop('WAYLAND_DISPLAY', None)
                terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('No user apps yet.')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                terminal.prompt('n', 'Add app: name', 'Brave')
                terminal.wait('command (quote paths with spaces)')
                terminal.send('brave-browser\r')
                terminal.wait('description (optional)')
                terminal.send('\r')
                terminal.wait('Launch mode:')
                terminal.send('\x15g\r')
                terminal.wait('App added: Brave')
                terminal.send('\r')
                terminal.wait('No graphical display.')
                self.assertIsNone(terminal.process.poll())
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
