#!/bin/bash
# Build in a disposable directory; never contaminate the source checkout.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (( EUID != 0 )); then
    echo 'ISO builds require root on a Debian amd64 host with mount/chroot capabilities.' >&2
    exit 1
fi
for tool in lb debootstrap xorriso mksquashfs; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
[[ $(dpkg --print-architecture) == amd64 ]] || { echo 'Use an amd64 builder.' >&2; exit 1; }
WORK="$ROOT/build/work"
mkdir -p "$WORK" "$ROOT/build/output"
cd "$WORK"
if [[ -d chroot || -d binary ]]; then
    echo 'Existing build state found. Run sudo ./build/clean.sh before rebuilding.' >&2
    exit 1
fi
lb config --mode debian --distribution trixie --architectures amd64 \
    --binary-images iso-hybrid --bootloaders 'syslinux,grub-efi' \
    --archive-areas 'main contrib non-free non-free-firmware' \
    --debian-installer none --apt-recommends false \
    --iso-application 'ASCII Linux 0.1' --iso-volume 'ASCII_LINUX_01' \
    --bootappend-live 'boot=live components username=ascii hostname=ascii-linux locales=en_US.UTF-8 keyboard-layouts=us'
cp -a "$ROOT/live-build/config/." config/
mkdir -p config/includes.chroot/usr/lib/ascii-linux config/includes.chroot/usr/local/bin \
    config/includes.chroot/etc/profile.d config/includes.chroot/etc/sudoers.d \
    config/includes.chroot/etc/ascii-linux \
    config/includes.chroot/etc/skel/Documents
cp -a "$ROOT/desktop" config/includes.chroot/usr/lib/ascii-linux/
find config/includes.chroot/usr/lib/ascii-linux -type d -name __pycache__ -prune -exec rm -rf {} +
install -m 755 "$ROOT/system/ascii-session" config/includes.chroot/usr/local/bin/ascii-session
install -m 755 "$ROOT/system/ascii-console" config/includes.chroot/usr/local/bin/ascii-console
install -m 755 "$ROOT/system/ascii-xsession" config/includes.chroot/usr/local/bin/ascii-xsession
install -m 755 "$ROOT/system/ascii-browser" config/includes.chroot/usr/local/bin/ascii-browser
install -m 644 "$ROOT/system/openbox/rc.xml" config/includes.chroot/etc/ascii-linux/openbox.xml
install -m 644 "$ROOT/system/profile/ascii-session.sh" config/includes.chroot/etc/profile.d/ascii-session.sh
install -m 440 "$ROOT/system/ascii-power" config/includes.chroot/etc/sudoers.d/ascii-power
cp "$ROOT/branding/motd" config/includes.chroot/etc/motd
cp "$ROOT/branding/issue" config/includes.chroot/etc/issue
cp "$ROOT/docs/live-welcome.txt" config/includes.chroot/etc/skel/Documents/Welcome.txt
lb build
IMAGE=live-image-amd64.hybrid.iso
[[ -s "$IMAGE" ]] || { echo 'live-build did not produce the expected ISO.' >&2; exit 1; }
install -m 644 "$IMAGE" "$ROOT/build/output/ascii-linux-amd64.iso"
cd "$ROOT/build/output"
sha256sum ascii-linux-amd64.iso > ascii-linux-amd64.iso.sha256
printf 'Built %s\n' "$ROOT/build/output/ascii-linux-amd64.iso"
