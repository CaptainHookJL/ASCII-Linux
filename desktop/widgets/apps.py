"""Selectable user applications for the home screen and Apps page."""
import curses
import shlex
import textwrap

from desktop.apps.catalog import AppCatalog
from desktop.widgets.table import Table


def fit(text, available, measure):
    """Clip a label using the desktop's terminal-cell measurement."""
    if measure(text) <= available:
        return text
    suffix = '...' if available >= 3 else ''
    available -= len(suffix)
    prefix = ''
    for character in text:
        if measure(prefix + character) > available:
            break
        prefix += character
    return prefix + suffix


class AppsSection:
    def __init__(self, catalog=None):
        self.catalog = catalog if catalog is not None else AppCatalog()
        self.error = ''
        self.table = Table(
            identity=lambda entry: entry.id,
            searchable=lambda entry: f'{entry.name} {entry.description} {shlex.join(entry.command)}',
            sorts={'name': (lambda entry: (entry.name.casefold(), entry.id), False)},
            sort_key='name')
        try:
            self.refresh()
        except (OSError, ValueError):
            pass  # Keep the desktop usable; the load error is shown in the status bar.

    def refresh(self):
        try:
            entries = self.catalog.load()
        except (OSError, ValueError) as error:
            self.error = str(error)
            raise
        self.table.update(entries)
        self.error = ''

    def add(self, name, command, description=''):
        entry = self.catalog.add(name, command, description)
        self.table.update(self.catalog.entries)
        self.table.set_query('')
        self.table.selected = next(i for i, app in enumerate(self.entries) if app.id == entry.id)
        self.error = ''
        return entry

    def remove(self, app_id):
        self.catalog.remove(app_id)
        self.table.update(self.catalog.entries)
        self.error = ''

    @property
    def entries(self):
        return self.table.entries

    @property
    def selected_entry(self):
        return self.table.selected_entry

    @property
    def query(self):
        return self.table.query

    def move(self, delta):
        self.table.move(delta)

    def set_query(self, query):
        self.table.set_query(query)

    def next(self):
        if self.entries:
            self.table.selected = (self.table.selected + 1) % len(self.entries)

    def _rows(self, count):
        start = max(0, self.table.selected - count + 1)
        return start, self.entries[start:start + count]

    def render(self, desktop, height, width):
        available = max(1, width - 6)
        count = max(1, height - 10)
        start, entries = self._rows(count)
        for row, entry in enumerate(entries, 4):
            selected = start + row - 4 == self.table.selected
            label = ('> ' if selected else '  ') + fit(entry.name, available - 2, desktop.width)
            desktop.text(row, 3, label, curses.A_REVERSE if selected else 0)
        if not entries:
            desktop.text(4, 3, 'No matching apps. Press / to change your search.' if self.query else
                         'No user apps yet. Press N to add one.')

        description_start = min(4 + len(entries) + 1, height - 6)
        description_end = height - 6
        if self.selected_entry:
            entry = self.selected_entry
            lines = textwrap.wrap(entry.description or shlex.join(entry.command), width=available)
            for row, line in enumerate(lines, description_start):
                if row > description_end:
                    break
                desktop.text(row, 3, fit(line, available, desktop.width))
        desktop.text(height - 5, 3,
                     fit('Search: ' + (self.query or '[all apps]'), available, desktop.width),
                     curses.A_DIM)
        desktop.text(height - 4, 2, 'N Add | D Remove | R Reload | / Search | Enter Open')

    def render_compact(self, desktop, width):
        entry = self.selected_entry
        if entry:
            prefix, suffix = 'Apps [A] > ', ' | Enter Open'
            name = fit(entry.name, width - 6 - len(prefix + suffix), desktop.width)
            label = prefix + name + suffix
        else:
            label = 'Apps [A] | No user apps yet'
        desktop.text(3, 3, label, curses.A_BOLD)

    def render_home(self, desktop, height, width):
        if width < 86:
            return
        x, top = 42, 4
        bottom = min(19, height - 4)
        panel_width = width - x - 4
        available = panel_width - 4
        desktop.text(top, x, '+' + '-' * (panel_width - 2) + '+')
        desktop.text(bottom, x, '+' + '-' * (panel_width - 2) + '+')
        for row in range(top + 1, bottom):
            desktop.text(row, x, '|')
            desktop.text(row, x + panel_width - 1, '|')
        desktop.text(top + 1, x + 2, 'Apps', curses.A_BOLD)
        count = max(1, bottom - top - 3)
        start, entries = self._rows(count)
        for row, entry in enumerate(entries, top + 2):
            selected = start + row - top - 2 == self.table.selected
            label = ('> ' if selected else '  ') + fit(entry.name, available - 2, desktop.width)
            desktop.text(row, x + 2, label, curses.A_REVERSE if selected else 0)
        if not entries:
            desktop.text(top + 2, x + 2, 'No matching apps.' if self.query else 'No user apps yet.')
            desktop.text(top + 3, x + 2, 'A Apps, then N to add.')
        if self.selected_entry:
            description_start = top + 3 + len(entries)
            entry = self.selected_entry
            for row, line in enumerate(textwrap.wrap(entry.description or shlex.join(entry.command),
                                                     width=available), description_start):
                if row >= bottom - 1:
                    break
                desktop.text(row, x + 2, fit(line, available, desktop.width), curses.A_DIM)
        desktop.text(bottom - 1, x + 2, 'A All apps | Enter Open')
