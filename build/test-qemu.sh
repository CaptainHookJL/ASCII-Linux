#!/bin/bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ISO="$ROOT/build/output/ascii-linux-amd64.iso"
[[ -s "$ISO" ]] || { echo "Missing ISO: $ISO" >&2; exit 1; }
command -v qemu-system-x86_64 >/dev/null || { echo 'Install qemu-system-x86.' >&2; exit 1; }
args=(-m 2048 -cdrom "$ISO" -boot d -nic user,model=virtio-net-pci)
if [[ -r /dev/kvm && -w /dev/kvm ]]; then args+=(-accel kvm); else args+=(-accel tcg); fi
if [[ ${1:-} == --uefi ]]; then
    CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
    VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
    [[ -r "$CODE" && -r "$VARS" ]] || { echo 'Install ovmf for UEFI testing.' >&2; exit 1; }
    mkdir -p "$ROOT/build/output"
    cp "$VARS" "$ROOT/build/output/OVMF_VARS.fd"
    args+=(-drive "if=pflash,format=raw,readonly=on,file=$CODE"
           -drive "if=pflash,format=raw,file=$ROOT/build/output/OVMF_VARS.fd")
elif [[ -n ${1:-} ]]; then
    echo 'Usage: test-qemu.sh [--uefi]' >&2; exit 1
fi
# curses display supports terminal-only builders; stop through the VM power menu.
exec qemu-system-x86_64 "${args[@]}" -display curses
