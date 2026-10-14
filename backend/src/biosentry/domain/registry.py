"""Model registry entries and their rules (PLAN, Models principle).

Every model ships behind an entry in `models/registry.yaml`. Two rules are enforced here so
a bad entry fails a test instead of reaching a clinician:
  - `licence` is a verified https URL or the literal `unverified`;
  - `unverified` can never carry `status: production`.
Entries for learned models also need a sha256 once they leave `scaffold`.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from biosentry.schemas import Tier
from biosentry.schemas.base import Contract

UNVERIFIED = "unverified"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RegistryStatus(StrEnum):
    scaffold = "scaffold"  # interface only, no model
    implemented = "implemented"  # code exists, not validated on local data
    research = "research"  # trained or wrapped for study; not for ranking
    shadow = "shadow"  # runs and logs; never raises a patient
    production = "production"


class RegistryEntry(Contract):
    id: str
    tier: Tier
    kind: Literal["deterministic", "classical", "ml"]
    version: str
    status: RegistryStatus
    sha256: str | None  # digest of the weight artifact; None where there is none
    corpus: tuple[str, ...]
    licence: str
    metrics: dict[str, float]
    valid_until: date | None
    card: str  # repo-relative path to the model card

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.licence != UNVERIFIED and not self.licence.startswith("https://"):
            raise ValueError("licence must be an https URL or 'unverified'")
        if self.status is RegistryStatus.production and self.licence == UNVERIFIED:
            raise ValueError("an entry with an unverified licence cannot be status production")
        if self.sha256 is not None and not _SHA256.match(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        if self.kind == "ml" and self.status is not RegistryStatus.scaffold and self.sha256 is None:
            raise ValueError("a learned model past scaffold needs the sha256 of its artifact")
        return self


class Registry(Contract):
    models: tuple[RegistryEntry, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [m.id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("registry ids must be unique")
        return self
