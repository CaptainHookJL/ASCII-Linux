#!/bin/bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ISO="$ROOT/build/output/ascii-linux-amd64.iso"
uefi=0
console=0
for option in "$@"; do
    case "$option" in
        --uefi) uefi=1 ;;
        --console) console=1 ;;
        --help|-h) echo 'Usage: test-qemu.sh [--uefi] [--console]'; exit 0 ;;
        *) echo 'Usage: test-qemu.sh [--uefi] [--console]' >&2; exit 1 ;;
    esac
done
[[ -s "$ISO" ]] || { echo "Missing ISO: $ISO" >&2; exit 1; }
command -v qemu-system-x86_64 >/dev/null || { echo 'Install qemu-system-x86.' >&2; exit 1; }
args=(-m 2048 -cdrom "$ISO" -boot d -nic user,model=virtio-net-pci)
if [[ -r /dev/kvm && -w /dev/kvm ]]; then args+=(-accel kvm); else args+=(-accel tcg); fi
if (( uefi )); then
    CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
    VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
    [[ -r "$CODE" && -r "$VARS" ]] || { echo 'Install ovmf for UEFI testing.' >&2; exit 1; }
    mkdir -p "$ROOT/build/output"
    cp "$VARS" "$ROOT/build/output/OVMF_VARS.fd"
    args+=(-drive "if=pflash,format=raw,readonly=on,file=$CODE"
           -drive "if=pflash,format=raw,file=$ROOT/build/output/OVMF_VARS.fd")
fi
if (( console )); then
    echo 'Console testing: append ascii.console to the boot menu kernel command line.' >&2
    args+=(-display curses)
else
    # The default desktop uses X11, which needs QEMU's graphical display.
    args+=(-display gtk)
fi
exec qemu-system-x86_64 "${args[@]}"
