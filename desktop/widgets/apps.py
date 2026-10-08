"""Selectable built-in applications for the home screen and Apps page."""
import curses
import textwrap

from desktop.apps.catalog import APPLICATIONS
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
    def __init__(self):
        order = {entry.page: index for index, entry in enumerate(APPLICATIONS)}
        self.table = Table(
            identity=lambda entry: entry.page,
            searchable=lambda entry: f'{entry.name} {entry.description} {entry.shortcut}',
            sorts={'catalog': (lambda entry: order[entry.page], False)},
            sort_key='catalog')
        self.table.update(APPLICATIONS)

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

    def _label(self, entry, available, desktop):
        # Keep the keyboard shortcut visible even when a name is clipped.
        name_width = max(0, available - len(entry.shortcut) - 4)
        name = fit(entry.name, name_width, desktop.width)
        padding = max(0, name_width - desktop.width(name))
        return name + ' ' * padding + '  ' + entry.shortcut

    def render(self, desktop, height, width):
        available = max(1, width - 6)
        count = min(len(APPLICATIONS), max(1, height - 10))
        start, entries = self._rows(count)
        for row, entry in enumerate(entries, 4):
            selected = start + row - 4 == self.table.selected
            label = ('> ' if selected else '  ') + self._label(entry, available - 2, desktop)
            desktop.text(row, 3, label, curses.A_REVERSE if selected else 0)
        if not entries:
            desktop.text(4, 3, 'No matching apps. Press / to change your search.')

        description_start = min(4 + len(entries) + 1, height - 6)
        description_end = height - 6
        if self.selected_entry:
            lines = textwrap.wrap(self.selected_entry.description, width=available)
            for row, line in enumerate(lines, description_start):
                if row > description_end:
                    break
                desktop.text(row, 3, line)
        desktop.text(height - 5, 3,
                     fit('Search: ' + (self.query or '[all apps]'), available, desktop.width),
                     curses.A_DIM)
        desktop.text(height - 4, 2, '/ Search | Enter Open | Arrows/Tab Select | Esc Desktop')

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
        count = min(len(APPLICATIONS), max(1, bottom - top - 3))
        start, entries = self._rows(count)
        for row, entry in enumerate(entries, top + 2):
            selected = start + row - top - 2 == self.table.selected
            label = ('> ' if selected else '  ') + self._label(entry, available - 2, desktop)
            desktop.text(row, x + 2, label, curses.A_REVERSE if selected else 0)
        if not entries:
            desktop.text(top + 2, x + 2, 'No matching apps.')
        if self.selected_entry:
            description_start = top + 3 + len(entries)
            for row, line in enumerate(textwrap.wrap(self.selected_entry.description,
                                                     width=available), description_start):
                if row >= bottom - 1:
                    break
                desktop.text(row, x + 2, line, curses.A_DIM)
        desktop.text(bottom - 1, x + 2, 'A All apps | Enter Open')
