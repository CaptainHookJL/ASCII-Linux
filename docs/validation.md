# Current validation — 2026-10-08

Executed in a Debian 13 amd64 cloud container:

- All 103 unittest tests passed, with no skips or disabled cases: 42 earlier
  file/editor/system/widget/terminal checks; 18 editor-history tests; 18 process
  tests; 13 network tests; two polling tests; four system-view regressions;
  three extended real-terminal workflows; and three Apps-section workflows.
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
- Apps workflows launch all six built-in tools, search by name/shortcut, recover
  from empty results, navigate through the home section and F1 menu, and preserve
  unsaved editor buffers across app switches before saving actual files. ASCII,
  Unicode, and 60-by-16 terminal modes passed. Manual rendering checks passed at
  30 supported terminal sizes with both ASCII and LINUX artwork intact.
- `python3 -m desktop.main --check` and build/integration shell syntax checks passed.

ISO build was previously attempted and stopped at the root prerequisite. This
container has no root/mount/chroot capability and cannot create a usable user
namespace. No ISO artifact has been produced or boot-tested here. live-build
execution, chroot hooks, BIOS/UEFI boot, live autologin, firmware, and physical
hardware remain **unverified**. Use a Debian amd64 VM with root and mount/chroot
support to finish release checks (README.md and docs/testing.md). Rebuild earlier
images to include the updated desktop apps; source checks do not establish a
bootable distribution release.
