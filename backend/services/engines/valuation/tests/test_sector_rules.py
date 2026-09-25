from services.engines.valuation.sector_rules import resolve_sector_rule, size_band

def test_resolves_media_archetype_and_size():
    rule = resolve_sector_rule("5915", 4_000_000)
    assert rule["archetype"] == "media_content"
    assert rule["size_band"] == "small"
    assert rule["parameters"]["wacc"]["median"] > .10
    assert rule["decision_readiness"] == "screen_grade"

def test_resolves_real_estate():
    assert resolve_sector_rule("6810", 60_000_000)["archetype"] == "real_estate"

def test_unknown_cnae_uses_disclosed_generic_rule():
    rule = resolve_sector_rule(None, None)
    assert rule["archetype"] == "general_business"
    assert rule["calibration_status"] == "provisional_policy_seed"

def test_size_bands():
    assert size_band(1_000_000) == "micro"
    assert size_band(5_000_000) == "small"
    assert size_band(20_000_000) == "medium"
    assert size_band(80_000_000) == "large"
