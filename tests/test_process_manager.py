"""Procfs snapshots, process identity checks and scoped child termination."""
from dataclasses import FrozenInstanceError, replace
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from desktop.apps.process_manager import Process, ProcessManager


class ProcessManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write_cpu(1000)
        (self.root / 'meminfo').write_text('MemTotal:       8192 kB\n')

    def write_cpu(self, total, cores=2, guest=0):
        # Guest CPU is deliberately separate; Linux already includes it in user.
        (self.root / 'stat').write_text(
            f'cpu  {total} 0 0 0 0 0 0 0 {guest} 0\n' +
            ''.join(f'cpu{core}  {total // cores} 0 0 0 0 0 0 0\n'
                    for core in range(cores)))

    def write_process(self, pid, command='worker', comm=None, ticks=10,
                      start=20, rss=256, uid=0, state='S'):
        path = self.root / str(pid)
        path.mkdir(exist_ok=True)
        fields = [state] + ['0'] * 21
        fields[11] = str(ticks)
        fields[12] = '0'
        fields[19] = str(start)
        fields[21] = str(rss)
        (path / 'stat').write_text(f'{pid} ({comm or command}) ' + ' '.join(fields) + '\n')
        (path / 'status').write_text(f'Name:\tworker\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n'
                                   'PPid:\t2\nThreads:\t3\n')
        (path / 'cmdline').write_bytes(command.encode().replace(b' ', b'\0') + b'\0'
                                     if command else b'')
        return path

    def test_parses_parentheses_in_comm_and_null_separated_arguments(self):
        self.write_process(10, command='tool --name hello', comm='worker (one) two)', state='R')
        manager = ProcessManager(self.root)
        entry = manager.selected_entry
        self.assertEqual((entry.pid, entry.state, entry.command, entry.start_time),
                         (10, 'R', 'tool --name hello', 20))
        self.assertEqual(entry.rss_bytes, 256 * os.sysconf('SC_PAGE_SIZE'))
        self.assertAlmostEqual(entry.memory_percent, entry.rss_bytes / (8192 * 1024) * 100)
        self.assertEqual(entry.cpu_percent, 0)
        with self.assertRaises(FrozenInstanceError):
            entry.pid = 11

    def test_empty_cmdline_falls_back_to_comm_and_escapes_terminal_controls(self):
        self.write_process(10, command='', comm='worker (one)\n\x1b[31m')
        manager = ProcessManager(self.root)
        self.assertEqual(manager.selected_entry.command, 'worker (one)\\n\\x1b[31m')
        self.write_process(10, command='tool\tfile\r\n\x1b[0m')
        manager.refresh()
        self.assertEqual(manager.selected_entry.command, 'tool\\tfile\\r\\n\\x1b[0m')

    def test_cpu_uses_interval_and_one_core_percent_without_double_counting_guest(self):
        self.write_process(10, ticks=1000)
        self.write_process(20, ticks=500)
        manager = ProcessManager(self.root)
        self.assertEqual([entry.cpu_percent for entry in manager.entries], [0.0, 0.0])
        self.write_cpu(1100, guest=100)
        self.write_process(10, ticks=1050)
        self.write_process(20, ticks=510)
        manager.refresh()
        self.assertEqual([(entry.pid, entry.cpu_percent) for entry in manager.entries],
                         [(10, 100.0), (20, 20.0)])
        self.write_cpu(1200, guest=100)
        self.write_process(10, ticks=1100)
        self.write_process(20, ticks=580)
        manager.refresh()
        self.assertEqual([(entry.pid, entry.cpu_percent) for entry in manager.entries],
                         [(20, 140.0), (10, 100.0)])

    def test_reused_pid_new_process_and_counter_reset_have_no_old_cpu_history(self):
        self.write_process(10, ticks=100, start=20)
        manager = ProcessManager(self.root)
        self.write_cpu(1100)
        self.write_process(10, ticks=500, start=21)
        self.write_process(20, ticks=5000)
        manager.refresh()
        self.assertEqual([entry.cpu_percent for entry in manager.entries], [0.0, 0.0])
        self.write_cpu(100)
        self.write_process(10, ticks=900, start=21)
        manager.refresh()
        self.assertEqual([entry.cpu_percent for entry in manager.entries], [0.0, 0.0])

    def test_filter_matches_casefolded_command_pid_and_user(self):
        self.write_process(10, command='Straße --file', uid=123456789)
        self.write_process(20, command='editor')
        with mock.patch('desktop.apps.process_manager.pwd.getpwuid', side_effect=KeyError):
            manager = ProcessManager(self.root)
        manager.set_query('STRASSE')
        self.assertEqual([entry.pid for entry in manager.entries], [10])
        manager.set_query('20')
        self.assertEqual([entry.pid for entry in manager.entries], [20])
        manager.set_query('123456789')
        self.assertEqual([entry.pid for entry in manager.entries], [10])
        self.assertEqual(manager.selected_entry.user, '123456789')
        manager.set_query('missing')
        self.assertIsNone(manager.selected_entry)
        manager.move(10)
        self.assertEqual(manager.selected, 0)
        with self.assertRaisesRegex(ValueError, 'Select'):
            manager.inspect()

    def test_sort_options_and_navigation_preserve_identity(self):
        self.write_process(30, command='alpha', uid=20, rss=10)
        self.write_process(10, command='charlie', uid=10, rss=100)
        self.write_process(20, command='beta', uid=30, rss=50)
        with mock.patch('desktop.apps.process_manager.pwd.getpwuid', side_effect=KeyError):
            manager = ProcessManager(self.root)
        manager.move(1)
        selected = manager.selected_entry
        for key, expected in (('pid', [10, 20, 30]), ('command', [30, 20, 10]),
                              ('user', [10, 30, 20]), ('memory', [10, 20, 30])):
            manager.set_sort(key)
            self.assertEqual([entry.pid for entry in manager.entries], expected)
            self.assertEqual(manager.selected_entry, selected)
        with self.assertRaisesRegex(ValueError, 'Sort'):
            manager.set_sort('invalid')
        self.assertEqual(manager.sort_key, 'memory')
        manager.move(100)
        self.assertEqual(manager.selected_entry.pid, 30)
        manager.move(-100)
        self.assertEqual(manager.selected_entry.pid, 10)

    def test_refresh_and_filter_preserve_selected_pid_when_possible(self):
        self.write_process(10, command='same-a', ticks=10)
        self.write_process(20, command='same-b', ticks=10)
        manager = ProcessManager(self.root)
        manager.move(1)
        self.write_cpu(1100)
        self.write_process(20, command='same-b', ticks=60)
        manager.refresh()
        self.assertEqual(manager.selected_entry.pid, 20)
        self.assertEqual(manager.selected, 0)
        manager.set_query('same')
        self.assertEqual(manager.selected_entry.pid, 20)
        manager.set_query('same-a')
        self.assertEqual(manager.selected_entry.pid, 10)
        manager.set_query('')
        self.assertEqual(manager.selected_entry.pid, 10)

    def test_malformed_inaccessible_and_disappearing_processes_are_skipped(self):
        self.write_process(10)
        missing = self.root / '20'
        missing.mkdir()
        malformed = self.write_process(30)
        (malformed / 'stat').write_text('not a valid process stat')
        self.write_process(40)
        (self.root / 'self').symlink_to('10', target_is_directory=True)
        real_read = Path.read_text

        def deny(path, *args, **kwargs):
            if path == self.root / '40' / 'stat':
                raise PermissionError(errno.EACCES, 'denied')
            return real_read(path, *args, **kwargs)

        with mock.patch('pathlib.Path.read_text', new=deny):
            manager = ProcessManager(self.root)
        self.assertEqual([entry.pid for entry in manager.entries], [10])
        (self.root / '10' / 'stat').unlink()
        manager.refresh()
        self.assertEqual([entry.pid for entry in manager.entries], [40])

    def test_missing_optional_uid_cmdline_and_negative_rss_are_supported(self):
        path = self.write_process(10, comm='fallback', rss=-20)
        (path / 'cmdline').unlink()
        (path / 'status').unlink()
        manager = ProcessManager(self.root)
        self.assertEqual(manager.selected_entry.command, 'fallback')
        self.assertEqual(manager.selected_entry.uid, path.stat().st_uid)
        self.assertEqual(manager.selected_entry.rss_bytes, 0)
        self.assertEqual(manager.selected_entry.memory_percent, 0)

    def test_missing_memtotal_uses_zero_and_global_procfs_failure_is_reported(self):
        self.write_process(10)
        (self.root / 'meminfo').write_text('MemFree: 100 kB\n')
        manager = ProcessManager(self.root)
        self.assertEqual(manager.selected_entry.memory_percent, 0)
        (self.root / 'stat').unlink()
        with self.assertRaises(FileNotFoundError):
            manager.refresh()

    def test_inspection_includes_snapshot_status_and_optional_paths(self):
        path = self.write_process(10, command='worker arg')
        (path / 'exe').symlink_to('/usr/bin/worker')
        (path / 'cwd').symlink_to('/home/user')
        manager = ProcessManager(self.root)
        lines = manager.inspect()
        for expected in ('PID: 10', 'Command: worker arg', 'Parent PID: 2', 'Threads: 3',
                         'Executable: /usr/bin/worker', 'Working directory: /home/user'):
            self.assertIn(expected, lines)
        (path / 'cwd').unlink()
        self.assertIn('Working directory: unavailable (permissions or process exited)', manager.inspect())

    def test_inspection_rejects_reused_and_disappeared_pid(self):
        path = self.write_process(10, start=20)
        manager = ProcessManager(self.root)
        entry = manager.selected_entry
        self.write_process(10, start=21)
        with self.assertRaises(OSError) as raised:
            manager.inspect(entry)
        self.assertEqual(raised.exception.errno, errno.ESTALE)
        (path / 'stat').unlink()
        with self.assertRaises(ProcessLookupError):
            manager.inspect(entry)

    def test_pid_reuse_during_snapshot_is_skipped(self):
        self.write_process(10, start=20)
        original_read = Path.read_bytes

        def replace_during_command_read(path):
            if path == self.root / '10' / 'cmdline':
                self.write_process(10, start=21, command='replacement')
            return original_read(path)

        with mock.patch('pathlib.Path.read_bytes', new=replace_during_command_read):
            manager = ProcessManager(self.root)
        self.assertEqual(manager.entries, [])

    def test_pid_reuse_during_inspection_is_reported(self):
        self.write_process(10, start=20)
        manager = ProcessManager(self.root)

        def replace_during_readlink(path):
            self.write_process(10, start=21)
            return '/replacement/path'

        with mock.patch('desktop.apps.process_manager.os.readlink',
                        side_effect=replace_during_readlink):
            with self.assertRaises(OSError) as raised:
                manager.inspect()
        self.assertEqual(raised.exception.errno, errno.ESTALE)

    def test_fixture_root_cannot_signal_host_pid(self):
        self.write_process(10000)
        manager = ProcessManager(self.root)
        with mock.patch('desktop.apps.process_manager.os.pidfd_open', create=True) as opener, \
                mock.patch('desktop.apps.process_manager.signal.pidfd_send_signal', create=True) as sender:
            with self.assertRaisesRegex(ValueError, 'real /proc'):
                manager.terminate()
            opener.assert_not_called()
            sender.assert_not_called()

    def test_termination_refuses_pid_one_self_empty_and_invalid_selection(self):
        self.write_process(1)
        self.write_process(os.getpid())
        manager = ProcessManager(self.root)
        for entry, message in ((manager.entries[0], 'PID 1'),
                               (next(entry for entry in manager.entries if entry.pid == os.getpid()), 'itself')):
            with self.assertRaisesRegex(ValueError, message):
                manager.terminate(entry)
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            manager.terminate(object())
        manager.set_query('missing')
        with self.assertRaisesRegex(ValueError, 'Select'):
            manager.terminate()


class RealProcessTerminationTests(unittest.TestCase):
    def test_sigterm_ends_only_the_explicitly_created_child(self):
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            self.skipTest('Python has no pidfd signaling API')
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])

        def cleanup():
            if child.poll() is None:
                # Popen retains this exact child, so cleanup cannot target an
                # arbitrary process from the system process list.
                child.terminate()
                child.wait(timeout=5)

        self.addCleanup(cleanup)
        manager = ProcessManager()
        entry = next(entry for entry in manager.entries if entry.pid == child.pid)
        with self.assertRaises(OSError) as raised:
            manager.terminate(replace(entry, start_time=entry.start_time + 1))
        self.assertEqual(raised.exception.errno, errno.ESTALE)
        self.assertIsNone(child.poll())
        manager.terminate(entry)
        self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)

    def test_missing_pidfd_support_refuses_numeric_pid_fallback(self):
        # No process is actually signaled: mocks verify both refusal and the
        # absence of any os.kill fallback against this harmless fake identity.
        manager = ProcessManager()
        entry = Process(1000000000, 'user', 0, 0, 'S', 'fake', 0)
        with mock.patch('desktop.apps.process_manager.os.pidfd_open',
                        side_effect=OSError(errno.ENOSYS, 'not supported')),\
                mock.patch('desktop.apps.process_manager.os.kill') as numeric_kill:
            with self.assertRaises(OSError) as raised:
                manager.terminate(entry)
            self.assertEqual(raised.exception.errno, errno.ENOTSUP)
            numeric_kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
