"""The scorer's identity: a digest of the code that turns inputs into a decision.

Cached decisions are keyed by it, so changing a band table, the NEWS2 scorer or the arbiter
makes every old entry unreachable instead of serving a decision the new code would not make.
It hashes source text, so it changes on any edit to those modules, comments included: that is
the safe direction for a cache key.
"""

import hashlib
import inspect
from collections.abc import Callable
from types import ModuleType

from biosentry.domain import arbiter
from biosentry.domain.scoring.tier_a import news2, tables

SCORER_MODULES: tuple[ModuleType, ...] = (tables, news2, arbiter)


def _source(module: ModuleType) -> bytes:
    try:
        return inspect.getsource(module).encode("utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"cannot read the source of {module.__name__} to identify the scorer; "
            "the cache needs it to key decisions by the code that made them"
        ) from exc


def scorer_sha(source: Callable[[ModuleType], bytes] = _source) -> str:
    digest = hashlib.sha256()
    for module in SCORER_MODULES:
        digest.update(module.__name__.encode("utf-8") + b"\0")
        digest.update(source(module) + b"\0")
    return digest.hexdigest()
