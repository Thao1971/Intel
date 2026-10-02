"""`lang=en` writes the opportunity card in English; Spanish is unchanged and numbers use English format."""
from services import opportunity_view as V


def _series():
    return [{"year": 2023, "revenue": 1_000_000.0}, {"year": 2024, "revenue": 1_232_000.0}]


def test_number_formats_per_language():
    assert V.pct_es(0.448) == "44,8%" and V.eur_es(2_600_000) == "2,6 M€"
    t = V.use_lang("en")
    try:
        assert V.pct_es(0.448) == "44.8%" and V.pct_es(-0.031) == "−3.1%"
        assert V.eur_es(515_000) == "€515k" and V.eur_es(2_600_000) == "€2.6M" and V.eur_es(41_200_000_000) == "€41,200M"
    finally:
        V.reset_lang(t)
    assert V.pct_es(0.448) == "44,8%"


def test_headline_and_comparison_in_english():
    t = V.use_lang("en")
    try:
        text = V.headline("growth.revenue_surge", {"value": 0.232}, _series(), [])
        assert text == "Revenue rises 23.2% in 2024."
        cmp = V.compare_to_baseline(0.232, {"p50": 0.05, "p75": 0.12, "sample_size": 40})
        assert cmp["text_es"].startswith("Grows above the top quarter of similar companies in its sector and size")
        assert cmp["sample_note_es"] == "Comparison based on 40 comparable companies."
        assert V.missing_for_opportunity("candidate", None, _series(), [], 2024)[0].startswith("Compare its growth")
        assert V.size_label_es("small") == "Small"
        assert [c["label_es"] for c in V.thesis_chips(["growth.sustained"])] == ["Growth"]
    finally:
        V.reset_lang(t)


def test_spanish_is_the_default():
    assert V.headline("growth.revenue_surge", {"value": 0.232}, _series(), []) == "Los ingresos suben un 23,2% en 2024."
    assert V.size_label_es("small") == "Pequeña"
