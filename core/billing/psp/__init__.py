"""Swappable payment providers (§3).

Deliberately empty of re-exports; each provider is imported by name from its own module and
registered against `base.ProviderRegistry`.

§3's requirement is architectural: PSP credentials are per-install config, "never hardcoded to
one merchant account (or self-hosted buyers would route payments through the reference
deployment's own account)". Both PayMongo and Xendit are real implementations behind one
interface — §3 resolves that explicitly as "not a deferred either/or".
"""
