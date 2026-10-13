"""Ward rows, abstained rows and the API response envelopes."""

from typing import Annotated

from pydantic import Field

from .base import Age, Contract, Flag, NonNegNum, Percent
from .clinical import LabPanel, VitalHistoryFull, VitalTrends, Vitals
from .common import Tier, Trend
from .tiers import EscalationReason, TierBData, TierCData, TierStatus


class ScoreRow(Contract):
    """A ranked patient: carries a NEWS2 score and rank. That every required input was
    present is enforced by the scorer and arbiter (CP4/5), not by this schema (I1, I4)."""

    id: str
    rank: Annotated[int, Field(strict=True, ge=1)]
    score: Annotated[int, Field(strict=True, ge=0, le=20)]  # NEWS2 aggregate, 0-20
    trend: Trend
    name: str
    age: Age | None
    sex: str | None
    bed: str
    admitting_context: str
    mechanism: str
    supporting: str
    vitals: Vitals
    vital_trends: VitalTrends
    labs: LabPanel
    sort_tier: Tier
    tier_status: list[TierStatus]
    tier_b: TierBData | None
    tier_c: TierCData | None
    escalation_reasons: list[EscalationReason]
    synthetic: Flag
    signal_quality: Percent
    last_update_s: NonNegNum


class AbstainedRow(Contract):
    """NOT RANKED is a first-class row (I4): a reason and an instruction, no score, no rank."""

    id: str
    name: str
    age: Age | None
    sex: str | None
    bed: str
    admitting_context: str
    reason: str
    instruction: str
    synthetic: Flag


class WardResponse(Contract):
    ward: str
    clinician: str
    shift: str
    receiving_data: Flag
    sort_tier: Tier
    tier_status: list[TierStatus]
    ranked: list[ScoreRow]
    abstained: list[AbstainedRow]


class TierAScore(Contract):
    score: Annotated[int, Field(strict=True, ge=0, le=20)]
    label: str


class TierBreakdown(Contract):
    tier_a: TierAScore | None
    tier_b: TierBData | None
    tier_c: TierCData | None


class PatientDetail(ScoreRow):
    vital_history: VitalHistoryFull
    tier_breakdown: TierBreakdown
