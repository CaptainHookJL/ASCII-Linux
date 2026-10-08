"""Session routing and failure recovery without requiring an X server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / 'system/ascii-session'
XSESSION = ROOT / 'system/ascii-xsession'


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.bin = self.path / 'bin'
        self.bin.mkdir()
        self.log = self.path / 'commands'
        self.env = dict(os.environ, PATH=str(self.bin), HOME=str(self.path),
                        SESSION_TEST_LOG=str(self.log))
        for key in ['DISPLAY', 'WAYLAND_DISPLAY', 'ASCII_DBUS_SESSION']:
            self.env.pop(key, None)
        (self.bin / 'dirname').symlink_to('/usr/bin/dirname')
        self.command('tty', 'printf "/dev/tty1\\n"\n')
        self.command('python3', 'printf "python-cwd=%s\\n" "$PWD" >> "$SESSION_TEST_LOG"\n'
                     'printf "python-arg=%s\\n" "$@" >> "$SESSION_TEST_LOG"\n')

    def command(self, name, body):
        script = self.bin / name
        script.write_text('#!/bin/sh\n' + body)
        script.chmod(0o755)

    def run_session(self, *args):
        return subprocess.run([str(SESSION), *args], cwd=self.path,
                              env=self.env, capture_output=True, text=True, timeout=5)

    def install_graphical_stubs(self, startx_status=0):
        self.command('startx', 'printf "startx-arg=%s\\n" "$@" >> "$SESSION_TEST_LOG"\n'
                     f'exit {startx_status}\n')
        for name in ['xauth', 'openbox', 'xterm', 'dbus-run-session', 'xsetroot', 'xprop']:
            self.command(name, 'exit 0\n')

    def test_console_launch_finds_checkout_and_preserves_arguments(self):
        result = self.run_session('--console', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn(f'python-cwd={ROOT}\n', log)
        self.assertIn('python-arg=-m\npython-arg=desktop.main\npython-arg=--ascii\npython-arg=--check\n', log)

    def test_existing_display_runs_in_current_terminal(self):
        self.install_graphical_stubs()
        for key in ['DISPLAY', 'WAYLAND_DISPLAY']:
            with self.subTest(display=key):
                self.env[key] = ':42' if key == 'DISPLAY' else 'wayland-1'
                result = self.run_session('--check')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('startx-', self.log.read_text())
                self.env.pop(key)

    def test_dedicated_session_refuses_to_replace_existing_wm(self):
        self.env['DISPLAY'] = ':42'
        result = self.run_session('--graphical')
        self.assertEqual(result.returncode, 1)
        self.assertIn('already running', result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_graphical_dependency_recovers_to_console(self):
        result = self.run_session('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Missing graphical session tool: startx', result.stderr)
        self.assertIn('python-arg=--check', self.log.read_text())

    def test_dedicated_startup_keeps_x_transport_local(self):
        self.install_graphical_stubs()
        result = self.run_session('--graphical', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn(f'startx-arg={XSESSION}\n', log)
        self.assertIn('startx-arg=--check\nstartx-arg=--\nstartx-arg=-nolisten\nstartx-arg=tcp\n', log)
        self.assertNotIn('python-arg=', log)

    def test_remote_terminal_keeps_console_and_does_not_start_x(self):
        self.install_graphical_stubs()
        self.command('tty', 'printf "/dev/pts/2\\n"\n')
        result = self.run_session('--graphical', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('requires a local Linux console', result.stderr)
        self.assertNotIn('startx-', self.log.read_text())

    def test_failed_x_startup_recovers_to_console(self):
        self.install_graphical_stubs(startx_status=7)
        result = self.run_session('--graphical', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Graphical session failed (status 7)', result.stderr)
        self.assertIn('python-arg=--check', self.log.read_text())

    def test_failed_desktop_offers_recovery_shell(self):
        self.command('python3', 'exit 23\n')
        result = subprocess.run([str(SESSION), '--console'], cwd=self.path,
                                env=self.env, input='exit 0\n',
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ASCII desktop failed (status 23). Starting a recovery shell.', result.stderr)

    def test_xsession_requires_display(self):
        result = subprocess.run([str(XSESSION)], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('requires an X display', result.stderr)

    def test_window_manager_failure_does_not_leave_owned_process(self):
        self.env.update(DISPLAY=':42', ASCII_DBUS_SESSION='1')
        self.command('xsetroot', 'exit 0\n')
        self.command('openbox', 'exit 9\n')
        self.command('xprop', 'exit 1\n')
        self.command('sleep', 'exec /bin/sleep "$@"\n')
        self.command('xterm', 'printf "unexpected-xterm\\n" >> "$SESSION_TEST_LOG"\n')
        result = subprocess.run([str(XSESSION)], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertIn('stopped during startup', result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
