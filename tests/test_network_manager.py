"""Read-only network inspection with real Linux data and isolated fixtures."""
import dataclasses
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from desktop.apps.network_manager import NetworkManager


class NetworkManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sys_root = self.root / 'sys' / 'class' / 'net'
        self.proc_root = self.root / 'proc'
        self.sys_root.mkdir(parents=True)
        (self.proc_root / 'net').mkdir(parents=True)
        self.resolv_path = self.root / 'resolv.conf'
        self.resolv_path.write_text(
            '# configured resolvers\nnameserver 192.0.2.53\nnameserver 2001:db8::53\n'
        )
        self.interface('eth0', rx=1000, tx=2000)
        self.interface('lo', state='unknown', mac='00:00:00:00:00:00', rx=50, tx=50)
        self.addresses = [
            {'ifname': 'eth0', 'operstate': 'UP', 'link_type': 'ether',
             'address': '02:00:00:00:00:01', 'addr_info': [
                 {'family': 'inet', 'local': '192.0.2.10', 'prefixlen': 24},
                 {'family': 'inet6', 'local': '2001:db8::10', 'prefixlen': 64},
                 {'family': 'inet6', 'local': 'fe80::10', 'prefixlen': 64},
             ]},
            {'ifname': 'lo', 'operstate': 'UNKNOWN', 'link_type': 'loopback',
             'address': '00:00:00:00:00:00', 'addr_info': [
                 {'family': 'inet', 'local': '127.0.0.1', 'prefixlen': 8},
                 {'family': 'inet6', 'local': '::1', 'prefixlen': 128},
             ]},
        ]
        self.routes4 = [{'dst': 'default', 'gateway': '192.0.2.1', 'dev': 'eth0'}]
        self.routes6 = [{'dst': 'default', 'gateway': 'fe80::1', 'dev': 'eth0'}]
        self.now = 100.0

    def interface(self, name, state='up', mac='02:00:00:00:00:01', rx=0, tx=0):
        directory = self.sys_root / name
        (directory / 'statistics').mkdir(parents=True, exist_ok=True)
        (directory / 'operstate').write_text(state + '\n')
        (directory / 'address').write_text(mac + '\n')
        (directory / 'type').write_text('772\n' if name == 'lo' else '1\n')
        (directory / 'statistics' / 'rx_bytes').write_text(str(rx) + '\n')
        (directory / 'statistics' / 'tx_bytes').write_text(str(tx) + '\n')

    def command(self, args, **kwargs):
        self.assertIsInstance(args, list)
        self.assertFalse(kwargs.get('shell', False))
        self.assertEqual(kwargs.get('timeout'), 1)
        if args == ['ip', '-j', 'address', 'show']:
            payload = self.addresses
        elif args == ['ip', '-j', '-4', 'route', 'show', 'default']:
            payload = self.routes4
        elif args == ['ip', '-j', '-6', 'route', 'show', 'default']:
            payload = self.routes6
        else:
            self.fail(f'Unexpected network command: {args!r}')
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), '')

    def make_manager(self, command=None):
        runner = mock.patch('desktop.apps.network_manager.subprocess.run',
                            side_effect=command or self.command)
        timer = mock.patch('desktop.apps.network_manager.time.monotonic',
                           side_effect=lambda: self.now)
        runner.start()
        timer.start()
        self.addCleanup(runner.stop)
        self.addCleanup(timer.stop)
        return NetworkManager(sys_root=self.sys_root, proc_root=self.proc_root,
                              resolv_path=self.resolv_path)

    def find(self, manager, name):
        return next(entry for entry in manager.entries if entry.name == name)

    def test_addresses_gateways_dns_mac_and_immutable_entries(self):
        manager = self.make_manager()
        eth0 = self.find(manager, 'eth0')
        self.assertEqual(eth0.ipv4, ('192.0.2.10/24',))
        self.assertEqual(set(eth0.ipv6), {'2001:db8::10/64', 'fe80::10/64'})
        self.assertEqual(eth0.mac, '02:00:00:00:00:01')
        self.assertIn('192.0.2.1', eth0.gateways)
        self.assertIn('fe80::1', eth0.gateways)
        self.assertEqual((eth0.rx_bytes, eth0.tx_bytes), (1000, 2000))
        self.assertEqual((eth0.rx_rate, eth0.tx_rate), (0, 0))
        self.assertEqual(manager.warning, '')
        with self.assertRaises(dataclasses.FrozenInstanceError):
            eth0.name = 'changed'
        text = '\n'.join(manager.details(eth0))
        for value in ('192.0.2.10/24', '2001:db8::10/64', '02:00:00:00:00:01',
                      '192.0.2.1', 'fe80::1', '192.0.2.53', '2001:db8::53'):
            self.assertIn(value, text)

    def test_selection_survives_reordered_ip_output_and_interface_removal(self):
        manager = self.make_manager()
        manager.selected = manager.entries.index(self.find(manager, 'lo'))
        self.addresses.reverse()
        self.interface('aaa0')
        self.addresses.append({'ifname': 'aaa0', 'addr_info': []})
        self.now += 1
        manager.refresh()
        self.assertEqual(manager.selected_entry.name, 'lo')
        shutil.rmtree(self.sys_root / 'lo')
        self.addresses[:] = [item for item in self.addresses if item['ifname'] != 'lo']
        self.now += 1
        manager.refresh()
        self.assertIsNotNone(manager.selected_entry)
        self.assertLess(manager.selected, len(manager.entries))
        manager.move(-1000)
        self.assertGreaterEqual(manager.selected, 0)
        manager.move(1000)
        self.assertLess(manager.selected, len(manager.entries))

    def test_traffic_rates_use_elapsed_time_and_counter_reset_is_zero(self):
        manager = self.make_manager()
        self.interface('eth0', rx=1600, tx=2600)
        self.now += 2
        manager.refresh()
        entry = self.find(manager, 'eth0')
        self.assertEqual((entry.rx_rate, entry.tx_rate), (300, 300))
        self.interface('eth0', rx=10, tx=20)
        self.now += 1
        manager.refresh()
        entry = self.find(manager, 'eth0')
        self.assertEqual((entry.rx_rate, entry.tx_rate), (0, 0))
        self.interface('eth0', rx=110, tx=120)
        self.now += 2
        manager.refresh()
        entry = self.find(manager, 'eth0')
        self.assertEqual((entry.rx_rate, entry.tx_rate), (50, 50))

    def test_new_interface_starts_with_zero_rate_and_zero_elapsed_is_safe(self):
        manager = self.make_manager()
        self.interface('wlan0', rx=900000, tx=800000)
        (self.sys_root / 'wlan0' / 'wireless').mkdir()
        self.addresses.append({'ifname': 'wlan0', 'operstate': 'UP', 'addr_info': []})
        self.now += 1
        manager.refresh()
        entry = self.find(manager, 'wlan0')
        self.assertEqual((entry.rx_rate, entry.tx_rate), (0, 0))
        self.assertEqual(entry.kind, 'Wi-Fi')
        self.interface('wlan0', rx=900100, tx=800100)
        manager.refresh()
        entry = self.find(manager, 'wlan0')
        self.assertGreaterEqual(entry.rx_rate, 0)
        self.assertGreaterEqual(entry.tx_rate, 0)

    def test_on_link_defaults_are_reported_without_inventing_gateway_addresses(self):
        self.routes4 = [{'dst': 'default', 'dev': 'eth0'}]
        self.routes6 = [{'dst': 'default', 'dev': 'eth0'}]
        manager = self.make_manager()
        self.assertEqual(set(self.find(manager, 'eth0').gateways),
                         {'on-link (IPv4)', 'on-link (IPv6)'})

    def test_missing_ip_uses_proc_routes_ipv6_and_traffic_with_honest_ipv4_warning(self):
        (self.proc_root / 'net' / 'dev').write_text(
            'Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n'
            ' eth0: 700 1 0 0 0 0 0 0 900 1 0 0 0 0 0 0\n'
        )
        shutil.rmtree(self.sys_root / 'eth0' / 'statistics')
        (self.proc_root / 'net' / 'route').write_text(
            'Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n'
            'eth0\t00000000\t010200C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n'
        )
        (self.proc_root / 'net' / 'if_inet6').write_text(
            '20010db8000000000000000000000010 02 40 00 80 eth0\n'
        )
        (self.proc_root / 'net' / 'ipv6_route').write_text(
            '00000000000000000000000000000000 00 '
            '00000000000000000000000000000000 00 '
            'fe800000000000000000000000000001 00000064 00000000 00000000 00000003 eth0\n'
        )
        manager = self.make_manager(lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError('ip')))
        entry = self.find(manager, 'eth0')
        self.assertEqual(entry.ipv4, ())
        self.assertIn('IPv4 lookup unavailable', manager.warning)
        self.assertIn('2001:db8::10/64', entry.ipv6)
        self.assertIn('192.0.2.1', entry.gateways)
        self.assertIn('fe80::1', entry.gateways)
        self.assertEqual((entry.rx_bytes, entry.tx_bytes), (700, 900))

    def test_invalid_json_timeout_and_failed_command_leave_interfaces_available(self):
        failures = (
            lambda args, **kwargs: subprocess.CompletedProcess(args, 0, '{bad json', ''),
            lambda args, **kwargs: subprocess.CompletedProcess(args, 0, '{"interfaces": []}', ''),
            lambda args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args, 1)),
            lambda args, **kwargs: subprocess.CompletedProcess(args, 1, '', 'operation failed'),
        )
        for command in failures:
            with self.subTest(command=command):
                manager = self.make_manager(command)
                self.assertEqual({entry.name for entry in manager.entries}, {'eth0', 'lo'})
                self.assertTrue(manager.warning)
                self.assertTrue(manager.details(self.find(manager, 'eth0')))

    def test_malformed_address_rows_preserve_good_data_and_warn_instead_of_hiding_failures(self):
        self.addresses[0]['addr_info'] = [
            {'family': 'inet', 'local': '192.0.2.10', 'prefixlen': -1},
            {'family': 'inet', 'local': 'not an IP address', 'prefixlen': 24},
            {'family': 'inet', 'local': '192.0.2.11', 'prefixlen': 24},
            {'family': 'inet6', 'local': '2001:db8::10', 'prefixlen': 129},
        ]
        manager = self.make_manager()
        entry = self.find(manager, 'eth0')
        self.assertEqual(entry.ipv4, ('192.0.2.11/24',))
        self.assertEqual(entry.ipv6, ())
        self.assertIn('IPv4 lookup unavailable', manager.warning)
        self.assertIn('IPv6 lookup unavailable', manager.warning)
        self.addresses[0]['addr_info'] = {'invalid': 'not a list'}
        self.now += 1
        manager.refresh()
        entry = self.find(manager, 'eth0')
        self.assertEqual(entry.ipv4, ())
        self.assertIn('IPv4: Lookup unavailable', '\n'.join(manager.details(entry)))

    def test_missing_resolver_is_distinct_from_no_configured_nameservers(self):
        self.resolv_path.unlink()
        manager = self.make_manager()
        self.assertIn('DNS resolver configuration unavailable', manager.warning)
        self.assertIn('DNS resolvers: Lookup unavailable', '\n'.join(manager.details()))
        self.resolv_path.write_text('# no resolver configured\n')
        self.now += 1
        manager.refresh()
        self.assertNotIn('DNS resolver configuration unavailable', manager.warning)
        self.assertIn('DNS resolvers: None configured', '\n'.join(manager.details()))

    def test_multipath_default_route_shows_each_interface_gateway(self):
        self.routes4 = [{'dst': 'default', 'nexthops': [
            {'gateway': '192.0.2.1', 'dev': 'eth0', 'weight': 1},
            {'gateway': '127.0.0.2', 'dev': 'lo', 'weight': 1},
        ]}]
        manager = self.make_manager()
        self.assertIn('192.0.2.1', self.find(manager, 'eth0').gateways)
        self.assertIn('127.0.0.2', self.find(manager, 'lo').gateways)

    def test_interface_limit_with_different_sys_and_ip_names_does_not_crash(self):
        self.addresses = [
            {'ifname': 'aa0', 'addr_info': [
                {'family': 'inet', 'local': '192.0.2.20', 'prefixlen': 24},
            ]},
            {'ifname': 'zz0', 'addr_info': [
                {'family': 'inet', 'local': '192.0.2.21', 'prefixlen': 24},
            ]},
        ]
        with mock.patch('desktop.apps.network_manager._MAX_INTERFACES', 2):
            manager = self.make_manager()
            self.assertLessEqual(len(manager.entries), 2)
            self.assertTrue(manager.entries)

    def test_disconnected_and_empty_interfaces_refresh_without_crashing(self):
        self.interface('eth0', state='down')
        self.addresses[0]['operstate'] = 'DOWN'
        self.addresses[0]['addr_info'] = []
        self.routes4 = []
        self.routes6 = []
        manager = self.make_manager()
        entry = self.find(manager, 'eth0')
        self.assertEqual(entry.state.lower(), 'down')
        self.assertEqual(entry.ipv4, ())
        self.assertEqual(entry.ipv6, ())
        self.assertEqual(entry.gateways, ())
        shutil.rmtree(self.sys_root)
        self.sys_root.mkdir()
        self.addresses = []
        self.now += 1
        manager.refresh()
        self.assertEqual(manager.entries, [])
        self.assertIsNone(manager.selected_entry)
        manager.move(1)
        self.assertIsInstance(manager.details(), list)


class LiveNetworkInspectionTests(unittest.TestCase):
    @unittest.skipUnless(Path('/sys/class/net').is_dir(), 'Linux network interfaces required')
    def test_real_interface_inspection_is_read_only_and_has_sensible_counters(self):
        manager = NetworkManager()
        self.assertTrue(manager.entries)
        self.assertIsNotNone(manager.selected_entry)
        for entry in manager.entries:
            self.assertGreaterEqual(entry.rx_bytes, 0)
            self.assertGreaterEqual(entry.tx_bytes, 0)
            self.assertGreaterEqual(entry.rx_rate, 0)
            self.assertGreaterEqual(entry.tx_rate, 0)
            self.assertTrue(manager.details(entry))


if __name__ == '__main__':
    unittest.main()
