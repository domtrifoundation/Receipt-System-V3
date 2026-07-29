"""Per-fact-kind polling mechanisms (Warden §3).

Deliberately empty of re-exports. Each poller is imported by name from its own module; a
convenience surface here would make `from ...pollers import PyPIPoller` look like the supported
path when the supported path is registering one against `poller.PollerRegistry`
(`docs/PRINCIPLES.md` §1.1).

**Polling is not uniform, and that is the design** (§1, §3). A PyPI release feed, a
free-threading trove classifier and one specific GitHub issue's open/closed state are three
different questions with three different answers, and the parent deep-dive §3.2 spells out why
folding them together loses information: a release poller would never surface a blocker issue
resolving, because that fact does not live in a changelog.
"""
