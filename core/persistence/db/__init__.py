"""Canonical-database plumbing: the WAL connection wrapper and the schema.

Import from `..contracts` for types. This subpackage is internal to Persistence.
"""

from .connection import Database, default_blob_root, default_db_path
from .receipts import ReceiptRepository
from .schema import CURRENT_SCHEMA_VERSION, SCHEMA

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "SCHEMA",
    "Database",
    "ReceiptRepository",
    "default_blob_root",
    "default_db_path",
]
