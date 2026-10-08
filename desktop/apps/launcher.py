"""Launch native windows without handing their output to the curses terminal."""
import os
from pathlib import Path
import subprocess


def graphical_session_available():
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


class GraphicalLauncher:
    def __init__(self):
        self.children = []

    def launch(self, app):
        if not graphical_session_available():
            raise ValueError('No graphical display. Start ascii-session from a Linux TTY or desktop terminal.')
        child = subprocess.Popen(
            app.command, cwd=Path.home(), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        self.children.append((app, child))

    def poll(self):
        """Reap finished launchers, including browser handoffs to existing windows."""
        finished = []
        active = []
        for app, child in self.children:
            status = child.poll()
            if status is None:
                active.append((app, child))
            else:
                finished.append((app, status))
        self.children = active
        return finished
