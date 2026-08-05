"""`GitHubAppIssueFilingClient` — real config-store-backed configuration, real
`is_configured()` gating, and a real JWT-minting round trip verified against a real
generated RSA keypair. Actual issue creation against GitHub's live API is not tested
here -- this project holds no real GitHub App installation to file against, and firing
a real issue-creation call as part of an automated test suite would be undesirable
regardless."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

httpx = pytest.importorskip("httpx", reason="httpx is not installed in this interpreter")

from common.local_config_store import LocalConfigStore  # noqa: E402
from core.telemetrees.diagnostics.github_app_auth import mint_app_jwt  # noqa: E402
from core.telemetrees.diagnostics.issue_filer import GitHubAppIssueFilingClient  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def _real_rsa_pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def test_is_configured_is_false_with_nothing_set(tmp_path):
    client = GitHubAppIssueFilingClient(tmp_path)
    assert client.is_configured() is False


def test_is_configured_is_true_once_every_field_is_set(tmp_path):
    store = LocalConfigStore(tmp_path, "telemetrees/github_app.json")
    store.set("app_id", "123")
    store.set("private_key_pem", "fake-pem")
    store.set("installation_id", "456")
    store.set("repo_owner", "domtrifoundation")
    store.set("repo_name", "Receipt-System-V3")

    client = GitHubAppIssueFilingClient(tmp_path)
    assert client.is_configured() is True


def test_is_configured_is_false_when_one_field_is_missing(tmp_path):
    store = LocalConfigStore(tmp_path, "telemetrees/github_app.json")
    store.set("app_id", "123")
    store.set("private_key_pem", "fake-pem")
    store.set("installation_id", "456")
    store.set("repo_owner", "domtrifoundation")
    # repo_name deliberately left unset

    client = GitHubAppIssueFilingClient(tmp_path)
    assert client.is_configured() is False


def test_file_issue_reports_not_configured_honestly(tmp_path):
    client = GitHubAppIssueFilingClient(tmp_path)

    result = run(client.file_issue("title", "body"))

    assert result.ok is False
    assert "not configured" in result.error_detail


def test_mint_app_jwt_produces_a_real_verifiable_rs256_signature():
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes, serialization

    key_pem = _real_rsa_pem()
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    private_key = load_pem_private_key(key_pem, password=None)
    public_key = private_key.public_key()

    token = mint_app_jwt("app-123", key_pem, now=1_000_000)
    header_b64, payload_b64, sig_b64 = token.split(".")

    header = json.loads(base64.urlsafe_b64decode(_pad(header_b64)))
    payload = json.loads(base64.urlsafe_b64decode(_pad(payload_b64)))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload["iss"] == "app-123"
    assert payload["iat"] == 1_000_000 - 60
    assert payload["exp"] == 1_000_000 + 540

    signature = base64.urlsafe_b64decode(_pad(sig_b64))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    # Raises if the signature doesn't verify -- the real, load-bearing assertion.
    public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
