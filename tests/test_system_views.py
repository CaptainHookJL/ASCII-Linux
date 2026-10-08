"""Snapshot changes must preserve identity, readable details and scroll recovery."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from desktop.apps.process_manager import Process
from desktop.core.desktop import Desktop
from desktop.core.system_views import SystemApps


def desktop_for_details(page):
    desktop = Desktop.__new__(Desktop)
    desktop.screen = SimpleNamespace(getmaxyx=lambda: (16, 60))
    desktop.ascii_only = False
    desktop.page = page
    desktop.lines = []
    desktop.offset = 0
    desktop.message = ''
    desktop.system_apps = SystemApps(desktop)
    return desktop


class SystemViewTests(unittest.TestCase):
    def test_details_refresh_statistics_without_accepting_reused_pid(self):
        desktop = desktop_for_details('process_details')
        apps = desktop.system_apps
        initial = Process(321, 'user', 1, 2, 'S', 'old command', 10)
        updated = Process(321, 'user', 60, 12, 'R', 'new command', 10)
        replacement = Process(321, 'other', 0, 0, 'S', 'different process', 20)
        apps.process_detail = initial
        apps.process_source = Mock()
        apps.process_source.inspect.side_effect = lambda entry: [f'{entry.cpu_percent}% {entry.command}']
        apps._apply_processes([updated])
        self.assertEqual(apps.process_detail, updated)
        self.assertEqual(desktop.lines, ['60% new command'])
        apps._apply_processes([replacement])
        self.assertEqual(apps.process_detail, updated)
        apps.process_source.inspect.assert_called_with(updated)

    def test_termination_keeps_capture_even_if_dialog_refreshes_selection(self):
        desktop = desktop_for_details('process_details')
        apps = desktop.system_apps
        captured = Process(321, 'user', 1, 2, 'S', 'old command', 10)
        replacement = Process(321, 'other', 0, 0, 'S', 'different process', 20)
        apps.process_detail = captured
        apps.process_source = Mock()
        apps.process_source.inspect.return_value = ['Old identity']

        def confirm(_):
            apps._apply_processes([replacement])
            return True

        desktop.confirm = confirm
        apps.terminate(captured)
        # The backend validates this captured start time and refuses a reused PID.
        apps.process_source.terminate.assert_called_once_with(captured)

    def test_removed_interface_resets_scroll_and_refresh_error_remains_visible(self):
        desktop = desktop_for_details('network_details')
        apps = desktop.system_apps
        apps.network_detail = 'gone0'
        desktop.offset = 12
        apps._apply_network(((), {}, ''))
        self.assertEqual(desktop.offset, 0)
        self.assertEqual(desktop.view_lines(), ['Interface is no longer present.'])
        apps.network_poll.last_error = OSError('read failed')
        self.assertIn('previous snapshot', apps.detail_warning(desktop.page))
        self.assertIn('read failed', apps.detail_warning(desktop.page))

    def test_long_address_lists_wrap_without_losing_values(self):
        desktop = desktop_for_details('network_details')
        values = [f'2001:db8:1234:5678:abcd:abcd:abcd:{i:04x}/64' for i in range(10)]
        original = 'IPv6: ' + ', '.join(values)
        desktop.lines = [original]
        wrapped = desktop.view_lines()
        self.assertEqual(''.join(wrapped), original)
        self.assertTrue(all(desktop.width(line) <= 54 for line in wrapped))
        self.assertGreater(len(wrapped), 1)


if __name__ == '__main__':
    unittest.main()
