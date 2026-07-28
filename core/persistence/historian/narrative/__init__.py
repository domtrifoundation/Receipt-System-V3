"""The narrative track's summarization layer (`v3-deepdive-29-historian.md` §5)."""

from .summarizers import SUMMARIZERS, summarize

__all__ = ["SUMMARIZERS", "summarize"]
