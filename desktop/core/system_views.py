"""Process/network views over immutable, asynchronously collected Linux snapshots."""
import curses

from desktop.apps.network_manager import NetworkManager
from desktop.apps.process_manager import ProcessManager
from desktop.utils.polling import SnapshotPoller
from desktop.widgets.table import Table


def rate(value):
    for unit in ('B/s', 'KiB/s', 'MiB/s', 'GiB/s'):
        if value < 1024 or unit == 'GiB/s':
            return f'{value:.0f}{unit}' if unit == 'B/s' else f'{value:.1f}{unit}'
        value /= 1024


class SystemApps:
    def __init__(self, desktop):
        self.desktop = desktop
        self.process_source = self.network_source = None
        self.processes = Table(
            identity=lambda entry: (entry.pid, entry.start_time),
            searchable=lambda entry: f'{entry.pid} {entry.user} {entry.state} {entry.command}',
            sorts={'cpu': (lambda entry: (entry.cpu_percent, -entry.pid), True),
                   'memory': (lambda entry: (entry.memory_percent, -entry.pid), True),
                   'pid': (lambda entry: entry.pid, False),
                   'user': (lambda entry: (entry.user, entry.pid), False),
                   'command': (lambda entry: (entry.command.casefold(), entry.pid), False)},
            sort_key='cpu')
        self.network = Table(identity=lambda entry: entry.name,
                             searchable=lambda entry: entry.name,
                             sorts={'name': (lambda entry: entry.name, False)}, sort_key='name')
        self.network_lines = {}
        self.network_warning = ''
        self.process_detail = None
        self.network_detail = None
        self.process_poll = SnapshotPoller(self._read_processes, self._apply_processes, 1.0)
        self.network_poll = SnapshotPoller(self._read_network, self._apply_network, 2.0)

    def _read_processes(self):
        if self.process_source is None:
            self.process_source = ProcessManager()
        else:
            self.process_source.refresh()
        return tuple(self.process_source.entries)

    def _read_network(self):
        if self.network_source is None:
            self.network_source = NetworkManager()
        else:
            self.network_source.refresh()
        entries = tuple(self.network_source.entries)
        lines = {entry.name: tuple(self.network_source.details(entry)) for entry in entries}
        return entries, lines, self.network_source.warning

    def _apply_processes(self, entries):
        self.processes.update(entries)
        if self.desktop.page == 'process_details':
            identity = (self.process_detail.pid, self.process_detail.start_time)
            for entry in entries:
                if (entry.pid, entry.start_time) == identity:
                    self.process_detail = entry
                    break
            self.refresh_process_details()

    def _apply_network(self, result):
        entries, lines, warning = result
        self.network.update(entries)
        self.network_lines = lines
        self.network_warning = warning
        if self.desktop.page == 'network_details':
            if self.network_detail in lines:
                self.set_details(lines[self.network_detail])
            else:
                self.desktop.offset = 0
                self.set_details(['Interface is no longer present.'])

    def tick(self):
        page = self.desktop.page
        self.process_poll.poll(page in ('processes', 'process_details'))
        self.network_poll.poll(page in ('network', 'network_details'))

    def opened(self, page):
        if page == 'processes':
            self.process_poll.request()
        elif page == 'network':
            self.network_poll.request()

    def set_details(self, lines):
        self.desktop.lines = list(lines)
        self.desktop.offset = min(self.desktop.offset, max(0, len(self.desktop.view_lines()) - 1))

    def detail_warning(self, page):
        poll = self.process_poll if page == 'process_details' else self.network_poll if page == 'network_details' else None
        return 'Refresh failed; showing previous snapshot: ' + str(poll.last_error) if poll and poll.last_error else ''

    def refresh_process_details(self):
        try:
            self.set_details(self.process_source.inspect(self.process_detail))
        except (OSError, ValueError) as error:
            self.desktop.offset = 0
            self.set_details(['Process inspection unavailable: ' + str(error)])

    def render(self, page, height, width):
        desktop = self.desktop
        table = self.processes if page == 'processes' else self.network
        poll = self.process_poll if page == 'processes' else self.network_poll
        if not poll.loaded:
            desktop.text(5, 3, str(poll.last_error) if poll.last_error else 'Loading Linux snapshot...')
        elif poll.last_error:
            desktop.text(5, 3, 'Refresh failed: ' + str(poll.last_error))
        else:
            count = max(1, height - 10)
            start = max(0, table.selected - count + 1)
            header = (f'{"PID":>7} {"USER":<8} {"CPU%":>6} {"MEM%":>5} {"S":>2} COMMAND'
                      if page == 'processes' else
                      f'{"INTERFACE":<12} {"TYPE":<9} {"STATE":<8} {"RX/s":>9} {"TX/s":>9}')
            desktop.text(4, 3, header, curses.A_BOLD)
            for row, entry in enumerate(table.entries[start:start + count], 5):
                if page == 'processes':
                    text = (f'{entry.pid:>7} {entry.user[:8]:<8} {entry.cpu_percent:>6.1f} '
                            f'{entry.memory_percent:>5.1f} {entry.state:>2} {entry.command}')
                else:
                    text = (f'{entry.name[:12]:<12} {entry.kind[:9]:<9} {entry.state[:8]:<8} '
                            f'{rate(entry.rx_rate):>9} {rate(entry.tx_rate):>9}')
                desktop.text(row, 3, text, curses.A_REVERSE if start + row - 5 == table.selected else 0)
            if not table.entries:
                desktop.text(5, 3, 'No matching processes.' if page == 'processes' else 'No network interfaces found.')
        if page == 'processes':
            desktop.text(height - 5, 3, f'Sort: {table.sort_key} | Search: {table.query or "[all processes]"}')
            desktop.text(height - 4, 3, '/ Search | S Sort | Enter Inspect | K Terminate | R Refresh')
        else:
            desktop.text(height - 5, 3, self.network_warning or 'Live interface traffic; connection settings are read-only.')
            desktop.text(height - 4, 3, 'Enter Addresses / Routes / DNS | R Refresh | Esc Back')

    def navigate(self, table, key):
        amount = max(1, self.desktop.screen.getmaxyx()[0] - 10)
        if key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            table.move((-1 if key in (curses.KEY_UP, curses.KEY_PPAGE) else 1)
                       * (amount if key in (curses.KEY_PPAGE, curses.KEY_NPAGE) else 1))
            return True
        if key == curses.KEY_HOME:
            table.move(-len(table.entries))
            return True
        if key == curses.KEY_END:
            table.move(len(table.entries))
            return True
        return False

    def terminate(self, entry):
        if entry is None:
            return
        # Capture an immutable process identity before displaying confirmation.
        if self.desktop.confirm(f'Send SIGTERM to PID {entry.pid} ({entry.user}): {entry.command}?'):
            self.process_source.terminate(entry)
            self.desktop.message = f'SIGTERM sent to PID {entry.pid}'
            self.process_poll.request()

    def handle(self, page, key):
        desktop = self.desktop
        if page == 'processes':
            if self.navigate(self.processes, key):
                return
            if key == '/':
                query = desktop.prompt('Search processes (PID, user or command)', self.processes.query)
                if query is not None:
                    self.processes.set_query(query)
            elif key in ('s', 'S'):
                self.processes.cycle_sort()
            elif key in ('r', 'R'):
                self.process_poll.request()
            elif key in ('k', 'K'):
                self.terminate(self.processes.selected_entry)
            elif key in ('\r', '\n', curses.KEY_ENTER) and self.processes.selected_entry:
                self.process_detail = self.processes.selected_entry
                desktop.page, desktop.offset = 'process_details', 0
                self.refresh_process_details()
        elif page == 'network':
            if self.navigate(self.network, key):
                return
            if key in ('r', 'R'):
                self.network_poll.request()
            elif key in ('\r', '\n', curses.KEY_ENTER) and self.network.selected_entry:
                self.network_detail = self.network.selected_entry.name
                desktop.page, desktop.offset = 'network_details', 0
                self.set_details(self.network_lines.get(self.network_detail, ()))
        elif page == 'process_details':
            if key in ('k', 'K'):
                self.terminate(self.process_detail)
            elif key in ('r', 'R'):
                self.refresh_process_details()
            else:
                desktop.scroll_lines(key)
        elif page == 'network_details':
            if key in ('r', 'R'):
                self.network_poll.request()
            else:
                desktop.scroll_lines(key)
