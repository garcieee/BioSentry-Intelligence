"""Series gaps (I1): a missing bin is null, never zero and never filled."""

import math
from typing import Any

import pytest
from pydantic import ValidationError

from biosentry.schemas import VitalHistory, VitalHistoryFull, VitalTrends
from samples import sample


def test_a_history_bin_may_be_a_gap() -> None:
    payload = sample(VitalHistory)
    payload["value"] = None
    assert VitalHistory.model_validate(payload).value is None


def test_a_gap_stays_null_through_a_round_trip() -> None:
    payload = sample(VitalHistoryFull)
    payload["heart_rate"][0]["value"] = None
    dumped = VitalHistoryFull.model_validate(payload).model_dump(mode="json")
    assert dumped["heart_rate"][0]["value"] is None


def test_zero_is_a_reading_and_null_is_a_gap() -> None:
    zero = VitalHistory.model_validate({**sample(VitalHistory), "value": 0})
    gap = VitalHistory.model_validate({**sample(VitalHistory), "value": None})
    assert zero.value == 0
    assert gap.value is None


@pytest.mark.parametrize("bad", [math.nan, math.inf, "97", True])
def test_a_bin_value_is_a_finite_number_or_null(bad: Any) -> None:
    with pytest.raises(ValidationError):
        VitalHistory.model_validate({**sample(VitalHistory), "value": bad})


@pytest.mark.parametrize("bad", ["06:30", "2026-09-03T06:30:00", "yesterday", None])
def test_a_bin_time_is_an_aware_iso_timestamp(bad: Any) -> None:
    with pytest.raises(ValidationError):
        VitalHistory.model_validate({**sample(VitalHistory), "time": bad})


def test_sparkline_series_allow_gaps_but_not_junk() -> None:
    payload = sample(VitalTrends)
    assert VitalTrends.model_validate(payload).heart_rate == [1.0, None, 2.0]
    payload["heart_rate"][0] = "n/a"
    with pytest.raises(ValidationError):
        VitalTrends.model_validate(payload)
