"""Process settings. Read from the environment once, at start-up."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET = _REPO_ROOT / "data" / "synthetic" / "synthetic.json"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://localhost:5174")


@dataclass(frozen=True, slots=True)
class Settings:
    dataset: Path = DEFAULT_DATASET
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        origins = source.get("BIOSENTRY_CORS_ORIGINS")
        return cls(
            dataset=Path(source.get("BIOSENTRY_DATASET", str(DEFAULT_DATASET))),
            cors_origins=(
                tuple(o.strip() for o in origins.split(",") if o.strip())
                if origins is not None
                else DEFAULT_CORS_ORIGINS
            ),
        )
