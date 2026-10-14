"""Read model: the ward, one patient, and the patient picker, scoped to the caller.

Scope is resolved first and fails closed: an unknown clinician sees nobody. Scores, ranks and
reasons are recomputed from the stored vitals with the real news2() and arbiter on every
read, and the rank is relative to the caller's set (it is never stored or cached).
Every read appends an audit record, including reads that find nothing.
"""

from biosentry.core.audit import AuditLog
from biosentry.domain.arbiter import NotRanked, Ranked, arbitrate, rank_ward
from biosentry.domain.scoring.tier_a import inputs_from_vitals, score_news2
from biosentry.repositories.memory.store import MemoryStore, PatientRecord
from biosentry.schemas import (
    AbstainedRow,
    PatientDetail,
    PatientSummary,
    ScoreRow,
    Tier,
    TierAScore,
    TierBreakdown,
    WardResponse,
)

SHIFT = "07:00"


class WardService:
    def __init__(self, store: MemoryStore, audit: AuditLog) -> None:
        self._store = store
        self._audit = audit

    # --- scope ---------------------------------------------------------------------------

    def visible(self, clinician_id: str) -> frozenset[str]:
        return self._store.assigned(clinician_id)

    # --- computed rows -------------------------------------------------------------------

    def _decision(self, record: PatientRecord) -> Ranked | NotRanked:
        row = record.ranked
        if row is None:
            raise ValueError(f"{record.id} has no vitals to score")
        return arbitrate(record.id, score_news2(inputs_from_vitals(row.vitals)))

    def _ranked_row(self, record: PatientRecord, rank: int, decision: Ranked) -> ScoreRow:
        base = self._base(record)
        return base.model_copy(
            update={
                "rank": rank,
                "score": decision.news2.total,
                "escalation_reasons": decision.escalation_reasons(),
                "labs": record.labs if record.labs is not None else base.labs,
            }
        )

    @staticmethod
    def _base(record: PatientRecord) -> ScoreRow:
        if record.ranked is None:
            raise ValueError(f"{record.id} has no scored row")
        return record.ranked

    def _not_ranked_row(self, record: PatientRecord, decision: NotRanked) -> AbstainedRow:
        base = self._base(record)
        return AbstainedRow(
            id=record.id,
            name=base.name,
            age=base.age,
            sex=base.sex,
            bed=base.bed,
            admitting_context=base.admitting_context,
            reason=decision.reason,
            instruction=decision.instruction,
            synthetic=True,
        )

    def _compute(self, ids: frozenset[str]) -> tuple[list[ScoreRow], list[AbstainedRow]]:
        decisions: dict[str, Ranked | NotRanked] = {}
        abstained: list[AbstainedRow] = []
        for pid in sorted(ids):
            record = self._store.patients.get(pid)
            if record is None:
                continue
            if record.ranked is not None:
                decisions[pid] = self._decision(record)
            elif record.abstained is not None:
                abstained.append(record.abstained)
        ranking = rank_ward(decisions.values())
        ranked = [
            self._ranked_row(self._store.patients[d.patient_id], rank, d)
            for rank, d in ranking.ranked
        ]
        abstained += [
            self._not_ranked_row(self._store.patients[d.patient_id], d) for d in ranking.not_ranked
        ]
        abstained.sort(key=lambda a: a.id)
        return ranked, abstained

    # --- reads ---------------------------------------------------------------------------

    def ward(self, clinician_id: str) -> WardResponse:
        ranked, abstained = self._compute(self.visible(clinician_id))
        self._audit.append(clinician_id, "view_ward", self._store.ward, "ok")
        return WardResponse(
            ward=self._store.ward,
            clinician=clinician_id,
            shift=SHIFT,
            receiving_data=True,
            sort_tier=Tier.A,
            tier_status=self._store.tier_status,
            ranked=ranked,
            abstained=abstained,
        )

    def patient(self, clinician_id: str, patient_id: str) -> PatientDetail | None:
        visible = self.visible(clinician_id)
        record = self._store.patients.get(patient_id)
        if record is None or patient_id not in visible or record.ranked is None:
            # Missing, not yours and not scored look identical to the caller (and in the log).
            self._audit.append(clinician_id, "view_patient", patient_id, "not_found")
            return None
        ranked, _ = self._compute(visible)
        row = next((r for r in ranked if r.id == patient_id), None)
        if row is None or record.history is None or record.breakdown is None:
            self._audit.append(clinician_id, "view_patient", patient_id, "not_found")
            return None
        self._audit.append(clinician_id, "view_patient", patient_id, "ok")
        breakdown = TierBreakdown(
            tier_a=TierAScore(score=row.score, label=f"NEWS2 = {row.score}"),
            tier_b=row.tier_b,
            tier_c=row.tier_c,
        )
        return PatientDetail(
            **row.model_dump(), vital_history=record.history, tier_breakdown=breakdown
        )

    def summaries(self, clinician_id: str) -> list[PatientSummary]:
        ranked, abstained = self._compute(self.visible(clinician_id))
        self._audit.append(clinician_id, "list_patients", "-", "ok")
        return [
            *(PatientSummary(id=r.id, name=r.name, bed=r.bed, ranked=True) for r in ranked),
            *(PatientSummary(id=a.id, name=a.name, bed=a.bed, ranked=False) for a in abstained),
        ]
