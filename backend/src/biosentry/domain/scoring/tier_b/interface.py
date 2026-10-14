"""Tier B: mechanism findings. Interface and registry only (scaffold, CP5).

Findings are named observations with their own units and direction, never a score and never
on a shared scale. No detector is implemented here: the scaffold returns `NotComputed`.

Burden, when a detector lands, is valid positive windows divided by valid windows, reported
with its coverage (valid windows / all windows). It is documented here and deliberately not
implemented: a gap never counts as normal and never counts as positive.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from biosentry.schemas import FindingDirection, Provenance, ProvenanceSource

from ...computed import NotComputed, Result
from ...signals import SignalInput, apply_windows


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    label: str
    value: str  # pre-formatted with its own units, e.g. "12%"
    direction: FindingDirection | None
    source: ProvenanceSource
    significant: bool  # exceeds this finding's own threshold
    pathway: str | None = None  # e.g. "renal", "perfusion", "arrhythmic"


class WindowLabeller(Protocol):
    """Labels one window (for example "af" or "sinus"). Gets the usable mask; never imputes."""

    id: str

    def label(self, samples: Sequence[float], usable: Sequence[bool]) -> str | NotComputed: ...


class Unimplemented:
    """The scaffold labeller: every window is NotComputed, nothing is fabricated (D5)."""

    def __init__(self, labeller_id: str) -> None:
        self.id = labeller_id

    def label(self, samples: Sequence[float], usable: Sequence[bool]) -> str | NotComputed:
        return NotComputed("not_implemented")


def label_windows(
    labeller: WindowLabeller,
    signal: SignalInput,
    provenance: Provenance,
    *,
    min_coverage: float = 0.5,
) -> tuple[Result[str], ...]:
    """Per-window labels; windows without enough valid signal are refused, never filled."""
    return apply_windows(signal, labeller.label, provenance=provenance, min_coverage=min_coverage)


class LabellerRegistry:
    """Detectors available to Tier B, by id. Ids are unique."""

    def __init__(self) -> None:
        self._by_id: dict[str, WindowLabeller] = {}

    def register(self, labeller: WindowLabeller) -> None:
        if labeller.id in self._by_id:
            raise ValueError(f"labeller {labeller.id!r} is already registered")
        self._by_id[labeller.id] = labeller

    def get(self, labeller_id: str) -> WindowLabeller:
        try:
            return self._by_id[labeller_id]
        except KeyError:
            raise KeyError(f"no labeller registered as {labeller_id!r}") from None

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))
