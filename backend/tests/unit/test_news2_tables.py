"""The NEWS2 tables partition their input grid, and their maxima add up to NEWS2's 20."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from biosentry.domain.scoring.tier_a import tables
from biosentry.domain.scoring.tier_a.tables import Band


def matching(bands: tuple[Band, ...], value: Decimal, on_oxygen: bool) -> list[Band]:
    return [
        b
        for b in bands
        if (b.low is None or value >= b.low)
        and (b.high is None or value <= b.high)
        and (b.on_oxygen is None or b.on_oxygen == on_oxygen)
    ]


INTEGER_TABLES = {
    "respiratory_rate": tables.RESPIRATORY_RATE,
    "spo2_scale_1": tables.SPO2_SCALE_1,
    "spo2_scale_2": tables.SPO2_SCALE_2,
    "systolic_bp": tables.SYSTOLIC_BP,
    "heart_rate": tables.HEART_RATE,
}


@pytest.mark.parametrize("name", INTEGER_TABLES)
def test_integer_tables_partition_the_whole_range(name: str) -> None:
    for value in range(1001):
        for on_oxygen in (False, True):
            hits = matching(INTEGER_TABLES[name], Decimal(value), on_oxygen)
            assert len(hits) == 1, f"{name}: {len(hits)} bands match {value} (oxygen={on_oxygen})"


def test_temperature_table_partitions_every_tenth_of_a_degree() -> None:
    for tenths in range(10001):
        value = Decimal(tenths) / 10
        assert len(matching(tables.TEMPERATURE, value, False)) == 1, value


def test_every_score_is_between_zero_and_three() -> None:
    every = [*INTEGER_TABLES.values(), tables.TEMPERATURE]
    scores = [b.score for bands in every for b in bands]
    scores += [*tables.SUPPLEMENTAL_O2_SCORE.values()]
    scores += [tables.CONSCIOUSNESS_ALERT_SCORE, tables.CONSCIOUSNESS_OTHER_SCORE]
    assert set(scores) <= {0, 1, 2, 3}


def test_parameter_maxima_add_up_to_twenty() -> None:
    def top(bands: tuple[Band, ...]) -> int:
        return max(b.score for b in bands)

    maxima: dict[str, Callable[[], int]] = {
        "respiratory_rate": lambda: top(tables.RESPIRATORY_RATE),
        "spo2": lambda: max(top(tables.SPO2_SCALE_1), top(tables.SPO2_SCALE_2)),
        "supplemental_o2": lambda: max(tables.SUPPLEMENTAL_O2_SCORE.values()),
        "systolic_bp": lambda: top(tables.SYSTOLIC_BP),
        "heart_rate": lambda: top(tables.HEART_RATE),
        "consciousness": lambda: tables.CONSCIOUSNESS_OTHER_SCORE,
        "temperature": lambda: top(tables.TEMPERATURE),
    }
    assert len(maxima) == 7
    assert sum(f() for f in maxima.values()) == tables.MAX_TOTAL == 20


def test_aggregate_thresholds_are_the_published_ones() -> None:
    assert (tables.SINGLE_PARAMETER_TRIGGER, tables.MEDIUM_FROM, tables.HIGH_FROM) == (3, 5, 7)
