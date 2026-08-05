"""Writing surfaced changes into `docs/CHANGELOG.md` (§4, §9).

§9 resolved the format as Keep a Changelog and the location as `docs/CHANGELOG.md`, explicitly
choosing "the standard, well-established convention rather than a bespoke format". This module
is the only thing that writes it.

Three properties, each of which exists because of a specific way this could go wrong:

* **Entries land under `## [Unreleased]`.** A tracked fact changing is not a release of this
  program, and inventing a version heading for it would make the changelog claim releases that
  never happened.
* **The write is idempotent per line.** Polling runs daily and a fact can be observed as
  changed once but written twice if a pass is retried; a duplicate line under the same heading
  is noise that makes the file less readable exactly as it grows.
* **A failed write never loses the observation.** The tracked state is updated by the poller
  before this is called, and `ChangelogUnwritable` is returned rather than raised into that
  path — a read-only filesystem must not cost us the knowledge that a blocker finally closed.

`ChangelogWriter` takes a root path rather than reaching for the repo root itself, so a test
writes into `tmp_path` and production writes into the real tree through the same code.
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence

from ..contracts import CHANGELOG_PATH, ChangelogEntry
from ..errors import ChangelogUnwritable
from ..metrics import TelemetreesMetricsCollector

UNRELEASED_HEADING = "## [Unreleased]"

_HEADER = """# Changelog

All notable changes to this project are documented here, in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

Entries under `[Unreleased]` below the dependency headings are appended automatically by
Dependencies Warden (`core/telemetrees/dependencies_warden/`) whenever a tracked fact changes
state — see `docs/apis/v3-deepdive-28-telemetrees-api.md` §4 and §9. Edit them by hand only to
correct wording; the next poll will not re-add a line that is already present.

"""


class ChangelogWriter:
    """Appends `ChangelogEntry` lines to `docs/CHANGELOG.md` under `[Unreleased]`."""

    def __init__(
        self,
        root: pathlib.Path | str,
        *,
        relative_path: str = CHANGELOG_PATH,
        metrics: TelemetreesMetricsCollector | None = None,
    ) -> None:
        self._path = pathlib.Path(root) / relative_path
        self._metrics = metrics or TelemetreesMetricsCollector()

    @property
    def path(self) -> pathlib.Path:
        return self._path

    def append(self, entries: Sequence[ChangelogEntry]) -> tuple[ChangelogEntry, ...]:
        """Write the entries that are not already present. Returns what was actually written.

        Returning the written subset rather than a bare count is what lets a caller report "3
        changes, 1 already recorded" honestly instead of implying it wrote more than it did.
        """
        if not entries:
            return ()

        try:
            existing = self._read()
        except OSError as exc:
            raise ChangelogUnwritable(f"could not read {self._path}: {exc}") from exc

        lines = existing.splitlines()
        written: list[ChangelogEntry] = []
        for entry in entries:
            rendered = self._render(entry)
            if rendered in lines:
                continue
            lines = self._insert(lines, entry.category, rendered)
            written.append(entry)

        if not written:
            return ()

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            raise ChangelogUnwritable(f"could not write {self._path}: {exc}") from exc

        self._metrics.increment("changelog_entries_written", len(written))
        return tuple(written)

    def _read(self) -> str:
        if not self._path.exists():
            return _HEADER + UNRELEASED_HEADING + "\n"
        return self._path.read_text(encoding="utf-8")

    @staticmethod
    def _render(entry: ChangelogEntry) -> str:
        return f"- {entry.text}"

    def _insert(self, lines: list[str], category: str, rendered: str) -> list[str]:
        """Place a line under `### <category>` inside `[Unreleased]`, creating either if absent.

        Written as a small parser over the real file rather than an append-to-end, because a
        changelog whose entries land under whatever heading happened to be last is not actually
        in Keep a Changelog format — it just looks like it until someone reads it.
        """
        out = list(lines)
        if UNRELEASED_HEADING not in out:
            out.extend(["", UNRELEASED_HEADING])

        unreleased_at = out.index(UNRELEASED_HEADING)
        next_release_at = len(out)
        for index in range(unreleased_at + 1, len(out)):
            if out[index].startswith("## "):
                next_release_at = index
                break

        heading = f"### {category}"
        for index in range(unreleased_at + 1, next_release_at):
            if out[index].strip() == heading:
                insert_at = index + 1
                while insert_at < next_release_at and out[insert_at].startswith("- "):
                    insert_at += 1
                out.insert(insert_at, rendered)
                return out

        out.insert(next_release_at, "")
        out.insert(next_release_at + 1, heading)
        out.insert(next_release_at + 2, rendered)
        return out


__all__ = ["UNRELEASED_HEADING", "ChangelogWriter"]
