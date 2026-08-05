"""Pure, in-process scanning steps — no provider, no network, no subprocess.

Each module here answers one question about bytes already in memory: `magic_bytes` what the
file really is, `polyglot_detection` whether it is honestly only one thing, `bomb_check`
whether a zip container's own metadata is safe to extract at all. `pipeline.py` is the only
caller that composes them into a verdict; nothing here decides accept/reject on its own.
"""
