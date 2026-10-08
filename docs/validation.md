# Current validation — 2026-10-08

Executed in a Debian 13 amd64 cloud container:

- Five unittest tests passed: file navigation/hidden entries/metadata/preview;
  bounded previews and special-file rejection; real Linux statistics;
  complete PTY keyboard workflows in ASCII and Unicode modes.
- Both PTY workflows exercise launcher, file preview, system view, Bash return,
  reboot cancellation, and confirmed logout. They never reboot the host.
- `python3 -m desktop.main --check` passed with real `/proc` and `/sys` information.
- Bash/sh syntax checks passed for the build and integration scripts.

ISO build was attempted and stopped at the root prerequisite. This container
runs as uid 1000, has no sudo/live-build/QEMU, no effective Linux capabilities,
and forbids user namespace mapping (`/proc/self/uid_map` is read-only).
There is no ISO artifact. live-build configuration execution, chroot hooks,
BIOS/UEFI boot, live autologin, firmware, and physical hardware are **unverified**.
A Debian amd64 VM with root and mount/chroot support is required to finish the
version 0.1 release checks. Follow README.md and docs/testing.md. Source readiness
and desktop tests do not establish a bootable distribution release.
