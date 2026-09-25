from pathlib import Path
from tempfile import TemporaryDirectory
from services.engines.valuation.ecb_risk_free import parse_ecb_csv
from services.engines.valuation.public_comparables import load_export, normalize_rows
from services.engines.valuation.wacc import beta_from_comparables

def test_parses_latest_dated_ecb_observation():
    payload="TIME_PERIOD,OBS_VALUE\n2026-09-18,3.12\n2026-09-19,3.08\n"
    result=parse_ecb_csv(payload)
    assert result["observation_date"]=="2026-09-19"
    assert result["value"]==.0308
    assert result["status"]=="observed"

def test_normalizes_marketscreener_aliases_and_units():
    result=normalize_rows([{
      "Empresa":"Media SA","Ticker":"MED","Sector":"Media",
      "Beta":"1,20","Capitalización":"500M","Deuda financiera":"100M",
      "Enterprise Value":"580M","EBITDA":"50M","Ventas":"300M",
    }],"marketscreener","2026-09-20")
    row=result["records"][0]
    assert row["archetype"]=="media_content"
    assert row["market_cap"]==500_000_000
    assert row["quality"]["beta_ready"] is True
    assert row["quality"]["multiples_ready"] is True

def test_spanish_subsectors_map_to_arroba_archetypes():
    rows=[
      {"Empresa":"A","Subsector BME":"Inmobiliarias y Otros"},
      {"Empresa":"B","Subsector BME":"Productos farmaceúticos y Biotecnología"},
      {"Empresa":"C","Subsector BME":"Electrónica y Software"},
    ]
    result=normalize_rows(rows,"marketscreener","2025-12-31")["records"]
    assert [r["archetype"] for r in result]==["real_estate","healthcare","software_data"]


def test_ev_ebit_is_derived_when_source_components_exist():
    row=normalize_rows([{"Empresa":"X","Enterprise Value":120,"EBIT":10}],
                       "marketscreener","2025-12-31")["records"][0]
    assert row["ev_ebit"]==12

def test_marketscreener_spanish_direct_multiples():
    result=normalize_rows([{
      "Empresa":"Prisa","ISIN":"ES0171743901","Sector BME":"Servicios de Consumo",
      "Subsector BME":"Medios de Comunicación y Publicidad",
      "PER 2025":"12,5","VE/EBITDA 2025":7.2,"VE/ventas 2025":1.1,
      "P/VC 2025":2.0,"Fuente MarketScreener":"https://example.test/valoracion/",
    }],"marketscreener","2025-12-31")
    row=result["records"][0]
    assert row["subsector"]=="Medios de Comunicación y Publicidad"
    assert row["archetype"]=="media_content"
    assert row["per"]==12.5
    assert row["ev_ebitda"]==7.2
    assert row["quality"]["multiples_ready"] is True
    assert row["source_url"].endswith("/valoracion/")

def test_xlsx_loader_finds_decorated_header_row():
    from openpyxl import Workbook
    with TemporaryDirectory() as directory:
        path=Path(directory)/"marketscreener.xlsx"
        workbook=Workbook()
        summary=workbook.active
        summary.title="Medianas"
        summary.append(["Resumen"])
        companies=workbook.create_sheet("Empresas")
        companies.append(["Múltiplos de empresas cotizadas"])
        companies.append([])
        companies.append(["Empresa","ISIN","Sector BME","PER 2025"])
        companies.append(["Media SA","ES0000000001","Medios",10.0])
        workbook.save(path)
        result=load_export(path,"marketscreener","2025-12-31")
        assert result["source_sheet"]=="Empresas"
        assert result["header_row"]==3
        assert result["record_count"]==1
        assert result["records"][0]["per"]==10.0
