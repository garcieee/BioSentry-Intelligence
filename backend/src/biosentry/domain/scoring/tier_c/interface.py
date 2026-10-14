"""Tier C: outcome model. Feature contract and predictor protocol only (scaffold, CP5).

The input is `TierCInput`, built from features, never from Tier A or Tier B verdicts
(OVERVIEW: fuse inputs, never outputs). No model exists yet: the scaffold predictor returns
`NotComputed`, and the arbiter ignores Tier C until it is registered, calibrated and current.
"""

from typing import Protocol

from biosentry.schemas import TierCData, TierCInput

from ...computed import Computed, NotComputed


class Predictor(Protocol):
    id: str

    def predict(self, features: TierCInput) -> Computed[TierCData] | NotComputed: ...


class NoModel:
    """The scaffold predictor: never predicts, always says why (D5, I1)."""

    id = "tier_c/none"

    def predict(self, features: TierCInput) -> Computed[TierCData] | NotComputed:
        return NotComputed("no_model_registered")
