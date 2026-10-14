"""In-memory repository seeded from the committed synthetic dataset (CP6).

A patient is either ranked (a full ScoreRow with vitals, a history and a breakdown) or NOT
RANKED (an AbstainedRow). Scores, ranks and reasons are not stored: the services recompute
them from the vitals on every read, so a write that changes an input changes the result.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from biosentry.schemas import (
    AbstainedRow,
    BloodPressure,
    ClinicalNote,
    LabPanel,
    ScoreRow,
    TierBreakdown,
    TierStatus,
    VitalHistoryFull,
)
from biosentry.schemas.common import Acvpu


@dataclass(slots=True)
class PatientRecord:
    id: str
    ranked: ScoreRow | None = None
    abstained: AbstainedRow | None = None
    history: VitalHistoryFull | None = None
    breakdown: TierBreakdown | None = None
    labs: LabPanel | None = None  # None until a lab is entered (abstained patients)
    admitted_bp: BloodPressure | None = None  # nurse-entered at admission, structured once
    admitted_acvpu: Acvpu | None = None

    @property
    def name(self) -> str:
        source = self.ranked or self.abstained
        if source is None:
            raise ValueError(f"{self.id} has no row")
        return source.name

    @property
    def bed(self) -> str:
        source = self.ranked or self.abstained
        if source is None:
            raise ValueError(f"{self.id} has no row")
        return source.bed


@dataclass(frozen=True, slots=True)
class ClinicianEntry:
    id: str
    role: str
    patients: frozenset[str]


@dataclass(slots=True)
class MemoryStore:
    ward: str
    as_of: datetime  # the dataset's "now"
    tier_status: list[TierStatus]
    patients: dict[str, PatientRecord]
    clinicians: dict[str, ClinicianEntry]
    notes: dict[str, list[ClinicalNote]]
    note_counter: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)

    # --- reads -------------------------------------------------------------------------------

    def knows_clinician(self, clinician_id: str) -> bool:
        return clinician_id in self.clinicians

    def assigned(self, clinician_id: str) -> frozenset[str]:
        """The patients under this clinician's care. Unknown id: nobody (fails closed)."""
        entry = self.clinicians.get(clinician_id)
        return entry.patients if entry is not None else frozenset()

    # --- writes ------------------------------------------------------------------------------

    def next_patient_id(self) -> str:
        numbers = [int(pid.removeprefix("p-")) for pid in self.patients if pid.startswith("p-")]
        return f"p-{max(numbers, default=0) + 1:03d}"

    def next_note_id(self) -> str:
        self.note_counter += 1
        return f"n-{self.note_counter:03d}"

    def add_patient(self, record: PatientRecord, clinician_id: str) -> None:
        with self.lock:
            self.patients[record.id] = record
            entry = self.clinicians[clinician_id]
            self.clinicians[clinician_id] = ClinicianEntry(
                entry.id, entry.role, entry.patients | {record.id}
            )


def load(path: Path) -> MemoryStore:
    raw = json.loads(path.read_text(encoding="utf-8"))
    patients: dict[str, PatientRecord] = {}
    for item in raw["ranked"]:
        row = ScoreRow.model_validate(item)
        detail = raw["details"][row.id]
        patients[row.id] = PatientRecord(
            id=row.id,
            ranked=row,
            history=VitalHistoryFull.model_validate(detail["vital_history"]),
            breakdown=TierBreakdown.model_validate(detail["tier_breakdown"]),
            labs=row.labs,
        )
    for item in raw["abstained"]:
        abstained = AbstainedRow.model_validate(item)
        patients[abstained.id] = PatientRecord(id=abstained.id, abstained=abstained)

    notes: dict[str, list[ClinicalNote]] = {}
    for item in raw["notes"]:
        note = ClinicalNote.model_validate(item)
        notes.setdefault(note.patient_id, []).append(note)
    counter = max((int(n.id.removeprefix("n-")) for ns in notes.values() for n in ns), default=0)

    clinicians = {
        cid: ClinicianEntry(cid, entry["role"], frozenset(entry["patients"]))
        for cid, entry in raw["clinicians"].items()
    }
    first = next(iter(patients.values())).ranked
    tier_status = list(first.tier_status) if first is not None else []
    return MemoryStore(
        ward=raw["ward"],
        as_of=datetime.fromisoformat(raw["as_of"]),
        tier_status=tier_status,
        patients=patients,
        clinicians=clinicians,
        notes=notes,
        note_counter=counter,
    )
