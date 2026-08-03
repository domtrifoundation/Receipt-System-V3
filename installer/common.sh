#!/usr/bin/env bash
# Shared bootstrap logic for setup.sh and setup-dev.sh (v3-deepdive-11-setup-api.md §4).
#
# This file, and the two entry points that source it, are the "small amount of real logic" §4
# says the bootstrap script has to carry before any Python code exists on disk at all — the
# license-key-to-token exchange happens before the first `git clone`, so it cannot depend on
# anything this project's own codebase provides (`common/`, this repo's own httpx-based
# services/update/keymaster_client.py included). Plain POSIX shell plus `curl`, nothing else.
#
# Kept as its own file, sourced by both entry points, rather than duplicated into each — the
# same "one shared implementation, not two copies that can drift" discipline
# `docs/PRINCIPLES.md` §1.5 applies everywhere else in this project, applied here to shell.
#
# The wire contract for the Keymaster call matches services/update/keymaster_client.py's own
# documented shape exactly (that module's docstring is the canonical spec; this is the
# necessarily-duplicated pre-Python implementation of the same contract):
#
#   POST {KEYMASTER_BASE_URL}/v1/clone-tokens
#   {"license_key": "...", "instance_id": "..."}
#   200 -> {"token": "...", "expires_at": "..."}
#   any other status -> a single generic rejection (never inspected further here either,
#   for the same "never leak why a key failed" reason that module's own docstring states)

set -euo pipefail

REPO_URL="https://github.com/domtrifoundation/Receipt-System-V3"
REPO_CLONE_URL="${REPO_URL}.git"

# Empty by default: Keymaster is a completely separate, closed system this repo does not (and
# never will) contain (v3-plan-02-architecture.md) — there is genuinely no default URL to point
# at yet. An empty value means "skip the license-key exchange, clone unauthenticated," which is
# also the only thing that can work today, since this repo is still public
# (docs/MAINTENANCE.md's own channel-tag section — gating has nothing to intercept against a
# public repo). Override via the environment, never hardcode a real one here.
KEYMASTER_BASE_URL="${KEYMASTER_BASE_URL:-}"

bootstrap_log() {
    # Always stderr, never stdout — several functions in this file (prompt_channel,
    # prompt_license_key, keymaster_get_clone_token) are called via command substitution to
    # capture a return value (`channel=$(prompt_channel)`), which captures EVERYTHING that
    # function writes to stdout. A log line on stdout there would silently concatenate into the
    # captured value — a real bug this script hit during its own live testing (a blank license
    # key came back polluted with this function's own log text) before this fix. Status output
    # is not a return value; it must never share stdout with one.
    printf '%s\n' "$1" >&2
}

bootstrap_die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

# --- channel resolution -----------------------------------------------------------------------

# Resolves a channel name to a real git ref, checking existence against the actual remote rather
# than assuming — none of ltsc/stable/beta/alpha exist yet (this project is still pre-x03.00.00,
# confirmed via `git tag -l` returning nothing as of this script's own writing), so an honest
# bootstrap script has to handle "the channel you picked has no release yet" as a real, expected
# case right now, not a hypothetical to handle someday.
#
# Echoes the resolved ref on success; returns non-zero and prints nothing on a genuine failure
# to resolve (caller decides whether to fall back).
resolve_channel_ref() {
    local channel="$1"
    case "$channel" in
        stable|beta|alpha)
            if git ls-remote --exit-code --tags "$REPO_CLONE_URL" "refs/tags/${channel}" >/dev/null 2>&1; then
                echo "$channel"
                return 0
            fi
            return 1
            ;;
        ltsc)
            # The first ltsc/* branch found, since a specific codename isn't chosen here —
            # LTSC branches are named ltsc/<codename> (docs/MAINTENANCE.md), plural over time.
            local branch
            branch=$(git ls-remote --heads "$REPO_CLONE_URL" 'refs/heads/ltsc/*' 2>/dev/null \
                | head -n1 | sed 's#.*refs/heads/##')
            if [ -n "$branch" ]; then
                echo "$branch"
                return 0
            fi
            return 1
            ;;
        latest_commit)
            echo "main"
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

prompt_channel() {
    bootstrap_log ""
    bootstrap_log "Which channel do you want?"
    bootstrap_log "  [1] Stable (recommended)"
    bootstrap_log "  [2] Beta"
    bootstrap_log "  [3] Alpha"
    bootstrap_log "  [4] LTSC (long-term support)"
    bootstrap_log "  [5] Latest development commit"
    printf 'Choice [1]: ' >&2
    read -r choice
    case "${choice:-1}" in
        1) echo "stable" ;;
        2) echo "beta" ;;
        3) echo "alpha" ;;
        4) echo "ltsc" ;;
        5) echo "latest_commit" ;;
        *) echo "stable" ;;
    esac
}

# --- Keymaster (self-hosted licensing only — irrelevant to DOMTRI's own hosted service) -------

prompt_license_key() {
    if [ -z "$KEYMASTER_BASE_URL" ]; then
        bootstrap_log ""
        bootstrap_log "Licensing is not yet configured for this pre-release build — skipping the"
        bootstrap_log "license-key step and cloning without one."
        echo ""
        return 0
    fi
    printf 'License key (leave blank to skip): ' >&2
    read -r key
    echo "$key"
}

# Prints a scoped clone token on success; prints nothing on any failure (network, rejection, no
# key) — mirrors services/update/keymaster_client.py's own KeymasterResult.ok being the only
# thing a caller branches on, never a differentiated reason (§4's "never leak why").
keymaster_get_clone_token() {
    local license_key="$1"
    local instance_id="$2"

    if [ -z "$license_key" ] || [ -z "$KEYMASTER_BASE_URL" ]; then
        return 0
    fi

    local body
    body=$(curl -fsS -m 10 -X POST "${KEYMASTER_BASE_URL}/v1/clone-tokens" \
        -H 'Content-Type: application/json' \
        -d "{\"license_key\":\"${license_key}\",\"instance_id\":\"${instance_id}\"}" 2>/dev/null) || return 0

    # No JSON parser available before Python exists on disk — a minimal, deliberately narrow
    # extraction, not a general-purpose parser. Real field validation happens the moment Python
    # is reachable (services/update/keymaster_client.py's own real JSON parsing).
    printf '%s' "$body" | grep -o '"token"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/'
}

# --- interpreter selection ---------------------------------------------------------------------

# Picks a real, working interpreter for venv provisioning — confirmed the hard way, not assumed:
# a bare `PYTHON_BIN=python` default silently hung on this project's own already-documented
# Day-0 gap (docs/MAINTENANCE.md §8.1 — grpcio has no prebuilt wheel for 3.15, and building it
# from source has already failed outright in this project's own environment). Every one of the
# ~30 service venvs this script provisions needs grpcio, so "just avoid grpcio" — the fix
# noxfile.py's own narrow forward_compat dependency set gets away with — is not available here.
#
# start.sh's own header comment already states the real intent: "default pinned interpreter
# (currently 3.14)". Nothing yet actually enforces that pin on a fresh machine (Setup API's own
# hardware/environment detection does not manage interpreter installation) — this function is a
# best-effort step toward it, preferring a real 3.14 if one is discoverable, before falling back
# to whatever `python`/`python3` happens to resolve to. `PYTHON_BIN` set explicitly always wins
# and skips this probing entirely.
# Populates the global array PYTHON_CMD (never a scalar) — confirmed the hard way why a scalar
# does not work here: on Windows there is typically no literal `python3.14` binary on PATH, only
# the `py` launcher's own multi-word invocation (`py -3.14`), and a bash *scalar* holding
# "py -3.14" passed as `"$python_bin" -m ...` is treated as one literal, nonexistent command
# name rather than a command plus an argument — the same class of bug this function exists to
# avoid, just one layer further in. An array is what lets `"${PYTHON_CMD[@]}" -m ...` expand
# correctly either way, whether PYTHON_CMD is one word or two.
#
# Also confirmed the hard way, the reason this function exists at all: a bare
# `PYTHON_BIN=python` default silently hung on this project's own already-documented Day-0 gap
# (docs/MAINTENANCE.md §8.1 — grpcio has no prebuilt wheel for 3.15, and building it from source
# has already failed outright in this project's own environment). Every one of the ~30 service
# venvs this script provisions needs grpcio, so this prefers a real 3.14 before falling back —
# `start.sh`'s own header comment already states the real intent ("default pinned interpreter
# (currently 3.14)"); nothing yet actually enforces that pin on a fresh machine.
detect_python_bin() {
    if [ -n "${PYTHON_BIN:-}" ]; then
        # shellcheck disable=SC2206 # deliberate word-splitting: an operator-supplied override
        # may legitimately be multi-word ("py -3.14"), same as PYTHON_BIN's own documented
        # shape in start.sh's header comment.
        PYTHON_CMD=($PYTHON_BIN)
        return 0
    fi
    if command -v python3.14 >/dev/null 2>&1; then
        PYTHON_CMD=("python3.14")
        return 0
    fi
    if command -v py >/dev/null 2>&1 && py -3.14 --version >/dev/null 2>&1; then
        PYTHON_CMD=("py" "-3.14")
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD=("python3")
        return 0
    fi
    PYTHON_CMD=("python")
}

# --- clone + handoff --------------------------------------------------------------------------

# A random instance ID, generated once on first run — deliberately not a hardware fingerprint
# (v3-plan-02-architecture.md: "hardware changes are legitimate, and a fingerprint-based lockout
# risks exactly the false-positive customer lockout already ruled unacceptable").
generate_instance_id() {
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen
    else
        # A portable fallback wherever uuidgen genuinely isn't available — real randomness from
        # /dev/urandom, not a weaker substitute.
        od -An -tx1 -N16 /dev/urandom | tr -d ' \n'
    fi
}

do_bootstrap() {
    local dev_mode="$1"       # "true" | "false"
    local install_root="$2"

    if [ "$dev_mode" = "true" ]; then
        bootstrap_log "This installs the full development environment — documentation, test"
        bootstrap_log "suite, and CI scaffolding. If you just want to run the program, close"
        bootstrap_log "this and run setup.sh instead."
        printf 'Continue? [y/N]: '
        read -r confirm
        case "${confirm:-}" in
            y|Y|yes|YES) ;;
            *) bootstrap_log "Cancelled."; exit 0 ;;
        esac
    fi

    local ref
    if [ -n "${REF_OVERRIDE:-}" ]; then
        # A real, standing escape hatch, not just a today-only test knob: bootstrapping
        # against a specific branch or PR ref (rather than a channel) is a genuine, recurring
        # need for verifying an unreleased change end to end before it ever reaches a real
        # channel tag. Skips the channel prompt entirely rather than prompting and then
        # overriding the answer, so a REF_OVERRIDE run is never ambiguous about what it did.
        ref="$REF_OVERRIDE"
        bootstrap_log ""
        bootstrap_log "REF_OVERRIDE set — bootstrapping ${ref} directly, skipping channel selection."
    else
        local channel
        channel=$(prompt_channel)
        if ! ref=$(resolve_channel_ref "$channel"); then
            bootstrap_log ""
            bootstrap_log "The ${channel} channel doesn't have a release yet — this project is"
            bootstrap_log "still in pre-release development. Falling back to the latest"
            bootstrap_log "development commit instead."
            ref="main"
        fi
    fi

    local instance_id license_key clone_token
    instance_id=$(generate_instance_id)
    license_key=$(prompt_license_key)
    clone_token=$(keymaster_get_clone_token "$license_key" "$instance_id")

    mkdir -p "${install_root}/releases"
    local tmp_clone_dir="${install_root}/releases/.bootstrap-clone-$$"

    bootstrap_log ""
    bootstrap_log "Cloning ${ref}..."
    if [ -n "$clone_token" ]; then
        git clone --branch "$ref" --depth 1 \
            "https://x-access-token:${clone_token}@github.com/domtrifoundation/Receipt-System-V3.git" \
            "$tmp_clone_dir" \
            || bootstrap_die "clone failed"
    else
        git clone --branch "$ref" --depth 1 "$REPO_CLONE_URL" "$tmp_clone_dir" \
            || bootstrap_die "clone failed — this repo is currently public, so an unauthenticated clone should work; if it didn't, check your network connection and try again"
    fi

    # Rename to <version>_<commit-hash>, the shape common/version.py's own resolve_commit_hash()
    # expects (docs/MAINTENANCE.md §2) — read directly out of the freshly cloned file rather
    # than guessed, since the version this script is bootstrapping is whatever that ref actually
    # contains, not whatever this installer script happened to ship with.
    local version commit_hash final_dir
    version=$(grep -o 'PROGRAM_VERSION = "[^"]*"' "${tmp_clone_dir}/common/version.py" | sed 's/.*"\(.*\)"/\1/')
    commit_hash=$(git -C "$tmp_clone_dir" rev-parse --short HEAD)
    final_dir="${install_root}/releases/${version}_${commit_hash}"
    mv "$tmp_clone_dir" "$final_dir"

    bootstrap_log "Cloned into ${final_dir}"
    bootstrap_log "Handing off to Setup API's own finalize routine..."

    local -a PYTHON_CMD
    detect_python_bin   # a plain call, not $(...) — PYTHON_CMD is an array and would not
    #                      survive being set inside a command-substitution subshell.
    bootstrap_log "Using interpreter: ${PYTHON_CMD[*]}"
    local finalize_args=("$final_dir")
    if [ "$dev_mode" = "true" ]; then
        finalize_args+=(--dev-mode)
    fi
    ( cd "$final_dir" && PYTHONPATH="$final_dir" "${PYTHON_CMD[@]}" -m services.setup.bootstrap "${finalize_args[@]}" ) \
        || bootstrap_die "finalize failed — see the output above"

    bootstrap_log ""
    bootstrap_log "Done! You're ready to go."
    bootstrap_log "Run: ${install_root}/start.sh"
}
