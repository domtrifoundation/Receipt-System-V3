#!/usr/bin/env bash
# The bare-bones developer installer (v3-deepdive-11-setup-api.md §4.1).
#
# Differs from setup.sh only in what it passes to do_bootstrap (common.sh) — the confirmation
# prompt this variant needs lives inside do_bootstrap itself, gated on the dev_mode argument,
# so the two scripts share one real implementation rather than each carrying its own copy of the
# clone/channel-resolution/Keymaster logic (docs/PRINCIPLES.md §1.5).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Same fix as setup.sh's own: this script's own directory IS the install root.
INSTALL_ROOT="${1:-$(pwd)}"

do_bootstrap "true" "$INSTALL_ROOT"
