"""In-memory repository seeded from the committed synthetic dataset.

Every patient is one `UnscoredPatient`: demographics, vitals, series, labs and the demo
Tier B/C content. Scores, ranks, reasons and the ranked/NOT RANKED split are not stored: the
services compute them from the vitals on every read with the real news2() and arbiter, so a
recorded value re-ranks the patient immediately.
"""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from biosentry.schemas import (
    ClinicalNote,
    ScoreRow,
    TierStatus,
    UnscoredPatient,
    VitalHistoryFull,
)


@dataclass(slots=True)
class PatientRecord:
    id: str
    state: UnscoredPatient
    # Bumped by every change to `state`. A cached snapshot is only as good as the revision it
    # was computed from, and the store is the one place that can say what the current one is.
    revision: int = 0


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

    def role_of(self, clinician_id: str) -> str | None:
        entry = self.clinicians.get(clinician_id)
        return entry.role if entry is not None else None

    def assigned(self, clinician_id: str) -> frozenset[str]:
        """The patients under this clinician's care. Unknown id: nobody (fails closed)."""
        entry = self.clinicians.get(clinician_id)
        return entry.patients if entry is not None else frozenset()

    def read(self, patient_id: str) -> tuple[int, UnscoredPatient] | None:
        """A patient's revision and the state at that revision, read together (or None)."""
        with self.lock:
            record = self.patients.get(patient_id)
            return (record.revision, record.state) if record is not None else None

    # --- writes ------------------------------------------------------------------------------

    def update(
        self, patient_id: str, change: Callable[[UnscoredPatient], UnscoredPatient]
    ) -> tuple[int, UnscoredPatient]:
        """Replace a patient's state with `change(state)`, atomically.

        Returns the new revision and state. Every write to a patient's state goes through here,
        so the revision cannot be left behind by a writer that forgot to say anything changed.
        """
        with self.lock:
            record = self.patients[patient_id]
            record.state = change(record.state)
            record.revision += 1
            return record.revision, record.state

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


def _state_from_row(row: ScoreRow, history: VitalHistoryFull) -> UnscoredPatient:
    return UnscoredPatient(
        id=row.id,
        name=row.name,
        age=row.age,
        sex=row.sex,
        bed=row.bed,
        admitting_context=row.admitting_context,
        trend=row.trend,
        mechanism=row.mechanism,
        supporting=row.supporting,
        vitals=row.vitals,
        vital_trends=row.vital_trends,
        vital_history=history,
        labs=row.labs,
        tier_b=row.tier_b,
        tier_c=row.tier_c,
        signal_quality=row.signal_quality,
        last_update_s=row.last_update_s,
        synthetic=row.synthetic,
    )


def load(path: Path) -> MemoryStore:
    raw = json.loads(path.read_text(encoding="utf-8"))
    patients: dict[str, PatientRecord] = {}
    tier_status: list[TierStatus] = []
    for item in raw["ranked"]:
        row = ScoreRow.model_validate(item)
        history = VitalHistoryFull.model_validate(raw["details"][row.id]["vital_history"])
        patients[row.id] = PatientRecord(row.id, _state_from_row(row, history))
        tier_status = tier_status or list(row.tier_status)
    for item in raw["unscored"]:
        state = UnscoredPatient.model_validate(item)
        patients[state.id] = PatientRecord(state.id, state)

    notes: dict[str, list[ClinicalNote]] = {}
    for item in raw["notes"]:
        note = ClinicalNote.model_validate(item)
        notes.setdefault(note.patient_id, []).append(note)
    counter = max((int(n.id.removeprefix("n-")) for ns in notes.values() for n in ns), default=0)

    clinicians = {
        cid: ClinicianEntry(cid, entry["role"], frozenset(entry["patients"]))
        for cid, entry in raw["clinicians"].items()
    }
    return MemoryStore(
        ward=raw["ward"],
        as_of=datetime.fromisoformat(raw["as_of"]),
        tier_status=tier_status,
        patients=patients,
        clinicians=clinicians,
        notes=notes,
        note_counter=counter,
    )
