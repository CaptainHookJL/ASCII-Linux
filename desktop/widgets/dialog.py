"""Small input and confirmation dialogs; the desktop supplies drawing and input."""
import curses


class Dialog:
    def __init__(self, title, initial='', confirm=False):
        self.title = title
        self.value = initial
        self.cursor = len(initial)
        self.confirm = confirm
        self.cursor_position = None

    def handle(self, key):
        """Return (finished, result), where None indicates cancellation."""
        if self.confirm:
            if key == curses.KEY_RESIZE:
                return False, None
            return True, key in ('y', 'Y')
        if key in ('\x1b', '\x11'):
            return True, None
        if key in ('\n', '\r', curses.KEY_ENTER):
            return True, self.value
        if key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
            if self.cursor:
                self.value = self.value[:self.cursor - 1] + self.value[self.cursor:]
                self.cursor -= 1
        elif key == curses.KEY_DC:
            self.value = self.value[:self.cursor] + self.value[self.cursor + 1:]
        elif key == curses.KEY_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif key == curses.KEY_RIGHT:
            self.cursor = min(len(self.value), self.cursor + 1)
        elif key in (curses.KEY_HOME, '\x01'):
            self.cursor = 0
        elif key in (curses.KEY_END, '\x05'):
            self.cursor = len(self.value)
        elif key == '\x15':
            self.value, self.cursor = '', 0
        elif isinstance(key, str) and key.isprintable():
            self.value = self.value[:self.cursor] + key + self.value[self.cursor:]
            self.cursor += len(key)
        return False, None

    def render(self, draw, height, width, measure=len):
        box_width = max(20, min(width - 4, 76))
        inside = box_width - 4
        title = ''.join(c if c.isprintable() else ' ' for c in self.title)
        labels, line = [], ''
        for character in title:
            if line and measure(line + character) > inside:
                labels.append(line)
                line = ''
            line += character
        if line:
            labels.append(line)
        labels = labels[:3] or ['']
        box_height = len(labels) + 5
        y = max(0, (height - box_height) // 2)
        x = max(0, (width - box_width) // 2)
        draw(y, x, '+' + '-' * (box_width - 2) + '+')
        for row in range(1, box_height - 1):
            draw(y + row, x, '|' + ' ' * (box_width - 2) + '|')
        for row, label in enumerate(labels, 1):
            draw(y + row, x + 2, label, curses.A_BOLD)
        input_y = y + len(labels) + 1
        if self.confirm:
            draw(input_y, x + 2, 'Type y to confirm; any other key cancels.')
            self.cursor_position = None
        else:
            start = 0
            while start < self.cursor and measure(self.value[start:self.cursor]) >= inside:
                start += 1
            end = start
            while end < len(self.value) and measure(self.value[start:end + 1]) < inside:
                end += 1
            draw(input_y, x + 2, self.value[start:end], curses.A_REVERSE)
            draw(input_y + 1, x + 2, 'Enter Accept | Esc Cancel | Ctrl+U Clear')
            self.cursor_position = (input_y, x + 2 + measure(self.value[start:self.cursor]))
        draw(y + box_height - 1, x, '+' + '-' * (box_width - 2) + '+')
