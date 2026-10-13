"""Tier status, Tier B findings, Tier C output and input, and escalation reasons.

I3 tier separation: Tier C input (TierCInput) is built only from raw and derived features.
It has no field that can carry a Tier A score, a Tier B finding or an arbiter reason.
"""

from enum import StrEnum

from pydantic import AwareDatetime

from .base import Contract, Flag, Fraction, NonNegInt, NonNegNum, Num
from .clinical import LabPanel, VitalTrends, Vitals
from .common import ProvenanceSource, Tier


class TierStatus(Contract):
    tier: Tier
    live: Flag
    label: str


class FindingDirection(StrEnum):
    rising = "rising"
    falling = "falling"
    stable = "stable"
    new = "new"


class TierBFinding(Contract):
    """A named observation with its own units. Not comparable on a shared scale."""

    id: str
    label: str
    value: str  # pre-formatted with units, e.g. "12%", "KDIGO 2"
    direction: FindingDirection | None
    source: ProvenanceSource
    significant: Flag  # exceeds the finding's own threshold
    detail: str | None = None


class TierBData(Contract):
    findings: list[TierBFinding]


class TierCAttribution(Contract):
    feature: str
    contribution: Num  # signed; positive = risk-increasing


class TierCData(Contract):
    risk_probability: Fraction  # isotonic-calibrated, never the raw model score
    forecast_window: str
    scored_seconds_ago: NonNegNum  # the model's own clock, not the vitals feed's
    attributions: list[TierCAttribution]


class TierCInput(Contract):
    """Everything Tier C may read. Features in, never verdicts (OVERVIEW: fuse inputs)."""

    patient_id: str
    as_of: AwareDatetime
    age: NonNegInt | None
    sex: str | None
    admitting_context: str
    vitals: Vitals
    vital_trends: VitalTrends
    labs: LabPanel
    synthetic: Flag


class EscalationRule(StrEnum):
    tier_a_threshold = "tier_a_threshold"
    tier_c_raise = "tier_c_raise"
    tier_b_finding = "tier_b_finding"
    missing_input = "missing_input"


class EscalationReason(Contract):
    rule: EscalationRule
    text: str
    pathway: str | None = None  # for tier_b_finding: which mechanism
