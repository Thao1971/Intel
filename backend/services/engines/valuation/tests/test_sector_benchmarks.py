from pathlib import Path
from tempfile import TemporaryDirectory
from openpyxl import Workbook
from services.engines.valuation.sector_benchmarks import (
    load_sector_benchmark, select_benchmark,
)

def _workbook(path):
    wb=Workbook()
    wb.active.title="Resumen"
    ws=wb.create_sheet("Sectores")
    ws.append(["Industria Damodaran","Grupo Arroba","Método principal","Empresas",
               "% con pérdidas","PER actual","PER trailing","PER forward","P/VC",
               "ROE","P/ventas","VE/ventas","Margen operativo",
               "VE/EBITDA positivo","VE/EBITDA todas","VE/EBIT"])
    ws.append(["Advertising","Medios y publicidad","VE/EBITDA y VE/ventas",83,
               .44,20,18,15,2,.12,1.0,1.3,.10,8.4,9.1,11])
    ws.append(["Broadcasting","Medios y publicidad","VE/EBITDA y VE/ventas",18,
               .20,16,14,13,1.5,.10,.8,.9,.08,7.5,8.0,10])
    wb.save(path)

def test_loads_regional_sector_workbook():
    with TemporaryDirectory() as directory:
        path=Path(directory)/"eu.xlsx"
        _workbook(path)
        result=load_sector_benchmark(path,"europe","2026-01-05")
        assert result["record_count"]==2
        assert result["records"][0]["archetype"]=="advertising"
        assert result["records"][0]["metrics"]["ev_ebitda"]==8.4

def test_selects_archetype_benchmark_with_traceability():
    records=[
        {"archetype":"media_content","industry":"Broadcasting","region":"europe",
         "provider":"damodaran","as_of":"2026-01-05","company_count":18,
         "metrics":{"ev_ebitda":7.5}},
        {"archetype":"media_content","industry":"Publishing & Newspapers","region":"europe",
         "provider":"damodaran","as_of":"2026-01-05","company_count":30,
         "metrics":{"ev_ebitda":9.5}},
    ]
    result=select_benchmark(records,"media_content","ev_ebitda")
    assert result["multiple"]==8.5
    assert result["company_count"]==48
    assert result["status"]=="observed_sector_benchmark"
