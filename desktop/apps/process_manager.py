"""Process snapshots and identity-checked SIGTERM, using Linux procfs only."""
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import pwd
import signal


@dataclass(frozen=True)
class Process:
    pid: int
    user: str
    cpu_percent: float
    memory_percent: float
    state: str
    command: str
    start_time: int
    uid: int = -1
    rss_bytes: int = 0


def _display_text(value):
    """Keep process-controlled command lines from injecting terminal controls."""
    return ''.join(character if character.isprintable() else
                   {'\n': '\\n', '\r': '\\r', '\t': '\\t'}.get(
                       character, f'\\x{ord(character):02x}') for character in value)


def _stat_fields(text, expected_pid):
    # comm is enclosed in parentheses and can itself contain spaces or ')'.
    opening, closing = text.find('('), text.rfind(')')
    if opening < 0 or closing <= opening:
        raise ValueError('Malformed process stat record')
    pid = int(text[:opening].strip())
    fields = text[closing + 1:].split()
    if pid != expected_pid or len(fields) < 22:
        raise ValueError('Incomplete or mismatched process stat record')
    return (text[opening + 1:closing], fields[0],
            int(fields[11]) + int(fields[12]), int(fields[19]),
            max(0, int(fields[21])))


class ProcessManager:
    """A sortable/filterable process list; CPU 100% means one occupied core.

    The first refresh establishes a CPU baseline and therefore reports 0%.
    Only the real /proc can send signals, and only through Linux pidfds. There
    is deliberately no os.kill fallback: it could signal a reused numeric PID.
    """
    SORT_KEYS = ('cpu', 'memory', 'pid', 'user', 'command')

    def __init__(self, proc_root='/proc'):
        self.proc_root = Path(proc_root)
        self.entries = []
        self.selected = 0
        self.query = ''
        self.sort_key = 'cpu'
        self._all_entries = []
        self._previous_ticks = {}
        self._previous_total = None
        self._page_size = os.sysconf('SC_PAGE_SIZE')
        self.refresh()

    @property
    def selected_entry(self):
        return self.entries[self.selected] if 0 <= self.selected < len(self.entries) else None

    def _cpu_snapshot(self):
        rows = (self.proc_root / 'stat').read_text().splitlines()
        aggregate = next(row.split()[1:] for row in rows if row.startswith('cpu '))
        # guest and guest_nice are already included in user/nice; exclude them.
        total = sum(int(value) for value in aggregate[:8])
        cores = sum(1 for row in rows if row.split() and
                    row.split()[0].startswith('cpu') and row.split()[0][3:].isdigit())
        return total, max(1, cores)

    def _memory_total(self):
        for row in (self.proc_root / 'meminfo').read_text().splitlines():
            if row.startswith('MemTotal:'):
                return int(row.split()[1]) * 1024
        return 0

    @staticmethod
    def _status(path):
        try:
            return dict(row.split(':', 1) for row in (path / 'status').read_text().splitlines()
                        if ':' in row)
        except OSError:
            return {}

    def _read_process(self, pid):
        path = self.proc_root / str(pid)
        command_name, state, ticks, start_time, rss_pages = _stat_fields(
            (path / 'stat').read_text(errors='replace'), pid)
        status = self._status(path)
        try:
            uid = int(status['Uid'].split()[0])
        except (KeyError, ValueError, IndexError):
            uid = path.stat().st_uid
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = str(uid)
        try:
            arguments = (path / 'cmdline').read_bytes().rstrip(b'\0')
            command = arguments.replace(b'\0', b' ').decode('utf-8', errors='replace')
        except OSError:
            command = ''
        # Kernel threads (and some zombies) have an empty cmdline.
        command = _display_text(command or command_name)
        # Avoid a mixed snapshot if the numeric PID changed owners between
        # reading stat and reading command/status metadata.
        _name, _state, _ticks, current_start, _rss = _stat_fields(
            (path / 'stat').read_text(errors='replace'), pid)
        if current_start != start_time:
            raise OSError(errno.ESTALE, 'Process identity changed while reading the snapshot.')
        return user, uid, state, ticks, start_time, rss_pages * self._page_size, command

    def _apply_view(self, previous=None):
        query = self.query.casefold()
        entries = [entry for entry in self._all_entries
                   if not query or query in f'{entry.pid} {entry.user} {entry.command}'.casefold()]
        if self.sort_key in ('cpu', 'memory'):
            attribute = 'cpu_percent' if self.sort_key == 'cpu' else 'memory_percent'
            entries.sort(key=lambda entry: (-getattr(entry, attribute), entry.pid))
        elif self.sort_key == 'pid':
            entries.sort(key=lambda entry: entry.pid)
        else:
            entries.sort(key=lambda entry: (getattr(entry, self.sort_key).casefold(), entry.pid))
        self.entries = entries
        self.selected = min(self.selected, max(0, len(entries) - 1))
        if previous is not None:
            for index, entry in enumerate(entries):
                if (entry.pid, entry.start_time) == (previous.pid, previous.start_time):
                    self.selected = index
                    break

    def refresh(self):
        previous = self.selected_entry
        # Failure to read global procfs data is a useful error, rather than an
        # empty process list that incorrectly looks like a healthy system.
        total, cores = self._cpu_snapshot()
        memory_total = self._memory_total()
        delta_total = total - self._previous_total if self._previous_total is not None else 0
        entries, current_ticks = [], {}
        for path in self.proc_root.iterdir():
            if not path.name.isascii() or not path.name.isdigit():
                continue
            pid = int(path.name)
            try:
                user, uid, state, ticks, started, rss, command = self._read_process(pid)
            except (OSError, ValueError, IndexError):
                # Processes can exit or become inaccessible during any read.
                continue
            identity = (pid, started)
            old_ticks = self._previous_ticks.get(identity)
            delta_ticks = ticks - old_ticks if old_ticks is not None else 0
            cpu = 100.0 * cores * max(0, delta_ticks) / delta_total if delta_total > 0 else 0.0
            memory = 100.0 * rss / memory_total if memory_total > 0 else 0.0
            entries.append(Process(pid, user, cpu, memory, state, command, started, uid, rss))
            current_ticks[identity] = ticks
        self._all_entries = entries
        self._previous_ticks = current_ticks
        self._previous_total = total
        self._apply_view(previous)

    def set_query(self, query):
        previous = self.selected_entry
        self.query = str(query)
        self._apply_view(previous)

    def set_sort(self, key):
        if key not in self.SORT_KEYS:
            raise ValueError('Sort by cpu, memory, pid, user or command.')
        previous = self.selected_entry
        self.sort_key = key
        self._apply_view(previous)

    def move(self, delta):
        self.selected = max(0, min(self.selected + int(delta), len(self.entries) - 1))

    def _selection(self, entry):
        selected = self.selected_entry if entry is None else entry
        if selected is None:
            raise ValueError('Select a process first.')
        if not isinstance(selected, Process):
            raise ValueError('Select a process snapshot first.')
        return selected

    def _check_identity(self, entry):
        try:
            _name, _state, _ticks, started, _rss = _stat_fields(
                (self.proc_root / str(entry.pid) / 'stat').read_text(errors='replace'), entry.pid)
        except FileNotFoundError as error:
            raise ProcessLookupError(errno.ESRCH, 'Process has exited; refresh the list.') from error
        if started != entry.start_time:
            raise OSError(errno.ESTALE, 'PID belongs to a different process; refresh the list.')

    def inspect(self, entry=None):
        entry = self._selection(entry)
        self._check_identity(entry)
        path = self.proc_root / str(entry.pid)
        lines = [f'PID: {entry.pid}', f'User: {entry.user} (UID {entry.uid})',
                 f'State: {entry.state}', f'CPU: {entry.cpu_percent:.1f}% (100% = one core)',
                 f'Memory: {entry.memory_percent:.1f}% ({entry.rss_bytes / 1048576:.1f} MiB resident)',
                 f'Start time: {entry.start_time} clock ticks after boot',
                 f'Command: {entry.command}']
        status = self._status(path)
        for key, label in (('PPid', 'Parent PID'), ('Threads', 'Threads')):
            if key in status:
                lines.append(f'{label}: {_display_text(status[key].strip())}')
        for name, label in (('exe', 'Executable'), ('cwd', 'Working directory')):
            try:
                value = _display_text(os.readlink(path / name))
            except OSError:
                value = 'unavailable (permissions or process exited)'
            lines.append(f'{label}: {value}')
        self._check_identity(entry)
        return lines

    def terminate(self, entry=None):
        """Send SIGTERM to the captured process identity, never to a PID group."""
        entry = self._selection(entry)
        if entry.pid <= 1:
            raise ValueError('PID 1 and nonpositive PIDs cannot be terminated.')
        if entry.pid == os.getpid():
            raise ValueError('The running desktop cannot terminate itself.')
        if self.proc_root != Path('/proc') or self.proc_root.resolve() != Path('/proc'):
            raise ValueError('Signals are only available for the real /proc process list.')
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise OSError(errno.ENOTSUP, 'Safe termination requires Linux pidfd support; use Bash instead.')
        try:
            descriptor = os.pidfd_open(entry.pid, 0)
        except OSError as error:
            if error.errno in (errno.ENOSYS, errno.EINVAL):
                raise OSError(errno.ENOTSUP, 'The kernel cannot safely terminate by identity; use Bash instead.') from error
            raise
        try:
            # Opening the pidfd before validation means an exit/PID reuse after
            # the check can never redirect the signal to a replacement process.
            self._check_identity(entry)
            signal.pidfd_send_signal(descriptor, signal.SIGTERM, None, 0)
        finally:
            os.close(descriptor)
