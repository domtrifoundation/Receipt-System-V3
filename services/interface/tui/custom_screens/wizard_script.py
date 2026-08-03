"""Plain-language step copy for the first-run wizard, transcribed from
`docs/SETUP_WIZARD_SCRIPT.md` — that document is the source of truth; this module is the
structured form a `WizardScreen` renders it in, keyed by `WizardStepId` exactly as that
document's own note says a client should ("a client renders that script keyed by
step_id" — `services/setup/contracts.py`'s own `WizardStepPrompt` docstring).

**Scope note, stated honestly**: each step's *primary* decision (the choice that
`WizardEngine._apply_*` actually branches on) is transcribed and wired to a real
`WizardAnswer`. The deeper follow-up sub-flows several steps describe — Cloudflare's own
device-login flow (Step 3), PSP credential entry (Step 5), SMS provider credentials and
sender-name registration (Step 6) — are genuinely external, multi-step integrations of
their own; this pass wires the visible choice ("set this up now" vs. the two skip
variants) but "set this up now" is not yet a real inline credential-entry flow. Selecting
it reports that honestly (matching `menu_screen.py`'s own "not wired yet" discipline)
rather than faking a working OAuth/credential form.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.interface.contracts import MenuItemSpec  # noqa: F401  (kept for import-path parity with sibling modules)
from services.setup.contracts import WizardStepId


@dataclass(frozen=True)
class WizardChoice:
    label: str
    answer_data: dict = field(default_factory=dict)
    skipped: bool = False
    needs_followup: bool = False
    """True for a choice this pass doesn't implement inline (see module docstring) —
    selecting it still submits a real, valid `WizardAnswer` (the visible choice itself is
    real), but the screen shows a note that deeper configuration isn't available yet."""


@dataclass(frozen=True)
class WizardStepScript:
    title: str
    body: str
    choices: tuple[WizardChoice, ...]


WIZARD_SCRIPT: dict[WizardStepId, WizardStepScript] = {
    WizardStepId.WELCOME: WizardStepScript(
        title="Welcome",
        body=(
            "Welcome. Let's get this set up — it takes a few minutes, and you can change "
            "almost anything here later.\n\nHow will you be using this?"
        ),
        choices=(
            WizardChoice("Just for myself", {"use_case": "personal"}),
            WizardChoice("For my company or team", {"use_case": "team"}),
            WizardChoice("For the public — anyone can sign up", {"use_case": "public"}),
        ),
    ),
    WizardStepId.ACCOUNT: WizardStepScript(
        title="Your own account",
        body="Now let's set up your own account — you'll be the owner of this installation.\n\nHow do you want to log in?",
        choices=(
            WizardChoice("Sign in with Google", {"method": "sso"}),
            WizardChoice("Use a passkey", {"method": "passkey"}),
            WizardChoice("Get a login code by email", {"method": "email"}),
            WizardChoice("Get a login code by text message", {"method": "sms"}),
        ),
    ),
    WizardStepId.RUN_ON_STARTUP: WizardStepScript(
        title="Run automatically when your computer starts",
        body="Do you want this to start automatically when your computer turns on? You can change this anytime later in Settings.",
        choices=(
            WizardChoice("Yes, start automatically", {"enable": True}),
            WizardChoice("No, I'll start it myself", skipped=True),
        ),
    ),
    WizardStepId.TUNNEL_EXPOSURE: WizardStepScript(
        title="Making this reachable from outside your network",
        body=(
            "If you want people outside your network to reach it, we need to open a secure "
            "path to the outside internet."
        ),
        choices=(
            WizardChoice("Set this up now", needs_followup=True),
            WizardChoice("Skip — I'll only use this on my own network", skipped=True),
            WizardChoice("Skip — I'll set this up later in Settings", skipped=True),
        ),
    ),
    WizardStepId.GROUPS: WizardStepScript(
        title="Groups — if you're setting this up for a team",
        body="Do people on your team need to see each other's receipts, or should everyone's stay private?",
        choices=(
            WizardChoice("Set up a shared team space", {"choice": "shared_space", "name": "Team"}),
            WizardChoice("Keep everyone's data private, even from each other", {"choice": "private"}),
            WizardChoice("Not sure yet — I'll set this up later", skipped=True),
        ),
    ),
    WizardStepId.BILLING: WizardStepScript(
        title="Getting paid",
        body="By default, everything here is free for everyone. Do you want to set up paid plans?",
        choices=(
            WizardChoice("Set this up now", needs_followup=True),
            WizardChoice("No — everything stays free", skipped=True),
            WizardChoice("I'll decide later in Settings", skipped=True),
        ),
    ),
    WizardStepId.SMS_NOTIFICATIONS: WizardStepScript(
        title="Text message notifications",
        body="Want this to be able to text people (e.g. \"your files are ready\")?",
        choices=(
            WizardChoice("Set this up now", needs_followup=True),
            WizardChoice("No, skip this", skipped=True),
            WizardChoice("I'll set this up later in Settings", skipped=True),
        ),
    ),
    WizardStepId.RECEIPT_INGESTION: WizardStepScript(
        title="Where receipts come in from",
        body="How do you want to add receipts? Upload and camera capture are always available.",
        choices=(
            WizardChoice("Also watch a Google Drive folder", {"channel": "google_drive"}),
            WizardChoice("Just upload directly", skipped=True),
        ),
    ),
    WizardStepId.ADDRESS_CHECKING: WizardStepScript(
        title="Finding addresses on receipts",
        body="This system can double-check addresses on your receipts against real map data.",
        choices=(
            WizardChoice("Use the built-in free option", {"choice": "built_in"}),
            WizardChoice("Skip this — I don't need address checking", skipped=True),
        ),
    ),
    WizardStepId.HARDWARE_TIER: WizardStepScript(
        title="How powerful should the AI processing be?",
        body="We looked at your computer's hardware and have a recommendation.",
        choices=(
            WizardChoice("Lightweight — fastest, least resources", {"tier": "lightweight"}),
            WizardChoice("Balanced — recommended for your hardware", {"tier": "balanced"}),
            WizardChoice("Maximum accuracy — slower, best results", {"tier": "maximum"}),
            WizardChoice("Use the recommended setting", skipped=True),
        ),
    ),
    WizardStepId.TERMS_OF_SERVICE: WizardStepScript(
        title="Terms of Service and Privacy Policy",
        body="Before you finish setup, please review and accept our Terms of Service and Privacy Policy.",
        choices=(
            WizardChoice("I have read and accept both", {"accepted": True}),
        ),
    ),
    WizardStepId.FINALIZE: WizardStepScript(
        title="All set",
        body="That's everything. Setting things up now — this takes a moment.",
        choices=(WizardChoice("Continue", skipped=True),),
    ),
}

__all__ = ["WizardChoice", "WizardStepScript", "WIZARD_SCRIPT"]
