"""Cache keys: `patient_id:schema_version:scorer_sha`.

A key holds an opaque surrogate id, a number and a digest: no name, no bed, no clinician and
no value. The shape check below cannot prove an id is opaque (a surrogate and a record number
look alike); opacity is the caller's contract. It does refuse everything that is plainly a
person ("Santos, Maria", "Bed 12", an e-mail address) so that a careless caller fails loudly
instead of putting PHI into a key that backends log and expose.
"""

import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}:[0-9]+:[0-9a-f]{64}")


def snapshot_key(patient_id: str, schema_version: int, scorer_sha: str) -> str:
    if _ID.fullmatch(patient_id) is None:
        raise ValueError("a cache key takes an opaque surrogate id, never a name or a label")
    if schema_version < 1:
        raise ValueError("schema_version starts at 1")
    if _SHA256.fullmatch(scorer_sha) is None:
        raise ValueError("scorer_sha must be a lowercase sha256 hex digest")
    return f"{patient_id}:{schema_version}:{scorer_sha}"


def is_snapshot_key(key: str) -> bool:
    """Whether `key` has exactly the shape `snapshot_key` produces (used by tests and guards)."""
    return _KEY.fullmatch(key) is not None
