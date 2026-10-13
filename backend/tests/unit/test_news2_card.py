"""The model card must cite RCP 2017 and carry every band the code scores with."""

from pathlib import Path

from biosentry.domain.scoring.tier_a import tables

CARD = Path(__file__).resolve().parents[3] / "models" / "tier_a" / "news2" / "card.md"


def test_card_cites_rcp_2017_and_states_the_licence_status() -> None:
    text = CARD.read_text(encoding="utf-8")
    assert "Royal College of Physicians" in text
    assert "2017" in text
    assert "licence | unverified" in text


def test_card_lists_every_band_label_used_by_the_scorer() -> None:
    text = CARD.read_text(encoding="utf-8")
    all_bands = [
        *tables.RESPIRATORY_RATE,
        *tables.SPO2_SCALE_1,
        *tables.SPO2_SCALE_2,
        *tables.SYSTOLIC_BP,
        *tables.HEART_RATE,
        *tables.TEMPERATURE,
    ]
    for band in all_bands:
        label = band.label.replace(" on air", "").replace(" on oxygen", "")
        assert label in text, f"model card does not mention band {band.label!r}"


def test_card_states_the_aggregate_thresholds() -> None:
    text = CARD.read_text(encoding="utf-8")
    assert "0-4 low, 5-6 medium, 7 or more high" in text
    assert f"Maximum {tables.MAX_TOTAL}" in text
