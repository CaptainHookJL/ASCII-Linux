# ASCII Linux 0.1

A Debian trixie (stable) amd64 live distribution whose primary interface is a
Python/curses desktop. No X11, Wayland, or graphical desktop is installed.
Debian supplies the kernel, systemd, apt, networking, and device support.
ASCII Linux supplies the console desktop, session startup, branding, and image
build configuration. This repository implements the live-system prototype and its next desktop
milestones: file operations, a built-in text editor, process management and network
information, from the ASCII Linux Distribution Specification.

## Run the desktop now

From the repository root, on Linux with Python 3.11 or newer:

```sh
python3 -m desktop.main
python3 -m desktop.main --ascii    # fallback for limited fonts
python3 -m desktop.main --check    # noninteractive Linux capability check
python3 -m unittest discover -s tests -v
```

No pip packages are required. Use a terminal of at least 60 columns by 16 rows.
F1 opens the launcher, F2 opens Files, F3 launches Bash, F4 opens system information,
F9 opens or resumes the text editor, F10 opens the power menu, F11 opens Processes,
and F12 opens Network. All apps are also available through F1. Arrows
navigate and Enter selects. Esc goes back; Ctrl+Q closes the editor or asks to
leave the desktop. Type `exit` in Bash to return to the desktop.
Power actions require confirmation and normal sudo authorization.

Files supports folder navigation, parent navigation, hidden entries (`H`),
refresh (`R`), permissions/owner/size/date, and bounded text previews. New controls:

| In Files | Action |
| --- | --- |
| Enter / Backspace | Open or preview / parent directory |
| `/` | Filter filenames, case insensitive; empty input clears |
| F5 / F6 | Copy / move selected file or directory |
| F7 / F8 | Create directory / confirmed permanent deletion |
| N / E | Rename / open selected file in the editor |

Copy and move accept relative paths, absolute paths, or existing destination
folders. Existing destinations are refused instead of overwritten. Directory
operations preserve symbolic links; deletion removes links without following
their targets. Copy/delete work runs outside the UI thread with byte progress.
Filesystem permissions still apply, and failures appear in the status line.
Search applies to names in the current folder; navigation clears the filter.
Deletion is permanent and has no trash/undo in this milestone.

| In Text editor | Action |
| --- | --- |
| Ctrl+S / F6 | Save / save under a new name |
| Ctrl+O / Ctrl+N | Open file / new document |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+F / F5 | Find text / next match (wraps) |
| Arrows, Home/End, Page Up/Down | Move cursor |
| Backspace / Delete / Tab | Remove text / remove next character / insert four spaces |
| Esc or Ctrl+Q | Close; ask before discarding unsaved changes |

The editor supports regular UTF-8 files up to 1 MiB, line numbers, Unicode input,
LF/CRLF preservation, and atomic saving. Save As refuses existing files. Changes
made by another program are detected before saving. New files have mode 0600;
existing saves retain permissions and ownership. Binary files, invalid UTF-8,
and mixed line endings are refused with an error instead of altered. Use F6 to
save an edited read-only document under a new name. Ctrl+U clears dialog input.
Switching applications preserves the editor buffer; logout and power actions
warn about any unsaved buffer. Undo/redo restores content and cursor position;
the modified flag follows the last successfully saved text, including across saves.
History retains up to 50 edits (100 before/after snapshots) and 8 MiB of UTF-8
snapshot text; oldest edits expire at those bounds. Clipboard integration is future work.

The system page shows CPU model, memory, root disk usage, uptime, load, kernel,
and network interface states. The top bar samples CPU and memory once per second,
including while a dialog or filesystem operation is active.

## Processes and Network

Processes (`F11` or F1 Menu) shows PID, user, CPU%, memory%, state and command.
CPU percentages use the top convention: 100% is one fully occupied core; the
first snapshot establishes a baseline and displays 0%. A background snapshot
updates about once per second while the app is visible.

| In Processes | Action |
| --- | --- |
| Arrows / Page Up/Down / Home/End | Select and scroll |
| `/` | Search PID, user, state or command; empty input clears |
| S | Cycle CPU, memory, PID, user and command sorting |
| Enter | Inspect process identity, resources, executable and working directory |
| K | Confirm sending SIGTERM to the selected process |
| R / Esc | Refresh / return |

Termination sends only SIGTERM, with normal OS permissions and no sudo escalation.
PID 1 and the desktop itself are protected. Linux pidfds and process start times
prevent a changed/reused PID from receiving a signal. Exited processes and denied
operations show an error. SIGTERM is a request; a program may handle or ignore it.

Network (`F12` or F1 Menu) lists Ethernet, Wi-Fi and other interfaces, state, and
receive/send rates. Arrows select; Enter shows MAC, IPv4/IPv6 addresses, default
gateways, DNS resolvers and byte totals. Details wrap and scroll on narrow screens.
R requests a new snapshot; Esc returns. Reads run in a background worker about
every two seconds. First-sample rates are 0; later rates use counter differences.
Warnings distinguish unavailable information from a disconnected/unconfigured
interface. DNS reflects `/etc/resolv.conf`, which may point to a local resolver.

This milestone displays network information only; Wi-Fi connection management
is deferred. It uses the image's existing iproute2 tools, with Linux fallbacks
when unavailable, and never changes host network settings. If your terminal
intercepts F11/F12, select the app through F1 instead.

## Build the live ISO

Use a **Debian 13 amd64 VM or physical host**, with root, working mount/chroot
capabilities, an Internet connection to Debian mirrors, and at least 10 GiB of
free disk space (20 GiB recommended). An unprivileged container cannot run this
build. Install the tools with normal signed Debian package verification:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends live-build debootstrap \
  squashfs-tools xorriso isolinux syslinux-common grub-pc-bin \
  grub-efi-amd64-bin mtools dosfstools qemu-system-x86 ovmf
# Needed if you extracted GitHub's ZIP rather than cloning:
chmod +x build/*.sh system/ascii-session live-build/config/hooks/live/*.chroot
sudo ./build/build-iso.sh
```

Verify the checksum from the output directory:

```sh
(cd build/output && sha256sum -c ascii-linux-amd64.iso.sha256)
```

The artifact is `build/output/ascii-linux-amd64.iso`. The build uses Debian's
signed current trixie repositories. Scripts and configuration are repeatable,
but this is **not a bit-for-bit reproducible release**: package versions and
build timestamps are not pinned. `build/work` holds disposable live-build state.
Before rebuilding, run `sudo ./build/clean.sh`; it retains existing ISO outputs.

## Boot testing

```sh
./build/test-qemu.sh           # BIOS, KVM where accessible, otherwise software emulation
./build/test-qemu.sh --uefi    # OVMF UEFI
```

QEMU uses its curses VGA display; run these commands in a real terminal.
Use the VM power menu to stop QEMU, or terminate its process from another
terminal. If your terminal does not support that display,
run QEMU on a desktop host with `qemu-system-x86_64 -m 2048 -cdrom
build/output/ascii-linux-amd64.iso -boot d`.

The live system uses Debian live-config's dedicated `ascii` user and tty1
console autologin. A profile hook launches `ascii-session`, which runs the
desktop without root. Other TTYs stay available. Narrow sudo rules allow only
confirmed live-user reboot/poweroff commands; normal Debian live sudo policy
also applies. This is an intentionally autologged-in live prototype, not a
hardened installed system. It has no disk installer and no persistent storage
by default. Never expose it as an authenticated multiuser installation.

See [testing and recovery](docs/testing.md), [architecture](docs/architecture.md),
and [roadmap](docs/roadmap.md). Current validation is recorded in
[validation](docs/validation.md); configuration alone is not proof an ISO boots.
