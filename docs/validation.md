# Current validation — 2026-10-08

Source and native X11 checks ran in a Debian 13 amd64 cloud container. The
graphical-session results and earlier desktop baseline are recorded below.

## Graphical-session update

- All 178 unittest tests passed with no skips, covering the earlier desktop
  checks plus catalog modes, graphical launching, session behavior and the QEMU
  helper. Mode checks cover legacy terminal defaults, persistence and changing
  a saved mode. Launcher checks cover nonblocking
  startup, inherited display variables, a home working directory, absent
  displays, missing executables, exit reporting and editor-buffer preservation.
  Session checks cover runtime selection, console fallback, local-TTY startup
  and recovery-shell startup.
- Four VM-launcher tests passed using a disposable argument-capture executable.
  They check the default GTK display, console curses display/recovery guidance,
  invalid-option rejection and help without an ISO. They do not boot QEMU.
- `python3 -m desktop.main --check`, all build/integration shell syntax checks
  including the new session helpers, and `git diff --check` passed.
- A headless Xorg server with the Debian dummy video driver ran the actual
  Openbox/xterm session. The ASCII terminal filled its 1280-by-800 display with
  zero frame extents. A native `xmessage` window appeared above it with normal
  decorations; Alt+Tab switched in both directions and Super+D focused and
  raised the ASCII desktop. This checks native X11 windows, not an ISO boot.
- A real Apps UI workflow registered `xmessage` through N with graphical mode,
  then launched its native window with Enter. The ASCII desktop stayed alive;
  F9 opened the editor and saved a temporary document while the app remained
  open. Alt+Tab and Super+D worked. Alt+F4 closed the graphical app and left the
  ASCII desktop protected; Ctrl+click on all three mouse buttons opened no
  xterm menus. Confirmed desktop logout exited successfully and cleaned up its
  own terminal and Openbox, leaving the independent Xorg server and unrelated
  test window running. Actual ISO build and BIOS/UEFI boot remain unverified.

## Earlier desktop baseline

Executed before graphical-session changes:

- All 150 unittest tests passed, with no skips or disabled cases: 42 earlier
  file/editor/system/widget/terminal checks; 18 editor-history tests; 18 process
  tests; 13 network tests; two polling tests; four system-view regressions;
  three extended real-terminal workflows; 32 user-app catalog tests; four
  Apps-section workflows; one Unicode Apps-panel regression; eight installation
  controller tests; and five download/install terminal workflows.
- File tests exercise copy/move/rename/mkdir/name filtering/deletion, source
  preservation after failures, collision races, staging cleanup, symbolic links,
  directory trees, local FIFO moves, simulated cross-device move fallback, and
  nonblocking previews. Real USB/cross-mount moves still need separate testing.
- Editor tests exercise UTF-8/LF/CRLF round trips, final newlines, save conflicts,
  permission preservation, unsupported input, and undo/redo of edits and cursors.
  Undo across saves correctly restores the modified/saved state; failed edits and
  saves preserve history. History is bounded by snapshot count and UTF-8 byte size.
- Process tests cover stat parsing, CPU interval/memory data, filtering/sorting,
  selection, inspection, exits, permissions, PID reuse, and pidfd-only SIGTERM.
  Functional signal tests create their own child process, then terminate only
  that child. The real-terminal test cancels first and confirms a signal afterward.
  No pre-existing host process is signalled.
- Network tests cover addresses, MAC/type/state, DNS, IPv4/IPv6/default/multipath
  routes, traffic deltas/resets, absent tools, malformed data, and Linux fallbacks.
  Real interface inspection passed without changing any connection settings.
  Wi-Fi kind detection is covered by fixtures; physical Wi-Fi hardware and
  connection changes have not been tested. Connection management is deferred.
- Polling tests prove slow/erroring sources run outside the UI thread, apply
  snapshots on the main thread, and retain previous data on failed refresh.
- UI regressions check fresh process details without changing identity, immutable
  termination capture during refresh, disappeared interfaces and scroll recovery,
  visible refresh errors, and wrapped addresses without missing values.
- Terminal workflows cover existing files/editor/Bash/power cancellation plus
  F1/F11/F12 navigation, sorting/search/inspection, network details/scrolling,
  confirmed child termination, and undo/redo around actual file saves.
- Apps starts empty and contains only user-registered launchers. Catalog tests
  cover persistence, quoted/literal arguments, Unicode, XDG paths, malformed
  records, external changes, write failures and temporary-file cleanup.
  Terminal workflows register and execute real user commands, check the home
  working directory, reload after restart, cancel/confirm launcher removal while
  preserving app files, scroll longer lists, search/cancel, recover from missing
  executables, and preserve unsaved editor buffers before saving actual files.
  Built-in tools remain in F1 and on their function keys. ASCII, Unicode, and
  60-by-16 terminal modes passed. Manual rendering checks covered empty and
  populated catalogs at 30 supported terminal sizes with both logos intact;
  a regression checks that wide Unicode descriptions stay inside the panel.
- Installation checks validate launch commands and catalog limits before running
  anything, preserve the catalog when installation fails or is cancelled, and
  recheck external edits before committing a successful install's launcher.
  Real-terminal tests download a script with curl from an in-process localhost
  HTTP server, register and execute it, and reject a failed HTTP pipeline even
  when its final shell command exits zero. They cover review scrolling/resizing,
  ignored approval below the supported terminal size, cancellation, and Ctrl+C
  interruption while preserving and saving an existing editor buffer. No remote
  installer, sudo command or host package change was executed by these tests.
- The Brave example uses its documented install/launch commands. The new live
  configuration includes X11; other hosts need an existing graphical session.
  Read-only requests to the official website
  and installer URL returned HTTP 403 in this environment. Brave installation,
  repository/package setup, and native GUI startup remain **unverified** here.
- `python3 -m desktop.main --check` and build/integration shell syntax checks passed.

ISO build was previously attempted and stopped at the root prerequisite. This
container has no root/mount/chroot capability and cannot create a usable user
namespace. No ISO artifact has been produced or boot-tested here. live-build
execution, chroot hooks, BIOS/UEFI boot, live autologin, firmware, and physical
hardware remain **unverified**. Use a Debian amd64 VM with root and mount/chroot
support to finish release checks (README.md and docs/testing.md). Rebuild earlier
images to include the updated desktop apps; source checks do not establish a
bootable distribution release.
