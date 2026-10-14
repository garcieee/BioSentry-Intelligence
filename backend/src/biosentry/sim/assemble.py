"""Turn scripted scenarios into contract-valid records, scored by the real Tier A and arbiter.

Nothing here states a score, a rank or a reason: `news2()` computes the score from the
generated vitals and `arbitrate()` / `rank_ward()` produce the order and the reasons. Tier B
and Tier C content is scripted demo content (PLAN D11) and never reaches the arbiter.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from biosentry.domain.arbiter import NotRanked, Ranked, arbitrate, rank_ward
from biosentry.domain.scoring.tier_a import (
    News2Inputs,
    News2Score,
    inputs_from_vitals,
    score_news2,
)
from biosentry.schemas import (
    AbstainedRow,
    AcvpuMeasurement,
    BloodPressure,
    BloodPressureMeasurement,
    ClinicalNote,
    FindingDirection,
    FlagMeasurement,
    LabPanel,
    MeasurementAbsent,
    NumberMeasurement,
    PatientDetail,
    Provenance,
    ProvenanceSource,
    QualityLevel,
    ScoreRow,
    Spo2ScaleMeasurement,
    Tier,
    TierAScore,
    TierBData,
    TierBFinding,
    TierBreakdown,
    TierCAttribution,
    TierCData,
    TierStatus,
    Trend,
    VitalHistory,
    VitalHistoryFull,
    Vitals,
    VitalTrends,
)
from biosentry.schemas.common import (
    AcvpuPresent,
    BloodPressurePresent,
    FlagPresent,
    NumberPresent,
    Spo2ScalePresent,
)

from .generator import BIN_MINUTES, BINS, MINUTES, SPARK_BINS, PatientSignals, simulate
from .scenarios import ALL, DEVICE_VITALS, FindingSpec, Scenario, Vital

DEFAULT_SEED = 20260903
AS_OF = datetime(2026, 9, 3, 7, 0, 0, tzinfo=UTC)
FORECAST_WINDOW = "next 1\u20134h"
STALE_AFTER_S = BIN_MINUTES * 60  # a device reading older than one bin is degraded
FORMAT_VERSION = 1
LAB_UNITS = {"bnp": "pg/mL", "troponin": "ng/mL"}
SUPPORTING_LABS = ("bnp", "troponin")


@dataclass(frozen=True, slots=True)
class Label:
    """Script-emitted ground truth for evaluation (never read by the scorer)."""

    story: str
    trajectory: str
    expected_news2: int | None


@dataclass(frozen=True, slots=True)
class Dataset:
    seed: int
    as_of: datetime
    ranked: tuple[ScoreRow, ...]  # arbiter order, rank 1..n
    abstained: tuple[AbstainedRow, ...]
    details: dict[str, tuple[VitalHistoryFull, TierBreakdown]]
    notes: tuple[ClinicalNote, ...]
    labels: dict[str, Label]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT_VERSION,
            "seed": self.seed,
            "as_of": self.as_of.isoformat().replace("+00:00", "Z"),
            "synthetic": True,
            "ranked": [r.model_dump(mode="json") for r in self.ranked],
            "abstained": [a.model_dump(mode="json") for a in self.abstained],
            "details": {
                pid: {
                    "vital_history": history.model_dump(mode="json"),
                    "tier_breakdown": breakdown.model_dump(mode="json"),
                }
                for pid, (history, breakdown) in self.details.items()
            },
            "notes": [n.model_dump(mode="json") for n in self.notes],
            "labels": {
                pid: {
                    "story": label.story,
                    "trajectory": label.trajectory,
                    "expected_news2": label.expected_news2,
                }
                for pid, label in self.labels.items()
            },
        }

    def dumps(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _provenance(
    source: ProvenanceSource, observed_at: datetime, quality: QualityLevel = QualityLevel.ok
) -> Provenance:
    return Provenance(
        source=source,
        tier=None,
        observed_at=observed_at,
        computed_at=None,
        model_id=None,
        synthetic=True,
        quality=quality,
    )


def _number(value: float, prov: Provenance) -> NumberMeasurement:
    return NumberMeasurement(data=NumberPresent(present=True, value=value), provenance=prov)


def _absent_number(reason: str, source: ProvenanceSource) -> NumberMeasurement:
    prov = _provenance(source, AS_OF, QualityLevel.missing)
    return NumberMeasurement(data=MeasurementAbsent(present=False, reason=reason), provenance=prov)


def vitals_for(scn: Scenario, signals: PatientSignals | None) -> Vitals:
    nurse_at = AS_OF - timedelta(minutes=scn.nurse.minutes_ago)
    nurse = _provenance(ProvenanceSource.nurse, nurse_at)
    nurse_missing = _provenance(ProvenanceSource.nurse, AS_OF, QualityLevel.missing)

    device: dict[Vital, NumberMeasurement] = {}
    for vital in DEVICE_VITALS:
        latest = signals.latest[vital] if signals is not None else None
        if signals is None or latest is None:
            reason = "no_patch" if signals is None else "no_signal"
            device[vital] = _absent_number(reason, ProvenanceSource.device)
            continue
        age_s = (MINUTES - 1 - latest.minute) * 60
        observed_at = AS_OF - timedelta(seconds=age_s)
        quality = QualityLevel.degraded if age_s > STALE_AFTER_S else QualityLevel.ok
        prov = _provenance(ProvenanceSource.device, observed_at, quality)
        device[vital] = _number(latest.value, prov)

    if scn.nurse.systolic is None or scn.nurse.diastolic is None:
        bp = BloodPressureMeasurement(
            data=MeasurementAbsent(present=False, reason="not_measured"), provenance=nurse_missing
        )
    else:
        bp = BloodPressureMeasurement(
            data=BloodPressurePresent(
                present=True,
                value=BloodPressure(systolic=scn.nurse.systolic, diastolic=scn.nurse.diastolic),
            ),
            provenance=nurse,
        )
    return Vitals(
        heart_rate=device["heart_rate"],
        respiratory_rate=device["respiratory_rate"],
        spo2=device["spo2"],
        temperature=device["temperature"],
        blood_pressure=bp,
        consciousness=AcvpuMeasurement(
            data=AcvpuPresent(present=True, value=scn.nurse.acvpu), provenance=nurse
        ),
        supplemental_o2=FlagMeasurement(
            data=FlagPresent(present=True, value=scn.nurse.on_oxygen), provenance=nurse
        ),
        spo2_scale=Spo2ScaleMeasurement(
            data=Spo2ScalePresent(present=True, value=scn.nurse.spo2_scale), provenance=nurse
        ),
    )


def _labs(scn: Scenario) -> LabPanel:
    fields: dict[str, Any] = dict.fromkeys(LabPanel.model_fields)
    fields["freshness_hours"] = None
    if scn.labs is not None:
        prov = _provenance(ProvenanceSource.lab, AS_OF - timedelta(hours=scn.labs.hours_old))
        for name, value in scn.labs.values.items():
            if name not in fields:
                raise ValueError(f"{scn.id}: unknown lab {name!r}")
            fields[name] = _number(value, prov)
        fields["freshness_hours"] = scn.labs.hours_old
    return LabPanel(**fields)


def _bin_time(b: int) -> datetime:
    return AS_OF - timedelta(minutes=(BINS - b) * BIN_MINUTES)


def _trends(signals: PatientSignals) -> VitalTrends:
    def last(vital: Vital) -> list[float | None]:
        return list(signals.bins[vital][BINS - SPARK_BINS :])

    return VitalTrends(
        heart_rate=last("heart_rate"),
        respiratory_rate=last("respiratory_rate"),
        spo2=last("spo2"),
        temperature=last("temperature"),
    )


def _history(signals: PatientSignals) -> VitalHistoryFull:
    def series(vital: Vital) -> list[VitalHistory]:
        return [VitalHistory(time=_bin_time(b), value=v) for b, v in enumerate(signals.bins[vital])]

    return VitalHistoryFull(
        heart_rate=series("heart_rate"),
        respiratory_rate=series("respiratory_rate"),
        spo2=series("spo2"),
    )


def _earlier_level(signals: PatientSignals, vital: Vital) -> float | None:
    """Median of the hour that ended three hours before as_of (bins 8-11); None if sparse."""
    first = BINS - 2 * SPARK_BINS + 8
    values = [v for v in signals.bins[vital][first : first + 4] if v is not None]
    return median(values) if len(values) >= 2 else None


def _trend(signals: PatientSignals | None, now: News2Inputs) -> Trend:
    """NEWS2 now against NEWS2 three hours ago, both from the same scorer."""
    if signals is None:
        return Trend.insufficient
    then = News2Inputs(
        respiratory_rate=_earlier_level(signals, "respiratory_rate"),
        spo2=_earlier_level(signals, "spo2"),
        spo2_scale=now.spo2_scale,
        supplemental_o2=now.supplemental_o2,
        systolic_bp=now.systolic_bp,
        heart_rate=_earlier_level(signals, "heart_rate"),
        consciousness=now.consciousness,
        temperature=_earlier_level(signals, "temperature"),
    )
    before, after = score_news2(then), score_news2(now)
    if not isinstance(before, News2Score) or not isinstance(after, News2Score):
        return Trend.insufficient
    delta = after.total - before.total
    return Trend.rising if delta >= 1 else Trend.falling if delta <= -1 else Trend.stable


def _findings(scn: Scenario, signals: PatientSignals | None) -> list[TierBFinding]:
    out: list[TierBFinding] = []
    for spec in scn.tier_b:
        value, detail, direction = spec.value, spec.detail, spec.direction
        if spec.id == "rr" and scn.rr_baseline is not None and signals is not None:
            latest = signals.latest["respiratory_rate"]
            if latest is not None:
                pct = round((latest.value / scn.rr_baseline - 1.0) * 100)
                sign = "+" if pct >= 0 else "\u2212"
                value = f"{sign}{abs(pct)}% vs baseline"
                detail = f"vs personal baseline {scn.rr_baseline:g}/min"
        out.append(_finding(spec, value, detail, direction))
    return out


def _finding(
    spec: FindingSpec, value: str, detail: str | None, direction: FindingDirection | None
) -> TierBFinding:
    return TierBFinding(
        id=spec.id,
        label=spec.label,
        value=value,
        direction=direction,
        source=spec.source,
        significant=spec.significant,
        detail=detail,
    )


def _supporting(scn: Scenario, vitals: Vitals) -> str:
    parts: list[str] = []
    if isinstance(vitals.heart_rate.data, NumberPresent):
        parts.append(f"HR {vitals.heart_rate.data.value:g} bpm")
    if isinstance(vitals.blood_pressure.data, BloodPressurePresent):
        bp = vitals.blood_pressure.data.value
        parts.append(f"BP {bp.systolic}/{bp.diastolic} (nurse)")
    if scn.labs is not None:
        for name in SUPPORTING_LABS:
            if name in scn.labs.values:
                label = "Troponin" if name == "troponin" else name.upper()
                parts.append(
                    f"{label} {scn.labs.values[name]:g} {LAB_UNITS[name]} "
                    f"(lab, {scn.labs.hours_old:g}h)"
                )
                break
    return ", ".join(parts)


def build(seed: int = DEFAULT_SEED) -> Dataset:
    """The whole synthetic ward for one seed. Same seed, byte-identical JSON."""
    decisions: list[Ranked | NotRanked] = []
    rows: dict[str, ScoreRow] = {}
    details: dict[str, tuple[VitalHistoryFull, TierBreakdown]] = {}
    abstained_meta: dict[str, Scenario] = {}
    notes: list[ClinicalNote] = []
    labels: dict[str, Label] = {}

    for index, scn in enumerate(ALL):
        signals = simulate(scn, seed, index)
        vitals = vitals_for(scn, signals)
        inputs = inputs_from_vitals(vitals)
        result = score_news2(inputs)
        decision = arbitrate(scn.id, result)
        decisions.append(decision)
        labels[scn.id] = Label(scn.story, scn.trajectory, scn.expected_news2)
        for note in scn.notes:
            notes.append(
                ClinicalNote(
                    id=note.id,
                    patient_id=scn.id,
                    author=note.author,
                    role=note.role,
                    timestamp=AS_OF - timedelta(minutes=note.minutes_ago),
                    content=note.content,
                    synthetic=True,
                )
            )

        if isinstance(decision, NotRanked):
            if scn.expected_news2 is not None:
                raise ValueError(
                    f"{scn.id} was scripted to score {scn.expected_news2} but abstained"
                )
            abstained_meta[scn.id] = scn
            continue
        if not isinstance(result, News2Score):  # a Ranked decision always carries a score
            raise ValueError(f"{scn.id}: ranked without a NEWS2 score")
        if scn.expected_news2 is None:
            raise ValueError(f"{scn.id} was scripted to abstain but scored {result.total}")
        if signals is None:
            raise ValueError(f"{scn.id} has no patch but was scored")

        tier_c = (
            TierCData(
                risk_probability=scn.tier_c.risk_probability,
                forecast_window=FORECAST_WINDOW,
                scored_seconds_ago=scn.tier_c.scored_seconds_ago,
                attributions=[
                    TierCAttribution(feature=f, contribution=c) for f, c in scn.tier_c.attributions
                ],
            )
            if scn.tier_c is not None
            else None
        )
        findings = _findings(scn, signals)
        tier_b = TierBData(findings=findings) if findings else None
        history = _history(signals)
        breakdown = TierBreakdown(
            tier_a=TierAScore(score=result.total, label=f"NEWS2 = {result.total}"),
            tier_b=tier_b,
            tier_c=tier_c,
        )
        details[scn.id] = (history, breakdown)
        rows[scn.id] = ScoreRow(
            id=scn.id,
            rank=1,  # replaced below, once the ward is ordered
            score=result.total,
            trend=_trend(signals, inputs),
            name=scn.name,
            age=scn.age,
            sex=scn.sex,
            bed=scn.bed,
            admitting_context=scn.admitting_context,
            mechanism="Sorted on NEWS2 (Tier A). Tier B and C are demo content.",
            supporting=_supporting(scn, vitals),
            vitals=vitals,
            vital_trends=_trends(signals),
            labs=_labs(scn),
            sort_tier=Tier.A,
            tier_status=_tier_status(),
            tier_b=tier_b,
            tier_c=tier_c,
            escalation_reasons=[],  # replaced below from the arbiter
            synthetic=True,
            signal_quality=signals.signal_quality,
            last_update_s=signals.last_update_s,
        )

    ranking = rank_ward(decisions)
    ordered: list[ScoreRow] = []
    for rank, decision in ranking.ranked:
        row = rows[decision.patient_id]
        ordered.append(
            row.model_copy(
                update={"rank": rank, "escalation_reasons": decision.escalation_reasons()}
            )
        )
    abstained = tuple(
        AbstainedRow(
            id=nr.patient_id,
            name=abstained_meta[nr.patient_id].name,
            age=abstained_meta[nr.patient_id].age,
            sex=abstained_meta[nr.patient_id].sex,
            bed=abstained_meta[nr.patient_id].bed,
            admitting_context=abstained_meta[nr.patient_id].admitting_context,
            reason=nr.reason,
            instruction=nr.instruction,
            synthetic=True,
        )
        for nr in ranking.not_ranked
    )
    # Validate every detail against the contract before it is written anywhere.
    for row in ordered:
        history, breakdown = details[row.id]
        PatientDetail(**row.model_dump(), vital_history=history, tier_breakdown=breakdown)
    return Dataset(
        seed=seed,
        as_of=AS_OF,
        ranked=tuple(ordered),
        abstained=abstained,
        details=details,
        notes=tuple(sorted(notes, key=lambda n: n.id)),
        labels=labels,
    )


def _tier_status() -> list[TierStatus]:
    return [
        TierStatus(tier=Tier.A, live=True, label="NEWS2"),
        TierStatus(tier=Tier.B, live=False, label="Mechanism axes (demo)"),
        TierStatus(tier=Tier.C, live=False, label="Outcome model (demo)"),
    ]


__all__ = ["AS_OF", "DEFAULT_SEED", "Dataset", "Label", "build", "vitals_for"]
