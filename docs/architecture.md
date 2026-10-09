# Architecture and source map

`desktop/main.py` parses options and owns terminal initialization/restoration.
`desktop/core/desktop.py` renders the status bar, framed views, launcher, keyboard
controls, confirmation dialogs, and shell suspension/resumption.
`desktop/apps/catalog.py` validates, loads and saves the user's launcher catalog
at `${XDG_DATA_HOME:-~/.local/share}/ascii-linux/apps.json`, ignoring relative XDG
paths. Each JSON record has an id, name, command argument list, description and
launch mode (`terminal` or `graphical`). Older records without a mode default to terminal.
It parses entered commands with POSIX `shlex`, uses atomic saves and checks for
external changes. It does not install or execute applications.
`desktop/widgets/apps.py` renders the desktop Apps panel and full Apps page using
the shared table selection/filtering model. It follows terminal size, sorts
entries alphabetically by name, and leaves application startup to the desktop controller.
The desktop controller handles adding/removing launchers and runs their launch
commands without an implicit shell, with the user's home as the working
directory. Terminal commands suspend and restore curses. Graphical commands
inherit display/session variables and run in background child processes; the
controller polls and reaps exited children and reports nonzero exit statuses.
Their standard streams do not write over the ASCII interface. A graphical launch
without a display is rejected. `M` changes a saved launcher's mode. Install from command (`I`)
collects a Bash download/install command and a separate launch argument list.
It validates the launcher and catalog before execution, shows a scrollable
review of both commands, and requires Y to proceed. The installer runs as
`/bin/bash -o pipefail -c` in the user's home. Only an exit status of 0 permits
saving the launcher; failure or interruption is reported after restoring the
desktop and does not undo files changed by the installer. Built-in tools keep
their F1 and function-key routes and are separate from the initially empty user
Apps list. There is no default Brave entry, automatic installer, or `.desktop`
discovery. The live image supplies a minimal X11 session for native graphical
apps. Brave installation and execution have not been validated in this cloud
environment.
`tests/test_apps_workflows.py` exercises the Apps section in real terminals.
`tests/test_install_controller.py` checks preflight validation, review cancellation,
installer status handling and launcher commits. `tests/test_app_install_workflows.py`
uses real terminals and `curl` against a local in-process HTTP server to check
downloads, pipeline failure, scrollable review, cancellation and interruption.
`desktop/apps/file_manager.py` implements directory navigation, name filtering,
file/directory mutations, and safe previews. It uses Linux libc's `renameat2`
with NOREPLACE to publish copies and move directories without racing another
writer. This narrowly scoped ctypes call avoids adding an external helper or
replacing an existing destination; a link/unlink fallback supports files on
filesystems without that syscall. Cross-device moves stage a copy before deleting
the source. If source removal fails, the destination is retained and reported.
`desktop/apps/text_editor.py` owns the text buffer, cursor, search, bounded UTF-8
loading, conflict-aware atomic saves, and bounded undo/redo. Before/after snapshots
restore cursor and content; the dirty flag compares against the saved text rather
than clearing when history is exhausted. It contains no curses calls.
`desktop/apps/process_manager.py` samples procfs CPU/RSS and process identity,
inspects process metadata, and sends confirmed-by-UI SIGTERM through pidfds.
`desktop/apps/network_manager.py` reads interface/address/route/resolver/traffic
information through sysfs, procfs and bounded read-only iproute2 requests.
`desktop/apps/web_browser.py` implements the text browser without a third-party
rendering engine. Python's `urllib` fetches HTTP/HTTPS pages with normal TLS
certificate verification, bounded responses and content-type checks.
`html.parser.HTMLParser` turns HTML into text and numbered links, resolving
relative targets against the final response address. Scripts and styles are
omitted, images use alt-text placeholders without fetching, and forms cannot be
edited or submitted. Plain-text responses also display. A page has at most 2,048
numbered links. Cookies last only for the in-memory browser session.
The browser model caches at most 100 back/forward pages within an 8 MiB budget,
retaining the current page, and page loading runs off
the curses thread. Cancelled or superseded requests cannot replace the active
page. `desktop/apps/browser_data.py` stores up to 256 bookmarks as JSON name/URL
records under the user's absolute XDG data directory in
`ascii-linux/browser-bookmarks.json`, otherwise `~/.local/share`. An empty store
does not create a file. Writes are atomic, detect external edits, and refuse
unsafe or malformed files. Adding the same URL keeps its existing bookmark.
`desktop/core/web_browser_view.py` renders wrapped ASCII page text, selectable
links, case-insensitive find results and saved bookmarks. It owns scrolling,
link selection, address prompts, bookmark creation/removal and navigation keys;
the worker never accesses curses. Bookmark R reloads externally changed data.
`desktop/browser.py` is the standalone `python3 -m desktop.browser [URL]` entry
point. The desktop's W/F1 route uses the same browser interface; it does not add
an entry to the saved user Apps catalog. `system/ascii-browser` runs the standalone
browser from the checkout or installed `/usr/lib/ascii-linux` source tree and is
staged as `/usr/local/bin/ascii-browser` in the live image.
`tests/test_web_browser.py`, `tests/test_browser_data.py` and
`tests/test_browser_view.py` cover fetching/rendering/navigation, bookmark
integrity and browser controls. `tests/test_browser_workflows.py` runs actual
desktop, standalone and Apps-launched browser flows in pseudo-terminals against
a disposable local HTTP server.
`desktop/core/system_views.py` renders these apps and handles their keyboard actions.
`desktop/widgets/table.py` keeps selections stable over immutable snapshots,
filters and sorts. `desktop/utils/polling.py` samples on a worker thread and applies
completed snapshots only on the UI thread, so slow tools cannot block input.
`desktop/widgets/dialog.py` is the reusable input/confirmation widget.
`desktop/utils/jobs.py` runs copy/move/delete work outside the curses thread,
retaining a bounded progress snapshot. Only the UI thread touches curses; other
file operations and session exit wait until an active filesystem job finishes.
`desktop/utils/system.py` reads `/proc` and `/sys` with the logged-in user's rights.
`tests/test_desktop.py` exercises data access and the original curses workflows.
`tests/test_file_operations.py` covers mutation integrity and failure cases;
`tests/test_text_editor.py` covers editing, save conflicts, permissions and encodings;
`tests/test_widgets.py` checks cursor/clipping alignment; and
`tests/test_workflows.py` exercises file/editor workflows in a real pseudo-TTY.
`tests/test_process_manager.py`, `tests/test_network_manager.py` and
`tests/test_editor_history.py` validate the new app models. `tests/test_polling.py`
checks slow/erroring snapshot sources. `tests/test_system_views.py` tests live
identity and detail transitions; `tests/test_system_workflows.py` tests the new apps
and editor history in a real terminal. Signal tests target only children they create.
A pseudo-TTY is a terminal pair used to automate keyboard input and screen output.

`build/build-iso.sh` configures Debian live-build, stages source and integration
files into its temporary tree, builds the ISO, and generates a SHA-256 checksum.
`build/clean.sh` removes temporary state through live-build's cleanup path.
`build/test-qemu.sh` launches the artifact with BIOS or OVMF UEFI firmware in a
GTK window. Its `--console` option selects curses VGA for console recovery tests;
append `ascii.console` to the boot menu's kernel command line for those tests.
`live-build/config/package-lists/ascii.list.chroot` selects runtime packages.
`live-build/config/hooks/live/0100-branding.hook.chroot` sets release identity,
hostname, and console target, and checks the power sudoers syntax.

`system/ascii-session` selects the runtime: an existing graphical terminal uses
the console interface with access to that display, and a local TTY without a
display starts a dedicated X11 session through `startx`. `--console` forces
console mode; `--graphical` requires a local TTY without an existing display.
`system/ascii-console` runs the Python desktop and offers a recovery Bash on error.
`system/ascii-xsession` starts a D-Bus session, Openbox and a frameless, maximized
xterm containing the ASCII desktop. The terminal uses a normal window layer so
Alt+Tab can bring it back above graphical apps. Super+D focuses the desktop.
Openbox supplies native window management without a panel or root menu. Exiting
the desktop ends the dedicated session; X11 startup failure falls back to console.
`system/openbox/rc.xml` defines the frameless desktop rule, native app decorations
and window-switching keys, and omits root-menu actions. It is installed as
`/etc/ascii-linux/openbox.xml`; X11 uses local sockets with TCP listening disabled.
`system/profile/ascii-session.sh` activates that session only on tty1 and supports
`ascii.safe` for a recovery shell and `ascii.console` for a console desktop.
`system/ascii-power` is the narrow
power-command sudo policy. `branding/` contains issue, MOTD, and ASCII logo.
`docs/live-welcome.txt` is copied into the live user's Documents directory.

Boot flow: firmware → Debian live bootloader → kernel/live-boot → systemd →
getty/live-config autologin → login profile → ascii-session → startx → D-Bus/Openbox
→ xterm → ASCII desktop. A native graphical app opens another X11 window.
A getty handles a Linux terminal and login; it is not a graphical display manager.
`multi-user.target` is systemd's normal non-graphical service target; X11 starts
within the live user's login session rather than through a display manager.
`/etc/os-release` identifies ASCII Linux while retaining `ID_LIKE=debian`.

Debian live-build supplies BIOS and UEFI bootloader templates. ISO application
and volume names identify ASCII Linux; an elaborate custom boot menu is future
work. Source and application logic remain separate from the rootfs integration.
