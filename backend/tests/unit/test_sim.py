"""The synthetic ward: determinism, contract validity, I1/I2/I6, scripted NEWS2 (CP3 gate bars)."""

import itertools
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from biosentry.domain.arbiter import Ranked, arbitrate, rank_ward
from biosentry.domain.scoring.tier_a import News2Score, inputs_from_vitals, score_news2
from biosentry.schemas import (
    AbstainedRow,
    ClinicalNote,
    EscalationRule,
    PatientDetail,
    ScoreRow,
    VitalHistoryFull,
)
from biosentry.schemas.common import MeasurementAbsent
from biosentry.sim import generator
from biosentry.sim.assemble import AS_OF, DEFAULT_SEED, Dataset, build, vitals_for
from biosentry.sim.generator import BINS, CLAMPS, MIN_VALID_PER_BIN, simulate
from biosentry.sim.scenarios import ABSTAINED, ALL, DEVICE_VITALS, RANKED, Scenario

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "data" / "synthetic" / "synthetic.json"
SEEDS = [0, 1, 7, DEFAULT_SEED, 424242]

NO_SCRIPTED_GAPS = [s for s in RANKED if not s.gaps and s.signal_lost_min == 0]


@pytest.fixture(scope="module")
def ward() -> Dataset:
    return build(DEFAULT_SEED)


# --- The scripts ----------------------------------------------------------------------------


def test_twelve_patients_ten_ranked_two_not_ranked() -> None:
    assert [s.id for s in ALL] == [f"p-{i:03d}" for i in range(1, 13)]
    assert len(RANKED) == 10
    assert {s.id for s in ABSTAINED} == {"p-004", "p-005"}
    assert all(s.expected_news2 is None for s in ABSTAINED)
    assert all(s.expected_news2 is not None for s in RANKED)


def test_scripted_end_levels_sit_inside_the_generator_clamps() -> None:
    for scn in ALL:
        for vital, plan in (scn.plans or {}).items():
            low, high = CLAMPS[vital]
            assert low <= plan.start <= high, (scn.id, vital)
            assert low <= plan.end <= high, (scn.id, vital)


def test_scripted_gaps_name_real_bins_and_vitals() -> None:
    for scn in ALL:
        for gap in scn.gaps:
            assert gap.bins
            assert all(0 <= b < BINS for b in gap.bins)
            assert set(gap.vitals) <= set(DEVICE_VITALS)


# --- Determinism and independence -----------------------------------------------------------


def test_same_seed_gives_byte_identical_json() -> None:
    assert build(DEFAULT_SEED).dumps() == build(DEFAULT_SEED).dumps()


def test_a_different_seed_gives_different_series() -> None:
    assert build(1).dumps() != build(2).dumps()


def test_committed_dataset_is_what_the_generator_writes(ward: Dataset) -> None:
    assert COMMITTED.read_text(encoding="utf-8") == ward.dumps(), (
        "data/synthetic/synthetic.json is stale: run `make data` and commit the result"
    )


def test_a_patient_depends_only_on_seed_and_index() -> None:
    scn = RANKED[0]
    first = simulate(scn, 5, 3)
    simulate(RANKED[1], 5, 4)  # simulating someone else in between changes nothing
    again = simulate(scn, 5, 3)
    assert first is not None
    assert again is not None
    for vital in DEVICE_VITALS:
        np.testing.assert_array_equal(first.minutes[vital], again.minutes[vital])


def test_two_patients_with_the_same_script_do_not_share_noise() -> None:
    scn = RANKED[0]
    a, b = simulate(scn, 5, 0), simulate(scn, 5, 1)
    assert a is not None
    assert b is not None
    assert not np.array_equal(a.minutes["heart_rate"], b.minutes["heart_rate"], equal_nan=True)


# --- Series: ranges, ordering, NaN end to end --------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_every_value_is_inside_the_clamps_and_finite_or_nan(seed: int) -> None:
    for index, scn in enumerate(ALL):
        signals = simulate(scn, seed, index)
        if signals is None:
            continue
        for vital in DEVICE_VITALS:
            low, high = CLAMPS[vital]
            values = signals.minutes[vital]
            valid = values[~np.isnan(values)]
            assert not np.isinf(values).any()
            assert ((valid >= low) & (valid <= high)).all(), (scn.id, vital)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_last_reading_is_the_scripted_end_level(seed: int) -> None:
    for index, scn in enumerate(RANKED):
        signals = simulate(scn, seed, index)
        assert signals is not None
        assert scn.plans is not None
        for vital in DEVICE_VITALS:
            latest = signals.latest[vital]
            assert latest is not None
            assert latest.value == scn.plans[vital].end
            assert signals.minutes[vital][latest.minute] == scn.plans[vital].end
            assert np.isnan(signals.minutes[vital][latest.minute + 1 :]).all()


@pytest.mark.parametrize("seed", SEEDS)
def test_a_bin_is_a_gap_exactly_when_it_has_too_few_usable_minutes(seed: int) -> None:
    for index, scn in enumerate(ALL):
        signals = simulate(scn, seed, index)
        if signals is None:
            continue
        for vital in DEVICE_VITALS:
            minutes = signals.minutes[vital].reshape(BINS, generator.BIN_MINUTES)
            usable = (~np.isnan(minutes)).sum(axis=1)
            for b, median in enumerate(signals.bins[vital]):
                assert (median is None) == (usable[b] < MIN_VALID_PER_BIN), (scn.id, vital, b)
                if median is not None:
                    assert median == round(float(np.nanmedian(minutes[b])), 1)


@pytest.mark.parametrize("seed", SEEDS)
def test_random_dropouts_alone_never_null_a_bin(seed: int) -> None:
    for scn in NO_SCRIPTED_GAPS:
        signals = simulate(scn, seed, ALL.index(scn))
        assert signals is not None
        for vital in DEVICE_VITALS:
            assert None not in signals.bins[vital], (scn.id, vital)


def test_scripted_gaps_null_exactly_the_scripted_bins() -> None:
    p006 = simulate(next(s for s in ALL if s.id == "p-006"), DEFAULT_SEED, 3)
    p010 = simulate(next(s for s in ALL if s.id == "p-010"), DEFAULT_SEED, 8)
    assert p006 is not None
    assert p010 is not None
    for vital in DEVICE_VITALS:
        assert [b for b, v in enumerate(p006.bins[vital]) if v is None] == [8, 9, 10]
    assert [b for b, v in enumerate(p010.bins["respiratory_rate"]) if v is None] == [20]
    assert None not in p010.bins["heart_rate"]


def test_trailing_signal_loss_ends_the_series_and_ages_the_last_update() -> None:
    scn = next(s for s in ALL if s.id == "p-011")
    signals = simulate(scn, DEFAULT_SEED, 8)
    assert signals is not None
    assert signals.bins["heart_rate"][-1] is None
    assert signals.last_update_s >= 20 * 60
    assert signals.latest["heart_rate"] is not None
    assert signals.latest["heart_rate"].minute == generator.MINUTES - 1 - 20


def test_no_patch_means_no_signals() -> None:
    p005 = next(s for s in ALL if s.id == "p-005")
    assert simulate(p005, DEFAULT_SEED, 4) is None


# --- The assembled ward -------------------------------------------------------------------------


def test_ward_shape(ward: Dataset) -> None:
    assert len(ward.ranked) == 10
    assert len(ward.abstained) == 2
    assert [r.rank for r in ward.ranked] == list(range(1, 11))
    assert {a.id for a in ward.abstained} == {"p-004", "p-005"}
    assert len(ward.notes) == 4


def test_ranks_come_from_the_arbiter_not_from_the_script(ward: Dataset) -> None:
    decisions = [arbitrate(r.id, score_news2(inputs_from_vitals(r.vitals))) for r in ward.ranked]
    expected = [d.patient_id for _, d in rank_ward(decisions).ranked]
    assert [r.id for r in ward.ranked] == expected


def test_trigger_first_ordering_shows_in_the_ward(ward: Dataset) -> None:
    order = [r.id for r in ward.ranked]
    assert order.index("p-008") < order.index("p-007")  # a single 3 outranks a total of 4


def test_every_score_is_news2_of_the_vitals_shown(ward: Dataset) -> None:
    for row in ward.ranked:
        result = score_news2(inputs_from_vitals(row.vitals))
        assert isinstance(result, News2Score)
        assert row.score == result.total == ward.labels[row.id].expected_news2


def test_reasons_come_only_from_implemented_rules(ward: Dataset) -> None:
    for row in ward.ranked:
        assert {r.rule for r in row.escalation_reasons} <= {EscalationRule.tier_a_threshold}
        decision = arbitrate(row.id, score_news2(inputs_from_vitals(row.vitals)))
        assert isinstance(decision, Ranked)
        assert [r.text for r in row.escalation_reasons] == [r.text for r in decision.reasons]


def test_tier_b_and_c_are_demo_never_live(ward: Dataset) -> None:
    for row in ward.ranked:
        status = {s.tier.value: s for s in row.tier_status}
        assert status["A"].live is True
        assert status["B"].live is False
        assert status["C"].live is False
        assert "demo" in status["B"].label.lower()
        assert "demo" in status["C"].label.lower()


def test_not_ranked_rows_name_what_is_missing(ward: Dataset) -> None:
    by_id = {a.id: a for a in ward.abstained}
    assert by_id["p-004"].reason == "Systolic BP missing"
    assert by_id["p-004"].instruction == "Record a blood pressure"
    assert by_id["p-005"].reason == "No device data"
    assert by_id["p-005"].instruction == "Apply the patch and verify the signal"


def test_every_record_is_synthetic_with_provenance(ward: Dataset) -> None:
    records: list[Any] = [*ward.ranked, *ward.abstained, *ward.notes]
    assert all(r.synthetic is True for r in records)
    for row in ward.ranked:
        measurements: list[Any] = [
            row.vitals.heart_rate,
            row.vitals.respiratory_rate,
            row.vitals.spo2,
            row.vitals.temperature,
            row.vitals.blood_pressure,
            row.vitals.consciousness,
            row.vitals.supplemental_o2,
            row.vitals.spo2_scale,
        ]
        measurements += [
            getattr(row.labs, name)
            for name in type(row.labs).model_fields
            if name != "freshness_hours" and getattr(row.labs, name) is not None
        ]
        for m in measurements:
            assert m.provenance.synthetic is True


def test_missing_readings_are_absent_never_zero() -> None:
    # No patch: every device vital is an absent measurement with a reason, not a zero.
    p005 = next(s for s in ALL if s.id == "p-005")
    vitals = vitals_for(p005, None)
    for vital in DEVICE_VITALS:
        data = getattr(vitals, vital).data
        assert isinstance(data, MeasurementAbsent)
        assert data.reason == "no_patch"
    # No blood pressure recorded: absent with a reason, not 0/0.
    p004 = next(s for s in ALL if s.id == "p-004")
    bp = vitals_for(p004, simulate(p004, DEFAULT_SEED, 3)).blood_pressure.data
    assert isinstance(bp, MeasurementAbsent)
    assert bp.reason == "not_measured"


def test_a_published_series_has_null_gaps_and_no_zero_fill(ward: Dataset) -> None:
    p006 = ward.details["p-006"][0]
    heart = [h.value for h in p006.heart_rate]
    assert heart.count(None) == 3
    for series in (p006.heart_rate, p006.respiratory_rate, p006.spo2):
        for point in series:
            assert point.value is None or point.value > 0
    for row in ward.ranked:
        for values in (
            row.vital_trends.heart_rate,
            row.vital_trends.respiratory_rate,
            row.vital_trends.spo2,
            row.vital_trends.temperature,
        ):
            assert len(values) == generator.SPARK_BINS
            assert all(v is None or v > 0 for v in values)


def test_history_times_are_ordered_fifteen_minute_bins_ending_before_as_of(ward: Dataset) -> None:
    for history, _ in ward.details.values():
        for series in (history.heart_rate, history.respiratory_rate, history.spo2):
            times = [p.time for p in series]
            assert len(times) == BINS
            assert times == sorted(times)
            assert all((b - a).total_seconds() == 900 for a, b in itertools.pairwise(times))
            assert times[-1] == AS_OF.replace(minute=45, hour=6)


def test_the_sparkline_is_the_last_three_hours_of_the_history(ward: Dataset) -> None:
    for row in ward.ranked:
        history, _ = ward.details[row.id]
        assert row.vital_trends.heart_rate == [p.value for p in history.heart_rate][12:]


# --- Contract validity of the written JSON ---------------------------------------------------


def test_the_written_json_validates_against_the_contract(ward: Dataset) -> None:
    data = json.loads(ward.dumps())
    assert data["synthetic"] is True
    for raw in data["ranked"]:
        ScoreRow.model_validate(raw)
        detail = data["details"][raw["id"]]
        PatientDetail.model_validate({**raw, **detail})
    for raw in data["abstained"]:
        AbstainedRow.model_validate(raw)
    for raw in data["notes"]:
        ClinicalNote.model_validate(raw)
    for detail in data["details"].values():
        VitalHistoryFull.model_validate(detail["vital_history"])


def test_json_has_no_nan_or_infinity_tokens(ward: Dataset) -> None:
    text = ward.dumps()
    assert "NaN" not in text
    assert "Infinity" not in text
    json.loads(text, parse_constant=lambda c: pytest.fail(f"non-finite constant {c}"))


def test_every_number_in_the_file_is_finite(ward: Dataset) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, float):
            assert math.isfinite(node)

    walk(ward.to_json_dict())


# --- Properties over seeds ---------------------------------------------------------------------


@settings(max_examples=25, deadline=None, database=None)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_for_any_seed_the_scripted_news2_holds_and_the_ward_is_valid(seed: int) -> None:
    ward = build(seed)
    assert len(ward.ranked) == 10
    assert len(ward.abstained) == 2
    for row in ward.ranked:
        assert row.score == ward.labels[row.id].expected_news2
    assert [r.rank for r in ward.ranked] == list(range(1, 11))


@settings(max_examples=25, deadline=None, database=None)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_for_any_seed_random_dropouts_never_create_a_gap(seed: int) -> None:
    for scn in NO_SCRIPTED_GAPS:
        signals = simulate(scn, seed, ALL.index(scn))
        assert signals is not None
        assert all(None not in signals.bins[v] for v in DEVICE_VITALS)


@settings(max_examples=15, deadline=None, database=None)
@given(
    seed=st.integers(min_value=0, max_value=2**31 - 1),
    end=st.floats(min_value=40, max_value=190, allow_nan=False),
)
def test_the_pinned_reading_is_exact_for_any_end_level(seed: int, end: float) -> None:
    base = RANKED[0]
    assert base.plans is not None
    plans = dict(base.plans)
    plans["heart_rate"] = replace(plans["heart_rate"], end=end)
    scn: Scenario = replace(base, plans=plans)
    signals = simulate(scn, seed, 0)
    assert signals is not None
    latest = signals.latest["heart_rate"]
    assert latest is not None
    assert latest.value == end
    assert signals.minutes["heart_rate"][latest.minute] == end


def test_clinician_directory_is_consistent(ward: Dataset) -> None:
    ids = {s.id for s in ALL}
    assert set(ward.clinicians) == {
        "rn-delacruz",
        "rn-reyes",
        "md-santos",
        "md-aquino",
        "rn-manalo",
    }
    for role, patients in ward.clinicians.values():
        assert role in {"rn", "md", "charge_rn"}
        assert set(patients) <= ids
    assert set(ward.clinicians["rn-manalo"][1]) == ids
    covered = {p for _, patients in ward.clinicians.values() for p in patients}
    assert covered == ids  # every patient is under someone's care
