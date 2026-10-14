"""Typed results for pure computations: a value with its provenance, or an explicit refusal.

A computation either returns `Computed` (value, where it came from, over which window) or
`NotComputed` (why it did not). Nothing is filled in, interpolated or defaulted (I1).
"""

from dataclasses import dataclass
from typing import Generic, TypeVar

from biosentry.schemas import Provenance, QualityLevel

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Window:
    start_s: float  # seconds from the start of the signal
    end_s: float
    coverage: float  # valid samples / samples in the window, 0..1


@dataclass(frozen=True, slots=True)
class Computed(Generic[T]):
    value: T
    provenance: Provenance
    window: Window

    @property
    def quality(self) -> QualityLevel:
        return self.provenance.quality


@dataclass(frozen=True, slots=True)
class NotComputed:
    reason: str


Result = Computed[T] | NotComputed
