#!/usr/bin/env bash
# Invoked inside an allocated compute job; no model/provider calls.
set -euo pipefail
: "${PVL_SOURCE:?Export the absolute path to the PVL checkout}"
test "${PVL_SOURCE:0:1}" = /
test -f "$PVL_SOURCE/scripts/check_kernel_acceptance.py"
test "$#" -eq 1
test "${1:0:1}" = /
cd "$PVL_SOURCE"
# Existing acceptance owns a fresh directory and refuses to overwrite it.
exec "${PVL_PYTHON:-python3}" -S scripts/check_kernel_acceptance.py --output "$1"
