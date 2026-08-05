"""Which services are actual sleep candidates (`v3-deepdive-38-supervisor.md` §6.2) —
"not a uniform policy... pretending otherwise would be a real correctness risk."

The table below is the deep-dive's own §6.2 list, verbatim, not a guess at what "seems
safe to sleep":

- `NEVER` — Auth (session validation is the hottest path in the entire system), Gateway
  (the fixed, always-reachable edge), Health (has to keep monitoring everything *else*),
  Persistence (near-universal dependency), Logs (things need to log continuously,
  including the wake events of everything else), Watchdog (can't supervise liveness
  while asleep).
- `SCHEDULED_ONLY` — Ingestion (a webhook subscription plus a daily fallback-poll timer;
  genuinely idle the overwhelming majority of the time).
- `IDLE_TIMEOUT` — OCR, Preprocessing, Inference (resident only while a run is actually
  in progress).

Every other registered service defaults to `NEVER` — the safe default (`docs/PRINCIPLES.md`
§4.2's own fail-closed posture, applied here: an unclassified service is assumed to need
to always be responsive rather than guessed as safe to sleep).
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from ..contracts import SleepPolicy

__all__ = ["DEFAULT_IDLE_TIMEOUT_MINUTES", "SLEEP_POLICIES", "policy_for"]

#: §6.2's own explicit table, `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1 — a module-level
#: constant lookup table read from every sleep-eligibility check, never written.
SLEEP_POLICIES: FrozenDict = FrozenDict(
    {
        "auth": SleepPolicy.NEVER,
        "gateway": SleepPolicy.NEVER,
        "health": SleepPolicy.NEVER,
        "persistence": SleepPolicy.NEVER,
        "logs": SleepPolicy.NEVER,
        "watchdog": SleepPolicy.NEVER,
        "ingestion": SleepPolicy.SCHEDULED_ONLY,
        "ocr": SleepPolicy.IDLE_TIMEOUT,
        "preprocessing": SleepPolicy.IDLE_TIMEOUT,
        "inference": SleepPolicy.IDLE_TIMEOUT,
    }
)

#: §11's resolved default — "real usage-pattern data can tune it later; the mechanism is
#: what matters for shipping."
DEFAULT_IDLE_TIMEOUT_MINUTES: int = 30


def policy_for(service_name: str) -> SleepPolicy:
    """A service absent from `SLEEP_POLICIES` defaults to `NEVER` — the fail-closed
    posture the module docstring states: an unclassified service is assumed to need to
    always be responsive, never guessed as safe to sleep."""
    return SLEEP_POLICIES.get(service_name, SleepPolicy.NEVER)
