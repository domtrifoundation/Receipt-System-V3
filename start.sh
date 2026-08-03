#!/usr/bin/env bash
# Manual runtime launcher. Hands off to Supervisor's own real fleet-boot entrypoint
# (supervisor/__main__.py), run from Supervisor's own top-level install
# (supervisor/install.py's install_supervisor() — this directory's supervisor/ folder is
# a real, permanent copy, never inside a release clone, per docs/PRINCIPLES.md §1.6).
# Supervisor's own venv (supervisor/.venv/) is separate from every service's — it only
# needs grpc, never a clone's full dependency set.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY="$(dirname "$0")/supervisor/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "Supervisor's own venv is missing at supervisor/.venv/ — run setup first." >&2
    exit 1
fi

exec "$PY" -m supervisor "$@"
