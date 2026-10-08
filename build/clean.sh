#!/bin/bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
(( EUID == 0 )) || { echo 'Run this script as root.' >&2; exit 1; }
if [[ -d "$ROOT/build/work" ]]; then
    cd "$ROOT/build/work"
    # live-build unmounts build mounts before deleting state. Fail if it cannot.
    lb clean --purge
    cd "$ROOT"
    rm -rf -- "$ROOT/build/work"
fi
# Keep release artifacts; remove them explicitly if no longer needed.
