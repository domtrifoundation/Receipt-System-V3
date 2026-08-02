#!/usr/bin/env bash
# Manual runtime launcher — a genuinely different concern from noxfile.py's automated
# per-marker test validation. This is for actually running the program under a chosen
# interpreter for hands-on local testing, not for CI or the fast per-API test checkpoint.
#
# In its final, shipped form this script hands off to Supervisor's own Boot Sequence
# (docs/apis/v3-deepdive-38-supervisor.md §3.2, docs/PROCESS_TOPOLOGY.md §6), which doesn't
# exist as real code yet — Supervisor is still Phase 1 scaffolding. What DOES exist and
# genuinely runs today is Agent Control's own gRPC service (core/agent_control/service.py,
# docs/PHASE_1_KICKOFF.md §1.5's one implemented exception), so that's what this launches
# for now. Replace the exec line below with a real Supervisor invocation once Supervisor
# actually has one — don't read this as "the launcher only ever starts Agent Control," read
# it as "the launcher starts whatever the one real, runnable thing is at the time."
#
# Also worth being explicit about, per docs/MAINTENANCE.md §5: a raw `git clone` of this
# repo was never meant to be a complete, installed instance — the real installer builds the
# top-level directory structure, config, and first-run wizard this script's eventual
# Supervisor handoff will expect. Running this script directly from a dev checkout is for
# exercising real, already-implemented code paths during development, not a substitute for
# an actual install.
#
# PYTHON_BIN — the interpreter this launches under. Unset, in the wild, on a real end-user
# install, always: those installs get their interpreter from Setup API's own environment
# detection and never touch this variable at all. Set it here, in a dev checkout, to run the
# one real thing under something other than the pinned default — e.g. to hands-on test
# against Python 3.15 ahead of a Forward-Compatibility Pattern review (docs/PRINCIPLES.md
# §3.3.1), separately from and in addition to noxfile.py's automated `forward_compat` gate.
#
#   ./start.sh                          # default pinned interpreter (currently 3.14)
#   PYTHON_BIN=python3.15 ./start.sh    # the whole system running under 3.15
#
# On Windows, there is usually no bare `python3.15` command on PATH even when 3.15 is
# genuinely installed — the `py` launcher is what resolves a specific version there instead.
# Quote it as one variable since it's two words: PYTHON_BIN="py -3.15" ./start.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-python}"

exec $PYTHON_BIN -m core.agent_control.service "$@"
