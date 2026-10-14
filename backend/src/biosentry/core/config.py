"""Process settings. Read from the environment once, at start-up."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET = _REPO_ROOT / "data" / "synthetic" / "synthetic.json"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://localhost:5174")


@dataclass(frozen=True, slots=True)
class Settings:
    dataset: Path = DEFAULT_DATASET
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    # What "now" means for ward data (lab and note times, lab freshness). The synthetic ward is
    # frozen at the dataset's as_of so ages stay coherent; "system" is the real clock. Audit
    # records always use the real clock.
    ward_time: Literal["dataset", "system"] = "dataset"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
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
        return cls(
            dataset=Path(source.get("BIOSENTRY_DATASET", str(DEFAULT_DATASET))),
            ward_time=ward_time,
            cors_origins=(
                tuple(o.strip() for o in origins.split(",") if o.strip())
                if origins is not None
                else DEFAULT_CORS_ORIGINS
            ),
        )
