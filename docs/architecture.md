# Architecture and source map

`desktop/main.py` parses options and owns terminal initialization/restoration.
`desktop/core/desktop.py` renders the status bar, framed views, launcher, keyboard
controls, confirmation dialogs, and shell suspension/resumption.
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
`build/test-qemu.sh` launches the artifact with BIOS or OVMF UEFI firmware.
`live-build/config/package-lists/ascii.list.chroot` selects runtime packages.
`live-build/config/hooks/live/0100-branding.hook.chroot` sets release identity,
hostname, and console target, and checks the power sudoers syntax.

`system/ascii-session` launches the desktop and offers a recovery Bash on error.
`system/profile/ascii-session.sh` activates that session only on tty1 and supports
an `ascii.safe` kernel command-line override. `system/ascii-power` is the narrow
power-command sudo policy. `branding/` contains issue, MOTD, and ASCII logo.
`docs/live-welcome.txt` is copied into the live user's Documents directory.

Boot flow: firmware → Debian live bootloader → kernel/live-boot → systemd →
getty/live-config autologin → login profile → ascii-session → curses desktop.
A getty handles a Linux terminal and login; it is not a graphical display manager.
`multi-user.target` is systemd's normal non-graphical service target.
`/etc/os-release` identifies ASCII Linux while retaining `ID_LIKE=debian`.

Debian live-build supplies BIOS and UEFI bootloader templates. ISO application
and volume names identify ASCII Linux; an elaborate custom boot menu is future
work. Source and application logic remain separate from the rootfs integration.
