"""models/registry.yaml: every entry valid, cards present, licence/production rule enforced."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from biosentry.domain.registry import Registry, RegistryEntry

ROOT = Path(__file__).resolve().parents[3]


def entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "tier_x/model",
        "tier": "B",
        "kind": "classical",
        "version": "1",
        "status": "implemented",
        "sha256": None,
        "corpus": [],
        "licence": "unverified",
        "metrics": {},
        "valid_until": None,
        "card": "models/tier_x/model/card.md",
    }
    return {**base, **overrides}


def test_committed_registry_is_valid_and_every_card_exists() -> None:
    raw = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    registry = Registry.model_validate(raw)
    assert {m.id for m in registry.models} >= {
        "tier_a/news2",
        "tier_b/arrhythmia",
        "tier_c/outcome",
    }
    for model in registry.models:
        assert (ROOT / model.card).is_file(), f"{model.id}: missing card {model.card}"


def test_unverified_licence_can_never_be_production() -> None:
    with pytest.raises(ValidationError, match="unverified licence"):
        RegistryEntry.model_validate(entry(status="production", licence="unverified"))


def test_verified_licence_may_be_production() -> None:
    RegistryEntry.model_validate(
        entry(status="production", licence="https://example.org/licence", kind="deterministic")
    )


@pytest.mark.parametrize("licence", ["MIT", "http://example.org", "", "Unverified"])
def test_licence_is_an_https_url_or_the_word_unverified(licence: str) -> None:
    with pytest.raises(ValidationError, match="licence must be"):
        RegistryEntry.model_validate(entry(licence=licence))


def test_learned_models_past_scaffold_need_a_sha256() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        RegistryEntry.model_validate(entry(kind="ml", status="research"))
    RegistryEntry.model_validate(entry(kind="ml", status="scaffold"))
    RegistryEntry.model_validate(entry(kind="ml", status="research", sha256="a" * 64))


@pytest.mark.parametrize("digest", ["abc", "A" * 64, "g" * 64])
def test_sha256_must_be_64_lowercase_hex(digest: str) -> None:
    with pytest.raises(ValidationError, match="sha256"):
        RegistryEntry.model_validate(entry(sha256=digest))


def test_ids_are_unique() -> None:
    with pytest.raises(ValidationError, match="unique"):
        Registry.model_validate({"models": [entry(), entry()]})
