"""Append-only audit log (I7: every view is logged, whether it succeeded or not).

Records hold ids and outcomes only: no names, no PhilHealth PIN, no measurement values. A
record names the clinician by id and by the role they held when they acted (a manual entry
carries source `nurse` on the measurement; who typed it is answered here). This is the
in-memory CP6 form; the hash-chained, Postgres-backed log comes later.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

Outcome = Literal["ok", "not_found", "denied", "rejected"]
Clock = Callable[[], datetime]
RoleOf = Callable[[str], str | None]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _no_role(_clinician_id: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class AuditRecord:
    seq: int
    at: datetime
    clinician_id: str | None  # None: the caller was not identified
    role: str | None  # the role that clinician held when they acted; None when unidentified
    action: str
    resource: str  # a patient id, a ward, or "-"
    outcome: Outcome


class AuditLog:
    def __init__(self, clock: Clock = utc_now, role_of: RoleOf = _no_role) -> None:
        self._clock = clock
        self._role_of = role_of
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def append(
        self, clinician_id: str | None, action: str, resource: str, outcome: Outcome
    ) -> AuditRecord:
        with self._lock:
            record = AuditRecord(
                seq=len(self._records) + 1,
                at=self._clock(),
                clinician_id=clinician_id,
                role=self._role_of(clinician_id) if clinician_id is not None else None,
                action=action,
                resource=resource,
                outcome=outcome,
            )
            self._records.append(record)
            return record

    def records(self) -> tuple[AuditRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def for_clinician(self, clinician_id: str) -> tuple[AuditRecord, ...]:
        return tuple(r for r in self.records() if r.clinician_id == clinician_id)
