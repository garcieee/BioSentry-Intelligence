"""NEWS2 scoring tables, transcribed from RCP 2017 (NEWS2 chart 1 and chart 2).

Every number in a score, a band label or a reason string comes from this file. Bounds are
inclusive. Inputs are rounded before banding (see `news2.round_half_up`), so integer
parameters meet integer bands and temperature meets 0.1 degC bands; the tables are a
partition of that grid (`tests/unit/test_news2_tables.py` proves it).
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Band:
    low: Decimal | None  # inclusive; None = unbounded below
    high: Decimal | None  # inclusive; None = unbounded above
    score: int
    label: str
    on_oxygen: bool | None = None  # None = any; False = breathing air; True = on oxygen


def _band(
    low: int | str | None,
    high: int | str | None,
    score: int,
    label: str,
    on_oxygen: bool | None = None,
) -> Band:
    return Band(
        None if low is None else Decimal(str(low)),
        None if high is None else Decimal(str(high)),
        score,
        label,
        on_oxygen,
    )


RESPIRATORY_RATE = (
    _band(None, 8, 3, "≤8"),
    _band(9, 11, 1, "9-11"),
    _band(12, 20, 0, "12-20"),
    _band(21, 24, 2, "21-24"),
    _band(25, None, 3, "≥25"),
)

SPO2_SCALE_1 = (
    _band(None, 91, 3, "≤91"),
    _band(92, 93, 2, "92-93"),
    _band(94, 95, 1, "94-95"),
    _band(96, None, 0, "≥96"),
)

# Scale 2 is for confirmed hypercapnic respiratory failure, on a clinician's recorded decision.
SPO2_SCALE_2 = (
    _band(None, 83, 3, "≤83"),
    _band(84, 85, 2, "84-85"),
    _band(86, 87, 1, "86-87"),
    _band(88, 92, 0, "88-92"),
    _band(93, None, 0, "≥93 on air", on_oxygen=False),
    _band(93, 94, 1, "93-94 on oxygen", on_oxygen=True),
    _band(95, 96, 2, "95-96 on oxygen", on_oxygen=True),
    _band(97, None, 3, "≥97 on oxygen", on_oxygen=True),
)

SYSTOLIC_BP = (
    _band(None, 90, 3, "≤90"),
    _band(91, 100, 2, "91-100"),
    _band(101, 110, 1, "101-110"),
    _band(111, 219, 0, "111-219"),
    _band(220, None, 3, "≥220"),
)

HEART_RATE = (
    _band(None, 40, 3, "≤40"),
    _band(41, 50, 1, "41-50"),
    _band(51, 90, 0, "51-90"),
    _band(91, 110, 1, "91-110"),
    _band(111, 130, 2, "111-130"),
    _band(131, None, 3, "≥131"),
)

TEMPERATURE = (
    _band(None, "35.0", 3, "≤35.0"),
    _band("35.1", "36.0", 1, "35.1-36.0"),
    _band("36.1", "38.0", 0, "36.1-38.0"),
    _band("38.1", "39.0", 1, "38.1-39.0"),
    _band("39.1", None, 2, "≥39.1"),
)

SUPPLEMENTAL_O2_SCORE = {False: 0, True: 2}
SUPPLEMENTAL_O2_LABEL = {False: "air", True: "oxygen"}

# Level of consciousness (ACVPU): Alert scores 0; new confusion, voice, pain, unresponsive 3.
CONSCIOUSNESS_ALERT_SCORE = 0
CONSCIOUSNESS_OTHER_SCORE = 3
CONSCIOUSNESS_ALERT_LABEL = "Alert"
CONSCIOUSNESS_OTHER_LABEL = "new confusion, V, P or U"

# Aggregate bands (chart 2). A single parameter scoring 3 is an independent trigger.
SINGLE_PARAMETER_TRIGGER = 3
MEDIUM_FROM = 5
HIGH_FROM = 7
MAX_TOTAL = 20
