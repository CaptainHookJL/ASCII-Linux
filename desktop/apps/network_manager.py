"""Read-only Linux network snapshots, with no connection or credential changes."""
from dataclasses import dataclass
import errno
import ipaddress
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time


_MAX_READ = 4 * 1024 * 1024
_MAX_INTERFACES = 4096


def _read(path, limit=_MAX_READ):
    """Bound proc/sys/config reads; a missing or oversized file is unavailable."""
    try:
        with Path(path).open(encoding='utf-8', errors='replace') as stream:
            value = stream.read(limit + 1)
        return value if len(value) <= limit else None
    except (OSError, ValueError):
        return None


def _number(path):
    value = _read(path, 128)
    try:
        return max(0, int(value.strip())) if value is not None else None
    except ValueError:
        return None


def _unique(values):
    return tuple(dict.fromkeys(values))


def _interface_name(value):
    return (isinstance(value, str) and value not in ('', '.', '..')
            and '/' not in value and '\x00' not in value)


def _valid_address(value, version):
    try:
        parsed = ipaddress.ip_address(value)
        return str(parsed) if parsed.version == version else None
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Interface:
    name: str
    state: str
    mac: str
    ipv4: tuple[str, ...]
    ipv6: tuple[str, ...]
    rx_bytes: int
    tx_bytes: int
    rx_rate: float
    tx_rate: float
    kind: str
    gateways: tuple[str, ...] = ()


class NetworkManager:
    """Sample interfaces on refresh; navigation and details use the cached snapshot.

    ``ip -j`` supplies all assigned addresses and default gateways when available.
    Linux proc/ioctl fallbacks still support useful information without iproute2.
    Warnings explicitly distinguish an unavailable lookup from an empty result.
    Rates measure counter deltas between snapshots, not traffic since boot.
    """

    def __init__(self, sys_root='/sys/class/net', proc_root='/proc',
                 resolv_path='/etc/resolv.conf'):
        self.sys_root = Path(sys_root)
        self.proc_root = Path(proc_root)
        self.resolv_path = Path(resolv_path)
        self.entries = []
        self.selected = 0
        self.warning = ''
        self.status = ''
        self.dns = ()
        self._previous = {}
        self._addresses_available = {4: False, 6: False}
        self._routes_available = {4: False, 6: False}
        self._traffic_available = set()
        self._dns_available = False
        self.refresh()

    @property
    def selected_entry(self):
        return self.entries[self.selected] if 0 <= self.selected < len(self.entries) else None

    def move(self, delta):
        self.selected = max(0, min(self.selected + delta, len(self.entries) - 1))

    @staticmethod
    def _ip_json(arguments):
        try:
            result = subprocess.run(['ip', '-j', *arguments], capture_output=True,
                                    text=True, timeout=1, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode or len(result.stdout) > _MAX_READ:
            return None
        try:
            rows = json.loads(result.stdout)
        except (ValueError, TypeError):
            return None
        if not isinstance(rows, list) or len(rows) > _MAX_INTERFACES:
            return None
        return rows if all(isinstance(row, dict) for row in rows) else None

    def _proc_counters(self):
        contents = _read(self.proc_root / 'net/dev')
        counters = {}
        if contents is None:
            return counters
        for line in contents.splitlines():
            if ':' not in line:
                continue
            name, data = line.rsplit(':', 1)
            fields = data.split()
            if len(fields) < 16:
                continue
            try:
                name = name.strip()
                if _interface_name(name):
                    counters[name] = (max(0, int(fields[0])), max(0, int(fields[8])))
            except ValueError:
                continue
        return counters

    def _fallback_addresses(self, names):
        addresses = {name: {4: [], 6: []} for name in names}
        available = {4: False, 6: False}
        # if_inet6 is authoritative for assigned IPv6 addresses, including prefixes.
        contents = _read(self.proc_root / 'net/if_inet6')
        if contents is not None:
            available[6] = True
            for line in contents.splitlines():
                fields = line.split()
                if len(fields) != 6 or fields[5] not in addresses:
                    continue
                try:
                    address = ipaddress.IPv6Address(int(fields[0], 16))
                    prefix = int(fields[2], 16)
                    if 0 <= prefix <= 128:
                        addresses[fields[5]][6].append(f'{address}/{prefix}')
                except ValueError:
                    continue
        # SIOCGIFADDR exposes the primary IPv4 address only. Do not query the
        # host when reading fixtures or another mounted machine's sys tree.
        if self.sys_root == Path('/sys/class/net') and self.proc_root == Path('/proc'):
            try:
                import fcntl
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as descriptor:
                    available[4] = True
                    for name in names:
                        encoded = os.fsencode(name)
                        if len(encoded) > 15:
                            available[4] = False
                            continue
                        request = struct.pack('256s', encoded)
                        try:
                            address = fcntl.ioctl(descriptor.fileno(), 0x8915, request)[20:24]
                            mask = fcntl.ioctl(descriptor.fileno(), 0x891b, request)[20:24]
                            netmask = str(ipaddress.IPv4Address(mask))
                            cidr = ipaddress.IPv4Network(f'0.0.0.0/{netmask}').prefixlen
                            addresses[name][4].append(f'{ipaddress.IPv4Address(address)}/{cidr}')
                        except OSError as error:
                            if error.errno not in (errno.EADDRNOTAVAIL, errno.ENODEV):
                                available[4] = False
                        except ValueError:
                            available[4] = False
            except (ImportError, OSError):
                pass
        return addresses, available

    def _fallback_routes(self, version):
        contents = _read(self.proc_root / ('net/route' if version == 4 else 'net/ipv6_route'))
        gateways = {}
        if contents is None:
            return gateways, False
        for line in contents.splitlines():
            fields = line.split()
            try:
                if version == 4:
                    if len(fields) < 8 or fields[1] != '00000000' or fields[7] != '00000000':
                        continue
                    flags = int(fields[3], 16)
                    name = fields[0]
                    gateway = str(ipaddress.IPv4Address(int(fields[2], 16).to_bytes(4, 'little')))
                    zero = gateway == '0.0.0.0'
                else:
                    if len(fields) < 10 or int(fields[0], 16) != 0 or int(fields[1], 16) != 0:
                        continue
                    flags = int(fields[8], 16)
                    name = fields[9]
                    gateway = str(ipaddress.IPv6Address(int(fields[4], 16)))
                    zero = gateway == '::'
                if flags & 1 and not flags & 0x200:
                    gateways.setdefault(name, []).append(f'on-link (IPv{version})' if zero else gateway)
            except (ValueError, OverflowError):
                continue
        return gateways, True

    def refresh(self):
        selected_name = self.selected_entry.name if self.selected_entry else None
        warnings = []
        names = set()
        try:
            with os.scandir(self.sys_root) as directories:
                for index, directory in enumerate(directories):
                    if index >= _MAX_INTERFACES:
                        warnings.append('Interface list truncated.')
                        break
                    if _interface_name(directory.name):
                        names.add(directory.name)
        except OSError:
            pass
        counters = self._proc_counters()
        names.update(counters)
        address_rows = self._ip_json(['address', 'show'])
        metadata = {}
        if address_rows is not None:
            for row in address_rows:
                name = row.get('ifname')
                if _interface_name(name):
                    names.add(name)
                    metadata[name] = row
        if len(names) > _MAX_INTERFACES and 'Interface list truncated.' not in warnings:
            warnings.append('Interface list truncated.')
        names = sorted(names, key=lambda name: (name.casefold(), name))[:_MAX_INTERFACES]
        addresses = {name: {4: [], 6: []} for name in names}
        if address_rows is None:
            addresses, self._addresses_available = self._fallback_addresses(names)
            warnings.append('ip address lookup unavailable; using Linux fallback (primary IPv4 only).')
        else:
            self._addresses_available = {4: True, 6: True}
            for name, row in metadata.items():
                if name not in addresses:
                    continue
                info = row.get('addr_info', [])
                if not isinstance(info, list):
                    self._addresses_available = {4: False, 6: False}
                    continue
                for item in info:
                    if not isinstance(item, dict):
                        self._addresses_available = {4: False, 6: False}
                        continue
                    version = {'inet': 4, 'inet6': 6}.get(item.get('family'))
                    if version is None:
                        continue
                    value = _valid_address(item.get('local'), version)
                    prefix = item.get('prefixlen')
                    if value is not None and isinstance(prefix, int) and 0 <= prefix <= (32 if version == 4 else 128):
                        addresses[name][version].append(f'{value}/{prefix}')
                    else:
                        self._addresses_available[version] = False
        for version, available in self._addresses_available.items():
            if not available:
                warnings.append(f'IPv{version} lookup unavailable or incomplete.')

        gateways = {name: [] for name in names}
        for version in (4, 6):
            rows = self._ip_json([f'-{version}', 'route', 'show', 'default'])
            if rows is None:
                defaults, available = self._fallback_routes(version)
            else:
                defaults = {}
                available = True
                for row in rows:
                    if row.get('type', 'unicast') != 'unicast':
                        continue
                    links = row.get('nexthops', [row])
                    if not isinstance(links, list) or not links:
                        available = False
                        continue
                    for link in links:
                        if not isinstance(link, dict) or not _interface_name(link.get('dev')):
                            available = False
                            continue
                        name = link['dev']
                        gateway = link.get('gateway')
                        if gateway is None and 'via' not in link:
                            defaults.setdefault(name, []).append(f'on-link (IPv{version})')
                        else:
                            gateway_version = version
                            if 'via' in link:
                                via = link['via']
                                if not isinstance(via, dict):
                                    available = False
                                    continue
                                gateway = via.get('host')
                                gateway_version = {'inet': 4, 'inet6': 6}.get(via.get('family'), version)
                            address = _valid_address(gateway, gateway_version)
                            if address is not None:
                                defaults.setdefault(name, []).append(address)
                            else:
                                available = False
            self._routes_available[version] = available
            for name, values in defaults.items():
                if name in gateways:
                    gateways[name].extend(values)
            if not available:
                warnings.append(f'IPv{version} default route lookup unavailable or incomplete.')

        dns_contents = _read(self.resolv_path, 64 * 1024)
        self._dns_available = dns_contents is not None
        dns = []
        if dns_contents is not None:
            for line in dns_contents.splitlines():
                fields = line.split('#', 1)[0].split(';', 1)[0].split()
                if len(fields) >= 2 and fields[0] == 'nameserver':
                    value = _valid_address(fields[1], 4) or _valid_address(fields[1], 6)
                    if value is not None:
                        dns.append(value)
        else:
            warnings.append('DNS resolver configuration unavailable.')
        self.dns = _unique(dns)

        timestamp = time.monotonic()
        snapshots = []
        previous = {}
        self._traffic_available = set()
        for name in names:
            directory = self.sys_root / name
            row = metadata.get(name, {})
            state = _read(directory / 'operstate', 128)
            state = (state.strip() if state is not None else str(row.get('operstate', 'unknown'))).lower()
            mac = _read(directory / 'address', 128)
            mac = mac.strip() if mac is not None else str(row.get('address', 'unavailable'))
            rx = _number(directory / 'statistics/rx_bytes')
            tx = _number(directory / 'statistics/tx_bytes')
            if rx is None or tx is None:
                values = counters.get(name)
                if values is not None:
                    rx, tx = values
            rate_rx = rate_tx = 0.0
            if rx is not None and tx is not None:
                self._traffic_available.add(name)
                old = self._previous.get(name)
                if old is not None and timestamp > old[0]:
                    interval = timestamp - old[0]
                    rate_rx = max(0, rx - old[1]) / interval
                    rate_tx = max(0, tx - old[2]) / interval
                previous[name] = (timestamp, rx, tx)
            kind = 'Other'
            interface_type = _number(directory / 'type')
            if name == 'lo' or interface_type == 772 or row.get('link_type') == 'loopback':
                kind = 'Loopback'
            elif (directory / 'wireless').is_dir() or (directory / 'phy80211').exists():
                kind = 'Wi-Fi'
            elif interface_type == 1 or row.get('link_type') == 'ether':
                kind = 'Ethernet'
            snapshots.append(Interface(name, state or 'unknown', mac or 'unavailable',
                                       _unique(addresses[name][4]), _unique(addresses[name][6]),
                                       rx if rx is not None else 0, tx if tx is not None else 0,
                                       rate_rx, rate_tx, kind, _unique(gateways[name])))
        self._previous = previous
        self.entries = snapshots
        if selected_name in names:
            self.selected = names.index(selected_name)
        else:
            self.selected = min(self.selected, max(0, len(self.entries) - 1))
        if len(self._traffic_available) < len(self.entries):
            warnings.append('Some traffic counters are unavailable.')
        if not self.entries:
            warnings.append('No interfaces could be read.')
        self.warning = ' '.join(warnings)
        self.status = f'{len(self.entries)} interfaces'
        if self.warning:
            self.status += ' | ' + self.warning

    def details(self, entry=None):
        entry = entry or self.selected_entry
        if entry is None:
            return [self.warning or 'No interface selected.']
        lines = [f'Interface: {entry.name}', f'Type: {entry.kind}',
                 f'State: {entry.state}', f'MAC: {entry.mac}']
        for version, values in ((4, entry.ipv4), (6, entry.ipv6)):
            missing = 'None assigned' if self._addresses_available[version] else 'Lookup unavailable'
            lines.append(f'IPv{version}: ' + (', '.join(values) if values else missing))
        if entry.gateways:
            lines.append('Default gateways: ' + ', '.join(entry.gateways))
        else:
            available = all(self._routes_available.values())
            lines.append('Default gateways: ' + ('None' if available else 'Lookup unavailable'))
        lines.append('DNS resolvers: ' + (', '.join(self.dns) if self.dns else
                     ('None configured' if self._dns_available else 'Lookup unavailable')))
        if entry.name in self._traffic_available:
            lines.extend([f'Received: {entry.rx_bytes:,} bytes ({entry.rx_rate:,.0f} bytes/s)',
                          f'Sent: {entry.tx_bytes:,} bytes ({entry.tx_rate:,.0f} bytes/s)'])
        else:
            lines.append('Traffic counters: Lookup unavailable')
        lines.append('DNS reflects resolv.conf; it may point to a local resolver.')
        if self.warning:
            lines.append(self.warning)
        return lines
