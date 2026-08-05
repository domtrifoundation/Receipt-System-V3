"""Outbound delivery channels — the `OutboundChannel` Provider Registry (§4).

Deliberately empty of re-exports, matching `core/logs/__init__.py` and `core/audit/__init__.py`:
`base.py` (the Protocol and registry), `email_channel.py`, and `sms_channel.py` are each
imported directly by whatever composes them (`dispatch.py`'s `default_channel_registry`), never
through this package's own namespace.
"""
