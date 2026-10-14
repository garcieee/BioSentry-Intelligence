"""Tier B and Tier C are scaffolds: interfaces that refuse, never fabricate."""

import inspect
from typing import get_type_hints

import pytest

from biosentry.domain.computed import NotComputed
from biosentry.domain.scoring.tier_b.interface import (
    LabellerRegistry,
    Unimplemented,
    label_windows,
)
from biosentry.domain.scoring.tier_c.interface import NoModel, Predictor
from biosentry.domain.signals import SignalInput
from biosentry.schemas import Provenance, TierCInput
from samples import provenance, sample

PROV = Provenance.model_validate(provenance())


def test_unimplemented_labeller_refuses_every_window() -> None:
    signal = SignalInput(250.0, 10.0, (0.1,) * 7500, (True,) * 7500)  # three clean windows
    results = label_windows(Unimplemented("tier_b/arrhythmia"), signal, PROV)
    assert results == (NotComputed("not_implemented"),) * 3


def test_registry_rejects_duplicate_ids_and_unknown_lookups() -> None:
    registry = LabellerRegistry()
    registry.register(Unimplemented("a"))
    registry.register(Unimplemented("b"))
    assert registry.ids() == ("a", "b")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Unimplemented("a"))
    with pytest.raises(KeyError, match="no labeller registered"):
        registry.get("missing")


def test_no_model_predictor_never_predicts() -> None:
    features = TierCInput.model_validate(sample(TierCInput))
    assert NoModel().predict(features) == NotComputed("no_model_registered")


def test_predictor_takes_features_only() -> None:
    hints = get_type_hints(Predictor.predict)
    parameters = [
        name for name in inspect.signature(Predictor.predict).parameters if name != "self"
    ]
    assert parameters == ["features"]
    assert hints["features"] is TierCInput
