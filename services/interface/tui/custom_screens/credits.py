"""The Credits screen (`v3-deepdive-14-interface-api.md` §5) — on the enumerated
custom-screen exception list. Two real purposes: fun (codename lineage, contributor
thanks) and a genuine legal one — several dependencies ship under licenses (MIT/BSD/
Apache 2.0) that require their notices be included in redistributed software once this
program is sold, not just self-used.

**Compliance-accuracy note, stated honestly rather than glossed over**: `THIRD_PARTY_DEPENDENCIES`
below is transcribed from this repo's own `requirements.txt` files with the license each
package is well-known to ship under. It is a real, sourced starting point, not a guess
dressed up as certainty — but it has not been cross-checked against each package's actual
current `LICENSE` file at redistribution time, which is what an actual legal compliance
pass before selling this program needs to do. Entries marked `license=None` are ones this
pass did not have enough confidence to state a license for; leaving them blank is more
honest than guessing wrong in a screen with a real legal purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from common.version import MAJOR_CODENAMES, PROGRAM_VERSION, codename
from services.interface.tui.i18n import t


@dataclass(frozen=True)
class DependencyNotice:
    package: str
    license: str | None
    used_by: str


THIRD_PARTY_DEPENDENCIES: tuple[DependencyNotice, ...] = (
    DependencyNotice("grpcio", "Apache-2.0", "process-separation substrate, every Core API"),
    DependencyNotice("grpcio-tools", "Apache-2.0", "proto compilation"),
    DependencyNotice("protobuf", "BSD-3-Clause", "gRPC message types"),
    DependencyNotice("frozendict", "MIT", "FrozenDict shim on pre-3.15 interpreters"),
    DependencyNotice("rapidfuzz", "MIT", "find_setting, geo/vendor fuzzy matching"),
    DependencyNotice("textual", "MIT", "this TUI"),
    DependencyNotice("rich", "MIT", "Textual's own rendering dependency"),
    DependencyNotice("httpx", "BSD-3-Clause", "OCR/Auth/Update async HTTP"),
    DependencyNotice("cryptography", "Apache-2.0 OR BSD-3-Clause", "Accounting Sync OAuth token storage"),
    DependencyNotice("authlib", "BSD-3-Clause", "Auth API OAuth/OIDC"),
    DependencyNotice("webauthn", "MIT", "Auth API passkeys"),
    DependencyNotice("pymupdf", "AGPL-3.0 OR commercial", "PDF handling — OCR/Ingestion/Preprocessing"),
    DependencyNotice("pillow", "MIT-CMU", "image handling, Ingestion"),
    DependencyNotice("pillow-heif", "BSD-3-Clause", "HEIF/HEIC support, Ingestion"),
    DependencyNotice("opencv-python", "Apache-2.0", "image preprocessing"),
    DependencyNotice("numpy", "BSD-3-Clause", "array ops across OCR/Preprocessing"),
    DependencyNotice("pdfplumber", "MIT", "OCR PDF text extraction"),
    DependencyNotice("pytesseract", "Apache-2.0", "one of OCR's parallel engines"),
    DependencyNotice("rapidocr-onnxruntime", "Apache-2.0", "one of OCR's parallel engines"),
    DependencyNotice("onnxruntime-genai", "MIT", "Inference API"),
    DependencyNotice("huggingface_hub", "Apache-2.0", "Inference/Proving Grounds model downloads"),
    DependencyNotice("jsonschema", "MIT", "Inference API structured output validation"),
    DependencyNotice("openpyxl", "MIT", "Persistence API Excel export"),
    DependencyNotice("boto3", "Apache-2.0", "Persistence/OCR S3-compatible storage clients"),
    DependencyNotice("b2sdk", "MIT", "Persistence API Backblaze B2"),
    DependencyNotice("google-api-python-client", "Apache-2.0", "Ingestion/Persistence Google Drive"),
    DependencyNotice("google-auth", "Apache-2.0", "Google API auth"),
    DependencyNotice("intuit-oauth", None, "Accounting Sync QuickBooks OAuth"),
    DependencyNotice("python-quickbooks", None, "Accounting Sync QuickBooks client"),
    DependencyNotice("xero-python", None, "Accounting Sync Xero client"),
)


class CreditsScreen(Screen):
    """A scrolling screen: version/codename lineage first, then the dependency notices."""

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Static(t("credits.title"), id="credits-title"),
            Static(self._codename_lineage(), id="credits-lineage"),
            Static(t("credits.scroll_hint"), id="credits-hint"),
            Static(self._dependency_text(), id="credits-deps"),
            id="credits-container",
        )
        yield Footer()

    def _codename_lineage(self) -> str:
        lines = [f"Running: {PROGRAM_VERSION} ({codename() or 'pre-release, no codename yet'})"]
        for major, name in sorted(MAJOR_CODENAMES.items()):
            lines.append(f"  x{major} — {name}")
        return "\n".join(lines)

    def _dependency_text(self) -> str:
        return "\n".join(
            f"{d.package} — {d.license or 'license not yet verified for this pass'} — {d.used_by}"
            for d in THIRD_PARTY_DEPENDENCIES
        )


__all__ = ["CreditsScreen", "DependencyNotice", "THIRD_PARTY_DEPENDENCIES"]
