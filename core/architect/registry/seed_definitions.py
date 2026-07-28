"""The definitions this registry ships with (`v3-deepdive-26-architect-api.md` §1, §5).

**Why these live here and not in the consuming APIs**: Reconciliation runs the VAT-math
check and Review/Flagging displays the flag it raises, but neither one is allowed to
*define* `vat_math_mismatch` — that is this registry's job and only this registry's job
(`docs/PRINCIPLES.md` §3.4). The same pattern was independently reinvented five separate
times before Architect existed; a seed set that lives with the consumer is how a sixth
starts.

**Every entry here is a seed, not a ceiling.** Consumers register their own additional
definitions at startup through `DefinitionRegistry.register`, and an instance's operator
can register more at runtime. Nothing in this file is a closed enumeration.

Sources, so a later reader can tell derived-from-real-work apart from invented: the flag
types are the concrete taxonomy `v3-plan-03-decisions.md` traced back to V2's real
reconciliation checks, mapped one-to-one onto Reconciliation's own check modules
(`v3-deepdive-17-reconciliation-api.md` §2). The reference-identifier types are the ones
Persistence's deep-dive §1 names as its motivating cases. The document-type categories are
the receipt document types Persistence's deep-dive names as "a new taxonomy category,
owned by Architect's registry."
"""

from __future__ import annotations

from ..contracts import FlagType, ReferenceIdentifierType, TaxonomyType

#: Two roots, deliberately separate subtrees rather than one flat list: what a business
#: *is* and what a document *is* answer different questions and are consumed by different
#: APIs (Matching/Inference for the first, Persistence/OCR for the second).
SEED_TAXONOMY_CATEGORIES: tuple[TaxonomyType, ...] = (
    TaxonomyType(code="business_category", label="Business category",
                 description="Root of the what-kind-of-business subtree."),
    TaxonomyType(code="food_service", label="Food service", parent_code="business_category"),
    TaxonomyType(code="fast_food", label="Fast food", parent_code="food_service"),
    TaxonomyType(code="restaurant", label="Restaurant", parent_code="food_service"),
    TaxonomyType(code="retail", label="Retail", parent_code="business_category"),
    TaxonomyType(code="convenience_store", label="Convenience store", parent_code="retail"),
    TaxonomyType(code="supermarket", label="Supermarket", parent_code="retail"),
    TaxonomyType(code="pharmacy", label="Pharmacy", parent_code="retail"),
    TaxonomyType(code="hardware", label="Hardware", parent_code="retail"),
    TaxonomyType(code="fuel_station", label="Fuel station", parent_code="business_category"),
    TaxonomyType(code="utilities", label="Utilities", parent_code="business_category"),
    TaxonomyType(code="transport", label="Transport", parent_code="business_category"),
    TaxonomyType(code="professional_services", label="Professional services",
                 parent_code="business_category"),

    TaxonomyType(code="document_type", label="Document type",
                 description="Root of the what-kind-of-document subtree."),
    TaxonomyType(code="official_receipt", label="Official Receipt (OR)",
                 parent_code="document_type"),
    TaxonomyType(code="sales_invoice", label="Sales Invoice (SI)", parent_code="document_type"),
    TaxonomyType(code="collection_receipt", label="Collection Receipt (CR)",
                 parent_code="document_type"),
    TaxonomyType(code="billing_statement", label="Billing statement",
                 parent_code="document_type"),
    TaxonomyType(code="delivery_receipt", label="Delivery receipt", parent_code="document_type"),
    TaxonomyType(code="acknowledgement_receipt", label="Acknowledgement receipt",
                 parent_code="document_type"),
)

#: Patterns here are *structural* only — they catch OCR misreads and malformed entry, and
#: say nothing about whether an identifier is real. A validity check against BIR's own
#: records would need a lookup service this project has no access to
#: (`v3-deepdive-17-reconciliation-api.md` §4.2, stated there rather than assumed here).
SEED_REFERENCE_IDENTIFIER_TYPES: tuple[ReferenceIdentifierType, ...] = (
    ReferenceIdentifierType(
        code="tin", label="Taxpayer Identification Number",
        description="9 base digits, optionally a 3-digit branch/RDO suffix, "
                    "conventionally dash-grouped. Structural check only.",
        value_pattern=r"^\d{3}-?\d{3}-?\d{3}(-?\d{3})?$", example="123-456-789-000",
        multi_valued=False,
    ),
    ReferenceIdentifierType(
        code="or_number", label="Official Receipt number",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9\-/]{0,31}$", example="OR-0001234",
        multi_valued=False,
    ),
    ReferenceIdentifierType(
        code="si_number", label="Sales Invoice number",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9\-/]{0,31}$", example="SI-0001234",
        multi_valued=False,
    ),
    ReferenceIdentifierType(
        code="atp_number", label="Authority to Print number",
        description="Printed on BIR-registered receipts; consumed by the ATP validity check.",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9\-]{0,31}$", multi_valued=False,
    ),
    ReferenceIdentifierType(
        code="license_plate", label="Vehicle plate number",
        description="One of Persistence's own motivating cases for typed identifiers.",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9 \-]{0,15}$",
    ),
    ReferenceIdentifierType(
        code="utility_account_number", label="Utility account number",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9\-]{0,31}$",
    ),
    ReferenceIdentifierType(
        code="policy_number", label="Policy number",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9\-/]{0,31}$",
    ),
    ReferenceIdentifierType(
        code="patient_id", label="Patient identifier",
        value_pattern=r"^[A-Za-z0-9][A-Za-z0-9\-/]{0,31}$",
    ),
)

#: One entry per real Reconciliation check module, plus the two flags raised from outside
#: Reconciliation. `raised_by` is recorded because "who can raise this" is a real question
#: a reviewer asks about an unfamiliar flag, and the answer would otherwise only exist by
#: grepping.
SEED_FLAG_TYPES: tuple[FlagType, ...] = (
    FlagType(code="vat_math_mismatch", label="VAT math does not reconcile",
             description="Printed subtotal/VAT/total do not reconcile within tolerance.",
             default_severity="medium", raised_by=("reconciliation",)),
    FlagType(code="tin_format_malformed", label="TIN is structurally malformed",
             default_severity="medium", raised_by=("reconciliation",)),
    FlagType(code="date_implausible", label="Receipt date is implausible",
             default_severity="low", raised_by=("reconciliation",)),
    FlagType(code="account_outlier", label="Amount is an outlier for this vendor/category",
             default_severity="low", raised_by=("reconciliation",)),
    FlagType(code="semantic_duplicate", label="Probable duplicate of another receipt",
             description="Distinct from Ingestion's exact-byte dedup.",
             default_severity="medium", raised_by=("reconciliation",)),
    FlagType(code="vendor_group_mismatch", label="Vendor grouped under the wrong entity",
             default_severity="medium", raised_by=("reconciliation",)),
    FlagType(code="items_vendor_mismatch", label="Line items do not fit the vendor's category",
             default_severity="low", raised_by=("reconciliation",)),
    FlagType(code="bir_completeness", label="Missing a BIR-required field",
             default_severity="high", raised_by=("reconciliation",)),
    FlagType(code="orphaned_archive_reference", label="Archive reference resolves to nothing",
             default_severity="high", raised_by=("reconciliation",)),
    FlagType(code="geo_vendor_cross_reference", label="Address and vendor disagree",
             default_severity="low", raised_by=("reconciliation", "geo_address")),
    FlagType(code="atp_validity", label="Authority to Print looks invalid or expired",
             default_severity="medium", raised_by=("reconciliation",)),
    FlagType(code="reimport_conflict", label="Reimport conflicts with canonical state",
             description="Both the user and canonical state changed the same field to "
                         "different values — surfaced, never auto-resolved "
                         "(`docs/PRINCIPLES.md` §4.3).",
             default_severity="high", raised_by=("reimport",)),
    FlagType(code="content_security_unsafe", label="File failed or could not complete a scan",
             description="An unscannable file is unsafe, never a silent bypass "
                         "(`docs/PRINCIPLES.md` §4.2).",
             default_severity="high", raised_by=("content_security",)),
)

#: Everything the registry seeds itself with, in registration order — taxonomy first so a
#: category's parent is always already present when its child registers.
ALL_SEED_DEFINITIONS = (
    SEED_TAXONOMY_CATEGORIES + SEED_REFERENCE_IDENTIFIER_TYPES + SEED_FLAG_TYPES
)

__all__ = [
    "ALL_SEED_DEFINITIONS",
    "SEED_FLAG_TYPES",
    "SEED_REFERENCE_IDENTIFIER_TYPES",
    "SEED_TAXONOMY_CATEGORIES",
]
