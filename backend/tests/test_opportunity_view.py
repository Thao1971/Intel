"""Tests unitarios (sin backend ni base de datos) de services/opportunity_view.py.

Las series son las REALES de Arroba-pro (lectura del 2026-09-29) de seis empresas que ya
aparecían en la pantalla Oportunidades; cubren cada regla: dato erróneo, rebote, desaceleración,
base pequeña, composición y comparativa con baseline.

    python -m pytest backend/tests/test_opportunity_view.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import opportunity_view as OV  # noqa: E402

# history viene del más reciente al más antiguo, como en master_companies.financials.history
POIMA = [{"year": 2024, "revenue": 526515.33}, {"year": 2023, "revenue": -13205.72}, {"year": 2022, "revenue": 2598.54}]
KRZ = [{"year": 2025, "revenue": 2593865.39}, {"year": 2024, "revenue": 2106134.98}, {"year": 2023, "revenue": 2603087.54}]
BLAYA = [{"year": 2025, "revenue": 151155.25}, {"year": 2024, "revenue": 104400.08}, {"year": 2023, "revenue": 138961.48}]
ESTIVIEL = [{"year": 2025, "revenue": 551172.47}, {"year": 2024, "revenue": 497669.89}, {"year": 2023, "revenue": 156947.2}]
ROJAS = [{"year": 2024, "revenue": 273462.92}, {"year": 2023, "revenue": 127413.94}, {"year": 2022, "revenue": 40843.02}]
SACASA = [{"year": 2024, "revenue": 12165640.77}, {"year": 2023, "revenue": 8170501.37}, {"year": 2022, "revenue": 9599789.02}]

BASE_C_SMALL = {"p50": 0.0198, "p75": 0.0641, "sample_size": 13}
BASE_G_MICRO = {"p50": 0.046, "p75": 0.1525, "sample_size": 47}


def _card(history, signal_type, evidence=None, composite=False, baseline=None, risk=False, all_types=None):
    master = {"master_id": "mc_x", "identity": {"legal_name": "X"},
              "financials": {"history": history, "latest": {"revenue": history[0]["revenue"], "year": history[0]["year"]}},
              "location": {"provincia": "MADRID"}}
    primary = {"signal_id": "s1", "signal_type": signal_type, "evidence": evidence or {},
               "is_composite": composite, "dimensions": {"confidence": 0.88, "urgency": 0.5, "persistence": 0.5}}
    return OV.build_card(primary=primary, all_types=all_types or [signal_type], master=master, band="micro",
                         baseline=baseline, sector_label="Sector", has_blocking_risk=risk, expected_year=2025)


def test_series_is_chronological_and_capped():
    s = OV.revenue_series(KRZ + [{"year": 2022, "revenue": 1.0}], years=3)
    assert [p["year"] for p in s] == [2023, 2024, 2025]


def test_poima_negative_revenue_is_verify_not_opportunity():
    c = _card(POIMA, "opportunity.expansion_opportunity", composite=True)
    assert c["level"] == "verify"
    assert c["data_issue"]["years"] == [2023]
    assert c["headline_es"] is None and c["comparison"] is None and c["caveats"] == []
    assert "negativos" in c["data_issue"]["text_es"]


def test_krz_rebound_and_comparison_above_p75():
    c = _card(KRZ, "growth.revenue_surge", {"metric": "revenue_growth_yoy", "value": 0.2316}, baseline=BASE_C_SMALL)
    assert c["level"] == "indicio"
    assert c["headline_es"] == "Los ingresos suben un 23,2% en 2025, tras haber caído un 19,1% el año anterior."
    assert c["caveats"][0]["code"] == "rebound" and "−0,4%" in c["caveats"][0]["text_es"]
    assert c["comparison"]["position"] == "above_p75" and c["comparison"]["indicative"] is True


def test_blaya_net_two_year_and_reliable_sample():
    c = _card(BLAYA, "growth.revenue_surge", {"value": 0.4478}, baseline=BASE_G_MICRO)
    assert c["caveats"][0]["code"] == "rebound" and "+8,8%" in c["caveats"][0]["text_es"]
    assert c["comparison"]["indicative"] is False and c["comparison"]["sample_size"] == 47


def test_estiviel_decelerating_headline():
    c = _card(ESTIVIEL, "growth.sustained", {"metric": "revenue_cagr", "value": 0.874})
    assert c["headline_es"] == ("Los ingresos se multiplican por 3,5 en 2 años (+87,4% anual compuesto), "
                                "aunque el último año se moderó.")
    assert [x["code"] for x in c["caveats"]] == ["decelerating"]
    assert c["comparison"] is None


def test_rojas_small_base_but_not_decelerating():
    c = _card(ROJAS, "growth.sustained", {"value": 1.5876})
    assert [x["code"] for x in c["caveats"]] == ["small_base"]
    assert "6,7" in c["headline_es"] and "+158,8%" in c["headline_es"]


def test_sacasa_composite_is_candidate_and_lists_what_is_missing():
    c = _card(SACASA, "opportunity.expansion_opportunity", composite=True)
    assert c["level"] == "candidate"
    assert c["headline_es"].startswith("Los ingresos suben un 48,9% en 2024")
    assert any("Comparar el crecimiento" in m for m in c["missing_es"])
    assert any("ejercicio 2025" in m for m in c["missing_es"])


def test_opportunity_requires_composite_comparison_and_no_blocking_risk():
    ok = _card(KRZ, "opportunity.expansion_opportunity", composite=True, baseline=BASE_C_SMALL)
    assert ok["level"] == "opportunity" and ok["missing_es"] == []
    blocked = _card(KRZ, "opportunity.expansion_opportunity", composite=True, baseline=BASE_C_SMALL, risk=True)
    assert blocked["level"] == "candidate"
    plain = _card(KRZ, "growth.revenue_surge", {"value": 0.2316}, baseline=BASE_C_SMALL)
    assert plain["level"] == "indicio"


def test_zero_revenue_year_is_flagged():
    h = [{"year": 2024, "revenue": 500000.0}, {"year": 2023, "revenue": 0.0}, {"year": 2022, "revenue": 100000.0}]
    assert OV.data_issue(OV.revenue_series(h))["text_es"].startswith("Los ingresos de 2023 constan como nulos")


def test_chips_and_words_and_formats():
    assert [c["enum"] for c in OV.thesis_chips(["ownership.consolidator", "growth.sustained"])] == \
        ["buy_and_build", "growth"]
    assert [OV.word_es(v) for v in (0.95, 0.85, 0.5, 0.4)] == ["Muy alta", "Alta", "Media", "Baja"]
    assert OV.eur_es(12165640.77) == "12 M€" and OV.eur_es(2593865) == "2,6 M€" and OV.eur_es(41_200_000_000) == "41.200 M€" and OV.eur_es(1_000_000) == "1 M€" and OV.eur_es(273462.9) == "273 k€" and OV.eur_es(-13205.7) == "−13 k€"
    assert OV.pct_es(-0.0004) == "0,0%" and OV.pct_es(0.0003, signed=True) == "0,0%" and OV.pct_es(0.4478) == "44,8%" and OV.pct_es(-0.191) == "−19,1%" and OV.pct_es(0.874, signed=True) == "+87,4%"


# ── tipos sin serie de ingresos: evidencia REAL leída de Arroba-pro (2026-09-29) ──

SUCCESSION_EV = {"metric": "administrator_tenure_years", "value": 24.6, "window": "latest",
                 "person_role": "Administrador Único", "appointment_date": "30/11/2001",
                 "succession_profile": {"admin_count": 1, "family_business_probable": False,
                                        "successor_candidate": {"person_name": "GABRIEL SANCHEZ DE FRUTOS RAMON",
                                                                "role": "Apoderado", "appointment_date": "23/12/2003"}}}
HOLDING_NO_REVENUE = [{"year": 2024, "revenue": 0.0}, {"year": 2023, "revenue": 0.0}, {"year": 2022, "revenue": 0.0}]


def test_consolidator_headline_and_holding_with_zero_revenue_is_not_flagged():
    c = _card(HOLDING_NO_REVENUE, "ownership.consolidator", {"metric": "investees_count", "value": 16})
    assert c["headline_es"] == "Participa en 16 sociedades: perfil compatible con una plataforma de consolidación."
    assert c["level"] == "indicio" and c["data_issue"] is None       # una holding sin ingresos es normal
    assert c["perspective"] == "acquirer"
    assert c["caveats"][0]["code"] == "holding_or_acquirer"
    assert c["comparison"] is None and c["missing_es"][0].startswith("Confirmar si actúa como compradora")
    # con pocas participadas no se habla de "plataforma" (el 52 % de los consolidadores reales tiene 2-4)
    assert OV.headline("ownership.consolidator", {"value": 1}, [], []) == \
        "Participa en una sociedad: posible matriz de un pequeño grupo de participadas."
    assert OV.headline("ownership.consolidator", {"value": 2}, [], []).endswith("pequeño grupo de participadas.")
    assert OV.headline("ownership.consolidator", {"value": 5}, [], []).endswith("plataforma de consolidación.")


def test_succession_headline_names_no_person():
    c = _card(HOLDING_NO_REVENUE, "opportunity.succession_signal", SUCCESSION_EV)
    assert c["headline_es"] == "Administrador único con 24,6 años en el cargo (desde 2001): posible relevo generacional."
    assert c["caveats"][0]["code"] == "successor_identified"
    assert "apoderado" in c["caveats"][0]["text_es"]
    assert "GABRIEL" not in str(c)                                    # RGPD: sin nombres de personas
    assert c["chips"] == [{"enum": "succession", "label_es": "Relevo generacional", "basis": "opportunity.succession_signal"}]
    fam = dict(SUCCESSION_EV, succession_profile={"family_business_probable": True})
    assert OV.headline("opportunity.succession_signal", fam, [], []).endswith("Con rasgos de empresa familiar.")


def test_hidden_gem_uses_only_component_types_and_optional_margin():
    ev = {"component_types": ["financial.margin_strong", "growth.sustained", "market.outperforms_peers",
                              "market.fragmented_sector"]}
    assert OV.headline("opportunity.hidden_gem", ev, [], [], {"ebitda_margin": 0.183}) == (
        "Combina un margen EBITDA del 18,3%, en el cuarto superior de sus comparables, y un crecimiento "
        "sostenido, en un sector fragmentado.")
    ev2 = {"component_types": ["financial.margin_strong", "growth.sustained", "market.outperforms_peers"]}
    assert OV.headline("opportunity.hidden_gem", ev2, [], [], {"ebitda_margin": None}) == (
        "Combina un margen en el cuarto superior de sus comparables y un crecimiento sostenido.")


def test_consolidation_candidate_and_potential_distress():
    base = {"component_types": ["growth.sustained", "financial.margin_strong", "ownership.consolidator"]}
    assert OV.headline("opportunity.consolidation_candidate", base, [], []) == (
        "Combina un crecimiento sostenido, márgenes sólidos y participaciones en otras sociedades: "
        "perfil de actor consolidador.")
    assert OV.headline("opportunity.consolidation_candidate",
                       {"component_types": base["component_types"] + ["transaction.ma_event"]}, [], []).endswith(
        "con al menos una operación de M&A registrada.")
    d = {"component_types": ["financial.net_loss", "financial.high_leverage", "financial.low_liquidity"]}
    assert OV.headline("opportunity.potential_distress", d, [], []) == (
        "Cierra con pérdidas netas y un endeudamiento elevado, con liquidez ajustada: "
        "posible situación especial o de reestructuración.")


def test_every_signal_type_of_the_opportunity_list_has_a_headline():
    cases = {
        "ownership.consolidator": {"value": 3}, "opportunity.succession_signal": SUCCESSION_EV,
        "opportunity.hidden_gem": {"component_types": []}, "opportunity.consolidation_candidate": {"component_types": []},
        "growth.revenue_surge": {"value": 0.3}, "growth.sustained": {"value": 0.3},
        "opportunity.expansion_opportunity": {}, "opportunity.potential_distress": {"component_types": []},
    }
    for stype, ev in cases.items():
        assert OV.headline(stype, ev, OV.revenue_series(KRZ), []) is not None, stype


def test_new_thesis_chips_cite_their_basis():
    chips = {c["enum"]: c["basis"] for c in OV.thesis_chips(
        ["opportunity.expansion_opportunity", "opportunity.hidden_gem", "opportunity.consolidation_candidate",
         "growth.revenue_surge"])}
    assert chips == {"growth": "growth.*", "expansion": "opportunity.expansion_opportunity",
                     "quality_growth": "opportunity.hidden_gem",
                     "consolidator_platform": "opportunity.consolidation_candidate"}


def test_special_situation_is_its_own_level_and_not_verify_for_zero_revenue():
    ev = {"component_types": ["financial.net_loss", "financial.high_leverage"]}
    c = _card(HOLDING_NO_REVENUE, "opportunity.potential_distress", ev, composite=True)
    assert c["level"] == "special" and c["level_label_es"] == "Situación especial"
    assert c["perspective"] == "target" and c["data_issue"] is None
    assert [x["enum"] for x in c["chips"]] == ["special_situation"]
    assert c["missing_es"] == ["Revisar la deuda financiera y su calendario de vencimientos"]


def test_operational_turnaround_and_group_subsidiary():
    ev = {"component_types": ["financial.margin_weak", "operational.productivity_low", "market.underperforms_peers"]}
    assert OV.headline("opportunity.operational_turnaround", ev, [], [], {"ebitda_margin": 0.031}) == (
        "Margen EBITDA del 3,1% y productividad por debajo de lo habitual, sin pérdidas netas ni patrimonio neto "
        "negativo, y por debajo de sus comparables: margen de mejora operativa.")
    assert OV.headline("opportunity.operational_turnaround",
                       {"component_types": ev["component_types"][:2]}, [], [], {}) .startswith("Márgenes débiles y productividad")
    assert OV.headline("opportunity.group_subsidiary", {"component_types": ["ownership.group_member"]}, [], []) == (
        "Forma parte de un grupo societario: posible desinversión o reorganización.")
    assert OV.headline("opportunity.group_subsidiary",
                       {"component_types": ["ownership.group_member", "ownership.foreign_parent"]}, [], []).endswith(
        "con matriz extranjera: posible desinversión o reorganización.")
    c = _card(HOLDING_NO_REVENUE, "opportunity.operational_turnaround", ev, composite=True)
    assert c["level"] == "candidate" and c["comparison"] is None
    assert [x["enum"] for x in c["chips"]] == ["turnaround"] and len(c["missing_es"]) == 2


if __name__ == "__main__":  # ejecución sin pytest
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK  ", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, "->", e)
    sys.exit(1 if failed else 0)
