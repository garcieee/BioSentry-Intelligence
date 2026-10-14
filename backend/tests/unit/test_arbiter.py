"""Arbiter v1: rule 1 and rule 5 live, rules 2-4 inert, ordering deterministic."""

import itertools
from dataclasses import replace
from typing import Any

import pytest

from biosentry.domain.arbiter import (
    Guarantees,
    NotesSignal,
    NotRanked,
    Ranked,
    TierBSignal,
    TierCSignal,
    WorriedPin,
    arbitrate,
    rank_ward,
)
from biosentry.domain.computed import Computed, NotComputed, Window
from biosentry.domain.scoring.tier_a import News2Inputs, News2Score, Risk, score_news2
from biosentry.domain.scoring.tier_b.interface import Finding
from biosentry.schemas import (
    Acvpu,
    EscalationReason,
    EscalationRule,
    FindingDirection,
    Provenance,
    ProvenanceSource,
    Spo2Scale,
)

from samples import provenance  # isort: skip

BASE = News2Inputs(
    respiratory_rate=16,
    spo2=98,
    spo2_scale=Spo2Scale.scale_1,
    supplemental_o2=False,
    systolic_bp=120,
    heart_rate=70,
    consciousness=Acvpu.A,
    temperature=37.0,
)


def news2(**changes: Any) -> News2Score:
    result = score_news2(replace(BASE, **changes))
    assert isinstance(result, News2Score)
    return result


def ranked(patient_id: str = "p-1", **changes: Any) -> Ranked:
    decision = arbitrate(patient_id, news2(**changes))
    assert isinstance(decision, Ranked)
    return decision


# --- Rule 1: Tier A threshold -------------------------------------------------------------

RULE_1 = [
    ({}, Risk.low, False),
    ({"respiratory_rate": 10, "heart_rate": 45, "systolic_bp": 105}, Risk.low, False),  # 3
    ({"heart_rate": 35}, Risk.low_medium, True),  # a single 3 inside a total of 3
    ({"respiratory_rate": 22, "heart_rate": 120, "temperature": 38.5}, Risk.medium, True),
    ({"respiratory_rate": 26, "systolic_bp": 85, "heart_rate": 120}, Risk.high, True),
]


@pytest.mark.parametrize(("changes", "risk", "escalated"), RULE_1)
def test_rule_1_escalates_on_any_chart_2_trigger(
    changes: dict[str, Any], risk: Risk, escalated: bool
) -> None:
    decision = ranked(**changes)
    assert decision.news2.risk is risk
    assert decision.escalated is escalated
    assert bool(decision.reasons) is escalated


def test_rule_1_reasons_are_the_scorers_own_lines() -> None:
    decision = ranked(respiratory_rate=26, systolic_bp=85, heart_rate=120)
    assert [r.text for r in decision.reasons] == [
        decision.news2.total_reason,
        decision.news2.trigger_reason,
    ]
    assert {r.rule for r in decision.reasons} == {EscalationRule.tier_a_threshold}
    assert "Total 8 (≥7): high" in decision.news2.reasons


def test_a_single_three_in_a_low_total_cites_only_the_trigger() -> None:
    decision = ranked(heart_rate=35)
    assert [r.text for r in decision.reasons] == [decision.news2.trigger_reason]
    assert decision.news2.trigger_reason == "Single parameter at 3: heart rate"


def test_reasons_convert_to_contract_escalation_reasons() -> None:
    converted = ranked(respiratory_rate=26, systolic_bp=85).escalation_reasons()
    assert converted
    assert all(isinstance(r, EscalationReason) for r in converted)
    assert ranked().escalation_reasons() == []


# --- Rule 5: missing input -> NOT RANKED --------------------------------------------------


def not_ranked(**changes: Any) -> NotRanked:
    decision = arbitrate("p-9", score_news2(replace(BASE, **changes)))
    assert isinstance(decision, NotRanked)
    return decision


def test_missing_blood_pressure_is_not_ranked_and_says_what_to_do() -> None:
    decision = not_ranked(systolic_bp=None)
    assert decision.reason == "Systolic BP missing"
    assert decision.instruction == "Record a blood pressure"
    assert [p.input for p in decision.problems] == ["systolic_bp"]


def test_no_device_data_asks_for_the_patch() -> None:
    decision = not_ranked(respiratory_rate=None, spo2=None, heart_rate=None, temperature=None)
    assert decision.reason == "No device data"
    assert decision.instruction == "Apply the patch and verify the signal"


def test_some_device_inputs_missing_names_them() -> None:
    decision = not_ranked(spo2=None, temperature=None)
    assert decision.reason == "SpO2 missing, Temperature missing"
    assert decision.instruction == "Check the patch is applied and the signal is verified"


def test_nurse_and_device_problems_combine_in_one_reason() -> None:
    decision = not_ranked(heart_rate=None, consciousness=None, spo2_scale=None)
    assert decision.reason == (
        "Heart rate missing, Level of consciousness missing, SpO2 scale missing"
    )
    assert decision.instruction.split("; ") == [
        "Check the patch is applied and the signal is verified",
        "Record ACVPU",
        "Record the SpO2 scale (a clinician's decision)",
    ]


def test_implausible_value_is_not_ranked_and_asks_for_re_entry() -> None:
    decision = not_ranked(systolic_bp=0)
    assert decision.reason == "Systolic BP implausible"
    assert decision.instruction == "Re-enter systolic bp"


def test_not_ranked_carries_no_score() -> None:
    decision = not_ranked(systolic_bp=None)
    assert not hasattr(decision, "news2")
    assert not hasattr(decision, "total")


# --- Rules 2-4 and guarantees: inert, typed ---------------------------------------------


def inert_inputs() -> dict[str, Any]:
    prov = Provenance.model_validate(provenance(source="model", tier="C"))
    finding = Finding(
        "af", "Arrhythmia burden", "40%", FindingDirection.rising, ProvenanceSource.device, True
    )
    return {
        "tier_c": TierCSignal(Computed(0.99, prov, Window(0.0, 60.0, 1.0))),
        "tier_b": TierBSignal((finding,)),
        "notes": NotesSignal(True, "renal", "feels worse"),
        "worried": WorriedPin("rn-delacruz", "gut feeling"),
        "guarantees": Guarantees(False, True),
    }


def test_inert_hooks_never_change_the_decision() -> None:
    baseline = arbitrate("p-1", news2(heart_rate=60))
    assert isinstance(baseline, Ranked)
    assert baseline.inert == ()
    supplied = inert_inputs()
    for size in range(1, len(supplied) + 1):
        for names in itertools.combinations(supplied, size):
            decision = arbitrate("p-1", news2(heart_rate=60), **{n: supplied[n] for n in names})
            assert isinstance(decision, Ranked)
            assert replace(decision, inert=()) == baseline
            assert len(decision.inert) == len(names)


def test_a_not_computed_tier_contributes_nothing() -> None:
    decision = arbitrate(
        "p-1",
        news2(),
        tier_c=TierCSignal(NotComputed("no_model_registered")),
        tier_b=TierBSignal(NotComputed("not_implemented")),
    )
    assert isinstance(decision, Ranked)
    assert (decision.escalated, decision.reasons) == (False, ())
    assert decision.inert == ("rule_2_tier_c", "rule_3_tier_b")


def test_a_high_tier_c_probability_cannot_raise_a_patient_in_v1() -> None:
    low = ranked("p-low")
    with_c = arbitrate("p-low", news2(), tier_c=inert_inputs()["tier_c"])
    assert isinstance(with_c, Ranked)
    assert with_c.sort_key == low.sort_key
    assert not with_c.escalated


def test_inert_hooks_are_also_inert_for_not_ranked() -> None:
    plain = not_ranked(systolic_bp=None)
    result = arbitrate("p-9", score_news2(replace(BASE, systolic_bp=None)), **inert_inputs())
    assert isinstance(result, NotRanked)
    assert replace(result, inert=()) == plain


# --- Ordering ----------------------------------------------------------------------------


def ward() -> list[Ranked | NotRanked]:
    return [
        arbitrate("p-low-4", news2(respiratory_rate=22, heart_rate=45)),  # total 3? see below
        arbitrate("p-single-3", news2(heart_rate=35)),
        arbitrate("p-medium", news2(respiratory_rate=22, heart_rate=120, temperature=38.5)),
        arbitrate("p-high", news2(respiratory_rate=26, systolic_bp=85, heart_rate=120)),
        arbitrate("p-zero", news2()),
        arbitrate("p-nobp", score_news2(replace(BASE, systolic_bp=None))),
    ]


def test_ward_order_is_trigger_level_then_total_then_id() -> None:
    result = rank_ward(ward())
    order = [d.patient_id for _, d in result.ranked]
    assert order == ["p-high", "p-medium", "p-single-3", "p-low-4", "p-zero"]
    assert [rank for rank, _ in result.ranked] == [1, 2, 3, 4, 5]
    assert [d.patient_id for d in result.not_ranked] == ["p-nobp"]


def test_a_single_three_outranks_a_higher_total_without_a_trigger() -> None:
    four = ranked("p-four", respiratory_rate=10, heart_rate=45, systolic_bp=105, temperature=36.0)
    assert four.news2.total == 4
    assert four.news2.risk is Risk.low
    three = ranked("p-three", heart_rate=35)
    assert three.news2.total == 3
    assert rank_ward([four, three]).ranked[0][1].patient_id == "p-three"


def test_ordering_is_independent_of_input_order() -> None:
    decisions = ward()
    expected = rank_ward(decisions)
    for perm in itertools.permutations(decisions[:5]):
        assert rank_ward([*perm, decisions[5]]) == expected


def test_equal_scores_are_broken_by_patient_id() -> None:
    a, b = ranked("p-b", heart_rate=35), ranked("p-a", heart_rate=35)
    assert [d.patient_id for _, d in rank_ward([a, b]).ranked] == ["p-a", "p-b"]


def test_rank_is_relative_to_the_set_given() -> None:
    full = rank_ward(ward())
    subset = rank_ward([d for d in ward() if d.patient_id in {"p-medium", "p-zero"}])
    assert [(r, d.patient_id) for r, d in subset.ranked] == [(1, "p-medium"), (2, "p-zero")]
    assert full.ranked[1][0] == 2


def test_rank_ward_accepts_a_generator() -> None:
    result = rank_ward(d for d in ward())
    assert len(result.ranked) == 5
    assert len(result.not_ranked) == 1
