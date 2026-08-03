#!/usr/bin/env bash
# The normal, immersive first-run installer (v3-deepdive-11-setup-api.md §4.1).
#
# `docs/SETUP_WIZARD_SCRIPT.md`'s own Step 0 welcome copy belongs to the *wizard*
# (services/setup/wizard.py, reached after this script hands off), not here — this script's own
# job ends at "get a working clone on disk and call Setup API's finalize routine." Real logic
# lives in common.sh, shared with setup-dev.sh so the two cannot drift (docs/PRINCIPLES.md §1.5).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

INSTALL_ROOT="${1:-$(pwd)/resibo}"

do_bootstrap "false" "$INSTALL_ROOT"
