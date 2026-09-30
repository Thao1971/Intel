"""Tests unitarios (sin backend ni base de datos): criterio de tamaño único, lectura de cargos y puerta
de la señal de sucesión. Los datos reproducen la forma REAL de `norm_officers` en Arroba-pro
(roles en inglés, fechas DDMONYYYY) leída el 2026-09-29.

    python -m pytest backend/tests/test_opportunity_criteria.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import officer_utils as OU  # noqa: E402
from services import opportunity_criteria as CR  # noqa: E402
from services import opportunity_view as OV  # noqa: E402

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
GATE = dict(min_revenue=1_000_000, min_tenure_years=CR.SUCCESSION_MIN_TENURE_YEARS, now=NOW)


def _off(name, role, date):
    return {"person_name": name, "role": role, "appointment_date": date}


# ── criterio único ──

def test_default_floor_is_one_million_and_env_overrides_it():
    saved = os.environ.pop(CR.ENV_MIN_REVENUE, None)
    try:
        assert CR.configured_min_revenue() == (1_000_000.0, "default")
        os.environ[CR.ENV_MIN_REVENUE] = "750000"
        assert CR.configured_min_revenue() == (750_000.0, "config")
        for bad in ("abc", "-5", ""):
            os.environ[CR.ENV_MIN_REVENUE] = bad
            assert CR.configured_min_revenue() == (1_000_000.0, "default"), bad
    finally:
        os.environ.pop(CR.ENV_MIN_REVENUE, None)
        if saved is not None:
            os.environ[CR.ENV_MIN_REVENUE] = saved


def test_mandate_revenue_min_overrides_config_and_default():
    assert CR.effective_min_revenue({"revenue_min": 300_000}) == (300_000.0, "mandate")
    assert CR.effective_min_revenue({"revenue_min": 0}) == (0.0, "mandate")          # 0 es un valor válido
    assert CR.effective_min_revenue({"revenue_min": None, "revenue_max": 5e6}) == (1_000_000.0, "default")
    assert CR.effective_min_revenue({"revenue_min": True}) == (1_000_000.0, "default")  # bool no es un importe
    assert CR.effective_min_revenue(None) == (1_000_000.0, "default")


def test_explicit_min_revenue_override_wins():
    assert CR.effective_min_revenue(None, 250_000) == (250_000.0, "mandate")
    assert CR.effective_min_revenue({"revenue_min": 300_000}, 250_000) == (250_000.0, "mandate")   # el explícito manda
    assert CR.effective_min_revenue(None, -5) == (1_000_000.0, "default")                           # inválido: se ignora
    assert CR.effective_min_revenue(None, None) == (1_000_000.0, "default")


def test_unknown_revenue_never_meets_the_floor():
    assert CR.meets_size_floor(1_000_000, 1_000_000) is True
    assert CR.meets_size_floor(999_999.99, 1_000_000) is False
    assert CR.meets_size_floor(None, 1_000_000) is False


# ── lectura de cargos ──

def test_dates_in_both_real_formats():
    assert OU.parse_officer_date("27AUG2020") == datetime(2020, 8, 27, tzinfo=timezone.utc)
    assert OU.parse_officer_date("07/10/2022") == datetime(2022, 10, 7, tzinfo=timezone.utc)
    assert OU.parse_officer_date("31/02/2020") is None and OU.parse_officer_date("xx") is None
    assert OU.officer_date_iso("11APR2011") == "2011-04-11" and OU.officer_date_iso(None) is None


def test_roles_english_and_spanish_and_concursal_excluded():
    for r in ("Sole Director", "Joint And Several Director", "Joint Director", "Administrador Único",
              "Administrador Solidario"):
        assert OU.is_administrator_role(r), r
    for r in ("Director", "Chairperson", "Representative", "Bankruptcy Administrator", "Administrador concursal", None):
        assert not OU.is_administrator_role(r), r
    assert OU.is_sole_administrator_role("Sole Director") and OU.is_sole_administrator_role("Administrador Único")
    assert not OU.is_sole_administrator_role("Joint Director")


# ── puerta de sucesión ──

def test_gate_passes_sole_administrator_long_tenure_and_size():
    g = OU.succession_gate([_off("JUAN PEREZ LOPEZ", "Sole Director", "27AUG1995")], 2_000_000, **GATE)
    assert g["passed"] and g["admin"]["tenure_years"] > 31 and g["threshold"] == 20.0


def test_gate_rejects_each_condition_with_its_reason():
    sole = [_off("JUAN PEREZ LOPEZ", "Sole Director", "27AUG1995")]
    assert OU.succession_gate(sole, 900_000, **GATE)["reason"] == "below_size_floor"
    assert OU.succession_gate(sole, None, **GATE)["reason"] == "below_size_floor"
    two = sole + [_off("ANA GARCIA RUIZ", "Joint Director", "10MAY1999")]
    assert OU.succession_gate(two, 2_000_000, **GATE)["reason"] == "not_sole_administrator"
    joint = [_off("JUAN PEREZ LOPEZ", "Joint And Several Director", "27AUG1995")]
    assert OU.succession_gate(joint, 2_000_000, **GATE)["reason"] == "not_sole_administrator"
    young = [_off("JUAN PEREZ LOPEZ", "Sole Director", "27AUG2011")]      # 15,1 años: pasaba con el umbral antiguo
    assert OU.succession_gate(young, 2_000_000, **GATE)["reason"] == "tenure_below_threshold"
    corp = [_off("INVERSIONES XYZ SL", "Sole Director", "27AUG1995")]
    assert OU.succession_gate(corp, 2_000_000, **GATE)["reason"] == "no_administrator"
    assert OU.succession_gate([], 2_000_000, **GATE)["reason"] == "no_administrator"


def test_gate_uses_the_higher_of_configured_and_criterion_tenure():
    o = [_off("JUAN PEREZ LOPEZ", "Sole Director", "27AUG1999")]           # ~27,1 años
    assert OU.succession_gate(o, 2e6, base_threshold=15, **GATE)["passed"]
    g = OU.succession_gate(o, 2e6, base_threshold=30, **GATE)
    assert not g["passed"] and g["threshold"] == 30.0


def test_the_only_signal_that_existed_passes_at_20_years_and_a_19_year_admin_does_not():
    """La única señal real (Administrador Único desde 30/11/2001) tiene 24,8 años a 2026-09-29."""
    g = OU.succession_gate([_off("JUAN PEREZ LOPEZ", "Administrador Único", "30/11/2001")], 5_000_000, **GATE)
    assert g["passed"] and 24.7 <= g["admin"]["tenure_years"] <= 24.9
    assert CR.SUCCESSION_MIN_TENURE_YEARS == 20.0
    just_below = [_off("JUAN PEREZ LOPEZ", "Sole Director", "30/11/2007")]            # 18,8 años
    assert OU.succession_gate(just_below, 5_000_000, **GATE)["reason"] == "tenure_below_threshold"
    just_above = [_off("JUAN PEREZ LOPEZ", "Sole Director", "30/11/2005")]            # 20,8 años
    assert OU.succession_gate(just_above, 5_000_000, **GATE)["passed"]


def test_succession_headline_translates_the_english_role():
    ev = {"value": 27.1, "person_role": "Sole Director", "appointment_date": "27AUG1999",
          "succession_profile": {"successor_candidate": {"role": "Representative"}}}
    assert OV.headline("opportunity.succession_signal", ev, [], []) == (
        "Administrador único con 27,1 años en el cargo (desde 1999): posible relevo generacional.")
    assert "representante" in OV.signal_caveats("opportunity.succession_signal", ev)[0]["text_es"]


# ── el suelo en la vista ──

KRZ = [{"year": 2025, "revenue": 2593865.39}, {"year": 2024, "revenue": 2106134.98}, {"year": 2023, "revenue": 2603087.54}]
BASE = {"p50": 0.0198, "p75": 0.0641, "sample_size": 13}


def _composite_card(history, **kw):
    master = {"master_id": "m", "identity": {"legal_name": "X"},
              "financials": {"history": history, "latest": {"revenue": history[0]["revenue"], "year": history[0]["year"]}},
              "location": {}}
    primary = {"signal_type": "opportunity.expansion_opportunity", "is_composite": True, "evidence": {},
               "dimensions": {"confidence": 0.9, "urgency": 0.5, "persistence": 0.5}}
    return OV.build_card(primary=primary, all_types=[primary["signal_type"]], master=master, band="small",
                         baseline=BASE, sector_label="S", has_blocking_risk=False, expected_year=2025, **kw)


def test_opportunity_level_requires_the_size_floor():
    ok = _composite_card(KRZ)
    assert ok["level"] == "opportunity" and ok["size_floor"] == {"min_revenue_eur": 1_000_000.0, "meets": True}
    small = [{"year": h["year"], "revenue": h["revenue"] * 0.2} for h in KRZ]       # ~519 k€
    c = _composite_card(small)
    assert c["level"] == "candidate" and c["size_floor"]["meets"] is False
    assert c["missing_es"][0] == "Su tamaño (519 k€) queda por debajo del mínimo de 1 M€ de ingresos"
    assert _composite_card(small, min_revenue=300_000)["level"] == "opportunity"     # override (mandato)
    assert _composite_card(KRZ, min_revenue=5_000_000)["level"] == "candidate"        # un mandato puede subirlo


# ── comparativa de respaldo por sector (sin tamaño) ──

ESTIVIEL = [{"year": 2025, "revenue": 551172.47}, {"year": 2024, "revenue": 497669.89}, {"year": 2023, "revenue": 156947.2}]
SECTOR_A = {"p50": 0.0078, "p75": 0.2279, "sample_size": 46}      # datos reales de Arroba-pro, sección A


def test_sector_only_comparison_is_shown_but_does_not_qualify_for_opportunity():
    master = {"master_id": "m", "identity": {"legal_name": "X"},
              "financials": {"history": ESTIVIEL, "latest": {"revenue": 551172.47, "year": 2025}}, "location": {}}
    primary = {"signal_type": "opportunity.expansion_opportunity", "is_composite": True, "evidence": {},
               "dimensions": {"confidence": 0.9, "urgency": 0.5, "persistence": 0.5}}
    c = OV.build_card(primary=primary, all_types=[primary["signal_type"]], master=master, band="micro",
                      baseline=None, sector_baseline=SECTOR_A, sector_label="Agricultura", has_blocking_risk=False,
                      expected_year=2025, min_revenue=100_000)
    cmp = c["comparison"]
    assert cmp["scope"] == "sector" and cmp["position"] == "above_p50" and cmp["indicative"] is True
    assert cmp["text_es"] == ("Crece por encima de la mediana de empresas de su sector (0,8%), "
                              "sin llegar al cuarto superior (22,8%).")
    assert cmp["sample_note_es"] == "Comparativa con todo el sector, sin distinguir tamaño: 46 empresas."
    assert c["level"] == "candidate"                     # con suelo cumplido y compuesta, pero sin comparables por tamaño
    assert any("mismo tamaño" in m for m in c["missing_es"])
    # la comparativa por sector y tamaño tiene prioridad sobre la del sector completo
    c2 = OV.build_card(primary=primary, all_types=[primary["signal_type"]], master=master, band="micro",
                       baseline={"p50": 0.05, "p75": 0.09, "sample_size": 30}, sector_baseline=SECTOR_A,
                       sector_label="A", has_blocking_risk=False, expected_year=2025, min_revenue=100_000)
    assert c2["comparison"]["scope"] == "sector_size" and c2["level"] == "opportunity"


# ── defectos que solo aparecieron con datos reales (endpoint contra Mongo local, 2026-09-29) ──

def _real_card(history, baseline=BASE, latest_year=None):
    """Compuesta con comparables: la Oportunidad depende solo de estas reglas."""
    master = {"master_id": "m", "identity": {"legal_name": "X"}, "location": {},
              "financials": {"history": history, "latest": {"revenue": history[0]["revenue"], "year": history[0]["year"]}}}
    primary = {"signal_type": "opportunity.hidden_gem", "is_composite": True,
               "evidence": {"component_types": ["financial.margin_strong", "growth.sustained", "market.outperforms_peers"]},
               "dimensions": {"confidence": 0.9, "urgency": 0.5, "persistence": 0.5}}
    return OV.build_card(primary=primary, all_types=[primary["signal_type"]], master=master, band="micro",
                         baseline=baseline, sector_label="S", has_blocking_risk=False, expected_year=2025)


def test_growth_below_the_median_of_comparables_is_not_an_opportunity():
    """XOGUNA ECO: crecía un 3,2% frente a una mediana del 4,6% y salía como Oportunidad."""
    hist = [{"year": 2024, "revenue": 1319622.33}, {"year": 2023, "revenue": 1278339.0}, {"year": 2022, "revenue": 907620.0}]
    c = _real_card(hist, {"p50": 0.046, "p75": 0.1525, "sample_size": 47})
    assert c["comparison"]["position"] == "below_p50" and c["level"] == "candidate"
    hist_ok = [{"year": 2024, "revenue": 1500000.0}, {"year": 2023, "revenue": 1278339.0}, {"year": 2022, "revenue": 907620.0}]
    assert _real_card(hist_ok, {"p50": 0.046, "p75": 0.1525, "sample_size": 47})["level"] == "opportunity"


def test_old_accounts_cannot_be_an_opportunity():
    """SON BUGADELLAS: sus últimas cuentas son de 2020 y salía como Oportunidad."""
    hist = [{"year": 2020, "revenue": 1487546.67}, {"year": 2019, "revenue": 1263245.0}, {"year": 2017, "revenue": 1009707.0}]
    c = _real_card(hist, {"p50": -0.012, "p75": 0.128, "sample_size": 26})
    assert c["level"] == "candidate"
    assert any("Los últimos ingresos disponibles son de 2020" in m for m in c["missing_es"])
    assert any(x["code"] == "series_gap" for x in c["caveats"])         # faltan 2018


def test_gap_in_the_series_is_never_presented_as_annual_growth():
    hist = [{"year": 2020, "revenue": 1487546.67}, {"year": 2019, "revenue": 1263245.0}, {"year": 2017, "revenue": 1009707.0}]
    s = OV.revenue_series(hist)
    assert OV.yoy(s) == round(1487546.67 / 1263245.0 - 1, 4)             # 2019 -> 2020: consecutivos
    assert OV.yoy(s, back=1) is None                                     # 2017 -> 2019: hueco, no es interanual


def test_last_year_decline_is_flagged_on_a_growth_reading():
    """GURMIR: 'crecimiento sostenido' con un −59,8% en el último ejercicio."""
    hist = [{"year": 2024, "revenue": 9045.01}, {"year": 2023, "revenue": 22475.0}, {"year": 2022, "revenue": 2695.0}]
    codes = {c["code"]: c["text_es"] for c in OV.caveats(OV.revenue_series(hist))}
    assert codes["latest_decline"] == "Los ingresos del último ejercicio caen un 59,8%: contrasta con la lectura de crecimiento."
    assert "decelerating" not in codes                                   # no se dice "el ritmo baja a −59,8%"


if __name__ == "__main__":  # ejecución sin pytest
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("OK  ", name)
            except AssertionError as e:
                failed += 1; print("FAIL", name, "->", e)
    sys.exit(1 if failed else 0)
