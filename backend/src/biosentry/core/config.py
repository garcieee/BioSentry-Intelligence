"""Process settings. Read from the environment once, at start-up.

Settings refuse to exist in a combination that cannot be run safely: a cache TTL above the
staleness ceiling, or more than one worker while state lives in one process's memory. The
process fails to start with a message that names the fix.
"""

import math
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET = _REPO_ROOT / "data" / "synthetic" / "synthetic.json"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://localhost:5174")

# The shortest period after which a displayed value could be called stale. No staleness rule
# exists yet (open ruling 2: the default is to show the age only), so this is a provisional
# ceiling and not a clinical threshold: a cache TTL above it is refused at start-up, so the day
# a rule exists no cached snapshot can outlive it. Revisit when ruling 2 is settled.
SHORTEST_STALENESS_S = 60.0
DEFAULT_CACHE_TTL_S = 30.0

CacheBackend = Literal["memory", "none"]
_WORKER_VARIABLES = ("BIOSENTRY_WORKERS", "WEB_CONCURRENCY", "UVICORN_WORKERS")
_WORKER_FLAG = re.compile(r"^(?:--workers|-w)(?:=(.*))?$")


class ConfigError(ValueError):
    """The process was configured in a way it cannot run safely. It refuses to start."""


def in_process_state(*, cache: str, repository: str = "memory") -> tuple[str, ...]:
    """What this configuration keeps in the memory of ONE process.

    A second worker would hold its own, diverging copy of each part named here (a nurse's entry
    on one worker invisible on the next request, an audit row on a worker that is never asked).
    A database repository lifts the first two; a shared cache, or none, lifts the third.
    """
    parts: list[str] = []
    if repository == "memory":
        parts += ["repositories", "audit log"]
    if cache == "memory":
        parts.append("snapshot cache")
    return tuple(parts)


def _count(name: str, raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, not {raw!r}") from None
    if value < 0:
        raise ConfigError(f"{name} must not be negative")
    return value


def declared_workers(env: Mapping[str, str], argv: Sequence[str]) -> int:
    """The most serving processes this start-up declares: environment variables and the CLI.

    `--workers N` (uvicorn) and `-w N` (gunicorn) are read from argv because that is how
    multi-worker servers are usually started, and a worker process inherits its parent's
    argv. A value that does not parse is an error, never "one".
    """
    counts = [1]
    for name in _WORKER_VARIABLES:
        raw = env.get(name)
        if raw is not None and raw.strip():
            counts.append(_count(name, raw))
    args = list(argv)
    for index, arg in enumerate(args):
        match = _WORKER_FLAG.match(arg)
        if match is None:
            continue
        raw = match.group(1)
        if raw is None:
            raw = args[index + 1] if index + 1 < len(args) else ""
        counts.append(_count(arg.partition("=")[0], raw))
    return max(counts)


@dataclass(frozen=True, slots=True)
class Settings:
    dataset: Path = DEFAULT_DATASET
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    # What "now" means for ward data (lab and note times, lab freshness). The synthetic ward is
    # frozen at the dataset's as_of so ages stay coherent; "system" is the real clock. Audit
    # records always use the real clock.
    ward_time: Literal["dataset", "system"] = "dataset"
    # Per-patient score snapshots (CP7). "none" computes on every read.
    cache: CacheBackend = "memory"
    cache_ttl_s: float = DEFAULT_CACHE_TTL_S
    # Serving processes sharing this state, as declared or detected at start-up.
    workers: int = 1

    def __post_init__(self) -> None:
        if self.cache not in ("memory", "none"):
            raise ConfigError(f"BIOSENTRY_CACHE must be 'memory' or 'none', not {self.cache!r}")
        if not (math.isfinite(self.cache_ttl_s) and 0 < self.cache_ttl_s <= SHORTEST_STALENESS_S):
            raise ConfigError(
                f"BIOSENTRY_CACHE_TTL_S must be above 0 and at most {SHORTEST_STALENESS_S:g} "
                f"seconds (the shortest staleness threshold), not {self.cache_ttl_s!r}"
            )
        if self.workers < 1:
            raise ConfigError("the number of workers must be at least 1")
        local = in_process_state(cache=self.cache)
        if self.workers > 1 and local:
            named = [f"the {part}" for part in local]
            listed = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
            raise ConfigError(
                f"refusing to start with {self.workers} workers: {listed} live in the memory of "
                "one process, so every worker would serve its own diverging copy (an entry "
                "recorded on one worker would be missing on the next request). Run a single "
                "worker (no --workers, WEB_CONCURRENCY unset or 1); multiple workers need a "
                "shared database repository and BIOSENTRY_CACHE=none or a shared cache."
            )

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, argv: Sequence[str] | None = None
    ) -> "Settings":
        """Read the process's environment. An explicit `env` describes a process with no
        command line unless `argv` is given too, which keeps callers hermetic."""
        source = os.environ if env is None else env
        args: Sequence[str] = (sys.argv if env is None else ()) if argv is None else argv
        origins = source.get("BIOSENTRY_CORS_ORIGINS")
        ward_time: Literal["dataset", "system"]
        match source.get("BIOSENTRY_WARD_TIME", "dataset"):
            case "dataset":
                ward_time = "dataset"
            case "system":
                ward_time = "system"
            case other:
                raise ValueError(
                    f"BIOSENTRY_WARD_TIME must be 'dataset' or 'system', not {other!r}"
                )
        cache: CacheBackend
        match source.get("BIOSENTRY_CACHE", "memory"):
            case "memory":
                cache = "memory"
            case "none":
                cache = "none"
            case other:
                raise ConfigError(f"BIOSENTRY_CACHE must be 'memory' or 'none', not {other!r}")
        ttl_raw = source.get("BIOSENTRY_CACHE_TTL_S")
        try:
            ttl = float(ttl_raw) if ttl_raw is not None else DEFAULT_CACHE_TTL_S
        except ValueError:
            raise ConfigError(f"BIOSENTRY_CACHE_TTL_S must be a number, not {ttl_raw!r}") from None
        return cls(
            dataset=Path(source.get("BIOSENTRY_DATASET", str(DEFAULT_DATASET))),
            ward_time=ward_time,
            cors_origins=(
                tuple(o.strip() for o in origins.split(",") if o.strip())
                if origins is not None
                else DEFAULT_CORS_ORIGINS
            ),
            cache=cache,
            cache_ttl_s=ttl,
            workers=declared_workers(source, args),
        )
