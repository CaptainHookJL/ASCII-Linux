"""Built-in applications available from the desktop Apps section."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Application:
    name: str
    page: str
    description: str
    shortcut: str


APPLICATIONS = (
    Application('Files', 'files', 'Browse, search, copy, move and manage your files.', 'F2'),
    Application('Text editor', 'editor', 'Write and edit text, with search and undo/redo.', 'F9'),
    Application('Terminal', 'shell', 'Open Bash to run commands and Linux tools.', 'F3'),
    Application('System information', 'system', 'View your system, memory and disk information.', 'F4'),
    Application('Processes', 'processes', 'Inspect running processes and their resource use.', 'F11'),
    Application('Network', 'network', 'View interfaces, addresses, DNS and traffic rates.', 'F12'),
)
