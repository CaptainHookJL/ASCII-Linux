# Current validation — 2026-10-08

Executed in a Debian 13 amd64 cloud container:

- 42 unittest tests passed: the original file/browser/system/ASCII and Unicode
  terminal tests; 14 file-operation tests; 15 editor-model tests; four Unicode
  widget tests; and four extended real-terminal workflows.
- File tests exercise copy/move/rename/mkdir/name filtering/deletion, source
  preservation after failures, collision races, copy staging cleanup, symbolic
  links, directory trees, same-filesystem FIFO moves, cross-device move fallback,
  and nonblocking previews. Cross-device fallback is simulated; this container's
  filesystem setup does not independently establish real USB/mount behavior.
- Editor tests exercise editing/cursor/search, UTF-8 and LF/CRLF round trips,
  final newlines, repeat saves, mode preservation, existing-destination refusal,
  external-change detection, read-only files, and special/binary/oversized input.
- Real-terminal workflows edit and save actual temporary files, search, switch
  applications, save under another name, cancel and confirm deletion, cancel
  unsaved document replacement/logout, recover from invalid home-directory input,
  and shrink/restore the terminal while a save dialog is open.
- Unicode widget tests check CJK/combining cursor alignment, ASCII fallback, and
  display-cell clipping/scrolling. Cursor columns count code points; full emoji
  grapheme navigation and clipboard/undo are future work.
- `python3 -m desktop.main --check` passed with real `/proc` and `/sys` information.
- Bash/sh syntax checks passed for the build and integration scripts.

ISO build was previously attempted and stopped at the root prerequisite. This
container runs as uid 1000, has no sudo/live-build/QEMU, no effective Linux
capabilities, and forbids user namespace mapping (`/proc/self/uid_map` is read-only).
No ISO artifact has been produced or boot-tested here. live-build configuration
execution, chroot hooks, BIOS/UEFI boot, live autologin, firmware, and physical
hardware remain **unverified**. A Debian amd64 VM with root and mount/chroot
support is required to finish release checks. Follow README.md and docs/testing.md.
Rebuild any earlier ISO to include the file manager and editor updates; source
validation does not establish a bootable distribution release.
