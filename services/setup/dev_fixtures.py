"""`setup-dev`'s own default-environment seeding (deep-dive §4.1).

§4.1 asks for three things: "a pre-populated `.env`/config with sensible local-dev values
already filled in... sample/fixture receipt images and a small seeded SQLite dataset... and
stub/mock provider configurations." **This module deliberately implements only the first.**

**Why the other two are not built here, stated rather than silently dropped:**

- **No synthetic receipt data, ever — not images, not database rows.** This is a standing,
  explicit project rule (`docs/HANDOFF_TO_LOCAL.md`, and every session's own carried-forward
  instructions): "Never generate or synthesize fake receipts, even to 'just test the pipeline
  runs.'" Real fixtures are gitignored and sourced from real scans a developer supplies
  (`tests/fixtures/real_receipts/`), never fabricated by code. §4.1's own sketch predates that
  rule being stated this explicitly, and the rule wins — this module will not create receipt
  images or a seeded receipt-shaped database, synthetic or otherwise. What it does instead:
  `seed_dev_environment` reports whether `tests/fixtures/real_receipts/` already has content a
  developer supplied themselves, so a caller can tell "no fixtures yet" from "fixtures exist,"
  without ever populating that directory itself.
- **Stub/mock provider implementations belong to the API that owns the real provider, not to
  Setup.** `docs/PRINCIPLES.md` §1.2/§1.3: every pluggable capability is that API's own Provider
  Registry — a mock `GeoAddressProvider` is Geo/Address's own package to build and register, the
  same way every other provider in this project is. Setup reaching into another API's package to
  add a provider implementation would be exactly the kind of boundary violation
  `docs/PRINCIPLES.md` §1.1 exists to prevent. What this module does instead: it leaves any
  provider's own credentials unset in the seeded config, which is already every implemented
  provider's own designed degrade-to-unavailable path (§4.4) — "stubbed" in the sense of "left
  absent, so the real graceful-degradation code path runs," not a fabricated fake response.
"""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import AgentTokenSeedGateway, DevFixturesReport

__all__ = [
    "DEV_AGENT_TOKEN_FILENAME",
    "DEV_DEFAULT_CONFIG",
    "REAL_RECEIPTS_FIXTURE_DIRNAME",
    "real_receipts_fixture_status",
    "seed_dev_environment",
]

#: Relative to `<install_root>/config/` — a plaintext file, deliberately: the audience for
#: this file is an unattended AI agent operating `setup-dev` with no human present to be
#: shown a one-time secret through any UI (`token_lifecycle.py`'s usual "shown once, not
#: recoverable" flow assumes a human reading a screen). The file itself is the "shown
#: once" moment for this specific, dev-only, human-authorized-by-running-setup-dev path.
DEV_AGENT_TOKEN_FILENAME = "dev_agent_token.txt"

#: Structurally complete so nothing crashes on a missing key (§4.1's own stated goal) — every
#: value here is either a genuinely free/local default or deliberately empty, never a real or
#: even plausible-looking credential. Every key used here is one this repo's own deep-dives
#: already establish (OCR §6, Geo/Address's own config surface) rather than invented for this
#: module.
DEV_DEFAULT_CONFIG: dict = {
    "dev_mode": True,
    "ocr": {
        # tesseract + rapidocr: both real, pip/system-installable, zero cost, zero credentials —
        # a contributor can exercise OCR immediately without configuring anything paid.
        "engines_enabled": ["tesseract", "rapidocr"],
        "tesseract": {"binary_path": "tesseract", "lang": "eng", "psm": 6, "omp_thread_limit": 1},
        "cloud_engines": {
            "google_vision": {"api_key": "", "max_calls_per_run": 0},
            "azure_document_intelligence": {"api_key": "", "endpoint": "", "max_calls_per_run": 0},
            "aws_textract": {"access_key_id": "", "secret_access_key": "", "region": "", "max_calls_per_run": 0},
        },
    },
    "geo_address": {
        # No provider credentials seeded — every provider in core/geo_address/providers/ is a
        # paid or self-hosted-infra option; left absent so that API's own already-designed
        # degrade-to-unavailable path runs, exactly as it would for any operator who has not
        # configured one yet (docs/PRINCIPLES.md §4.4). Not this module's package to add a mock
        # provider implementation to.
        "providers_enabled": [],
    },
    "billing": {"psp": {"provider": "", "credentials": {}}},
    "notifications": {"sms": {"providers_enabled": []}},
    "setup": {"startup_registrar": "auto"},
}

#: Relative to the top-level install directory's own conventional test-fixture location —
#: matches `docs/HANDOFF_TO_LOCAL.md`'s own reference path.
REAL_RECEIPTS_FIXTURE_DIRNAME = Path("tests") / "fixtures" / "real_receipts"


def real_receipts_fixture_status(clone_dir: Path) -> tuple[bool, int]:
    """Whether a developer has already supplied real receipt fixtures, and how many files.

    Read-only — this function only reports; it never creates, downloads, or synthesizes
    anything into this directory. `(False, 0)` for "not present yet" is a completely normal,
    expected answer on a fresh developer checkout, not a problem to fix.
    """
    fixture_dir = clone_dir / REAL_RECEIPTS_FIXTURE_DIRNAME
    if not fixture_dir.is_dir():
        return False, 0
    count = sum(1 for p in fixture_dir.rglob("*") if p.is_file())
    return count > 0, count


async def seed_dev_environment(
    install_root: Path, *, overwrite: bool = False, agent_token_gateway: AgentTokenSeedGateway | None = None,
) -> DevFixturesReport:
    """Writes `DEV_DEFAULT_CONFIG` to `<install_root>/config/dev_defaults.json`.

    Idempotent by default: an existing file is left alone (`written=False`) unless
    `overwrite=True` — a contributor's own edits to their local dev config must never be
    silently clobbered by a re-run of setup-dev.

    `agent_token_gateway`, if given, additionally issues one dev-scoped Agent Control
    token and writes its plaintext to `<install_root>/config/dev_agent_token.txt` — the
    real mechanism behind "an AI running `setup-dev` unattended gets MCP access without a
    human present to hand it a token through the UI." `None` (the default) skips this
    entirely — every non-`setup-dev` install path, and any `setup-dev` run that doesn't
    wire this gateway in, seeds no token at all, matching `docs/PRINCIPLES.md` §4.4's
    degrade-to-absent posture for an unsupplied collaborator.
    """
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / "dev_defaults.json"

    written = False
    if not target.exists() or overwrite:
        target.write_text(json.dumps(DEV_DEFAULT_CONFIG, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written = True

    agent_token_path: Path | None = None
    if agent_token_gateway is not None:
        token_path = config_dir / DEV_AGENT_TOKEN_FILENAME
        if not token_path.exists() or overwrite:
            plaintext = await agent_token_gateway.issue_dev_token("setup-dev unattended AI operator")
            token_path.write_text(plaintext + "\n", encoding="utf-8")
        agent_token_path = token_path

    return DevFixturesReport(config_path=target, written=written, agent_token_path=agent_token_path)
