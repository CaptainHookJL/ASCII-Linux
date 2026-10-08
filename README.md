# ASCII Linux 0.1

A Debian trixie (stable) amd64 live distribution whose primary interface is a
Python/curses desktop. No X11, Wayland, or graphical desktop is installed.
Debian supplies the kernel, systemd, apt, networking, and device support.
ASCII Linux supplies the console desktop, session startup, branding, and image
build configuration. This repository implements the first prototype milestone
from the ASCII Linux Distribution Specification.

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
and F10 opens the power menu. Arrows navigate and Enter selects. Esc returns to
the desktop; Ctrl+Q asks to leave. Type `exit` in Bash to return to the desktop.
Power actions require confirmation and normal sudo authorization.

Files supports folder navigation, parent navigation, hidden entries (`H`),
refresh (`R`), permissions/owner/size/date, and bounded text previews. It is
intentionally read-only in this milestone. The system page shows CPU model,
memory, root disk usage, uptime, load, kernel, and network interface states.
The top bar samples CPU and memory once per second without blocking input.

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
