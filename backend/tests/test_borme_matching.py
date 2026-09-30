"""Tests unitarios (sin backend ni base de datos): emparejamiento de eventos BORME con el Master y formato
de fecha real de los eventos (YYYYMMDD).

    python -m pytest backend/tests/test_borme_matching.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import borme_matching as BM  # noqa: E402
from services import officer_utils as OU  # noqa: E402


def key_fn(n):   # equivalente simplificado de services.data_layer.normalize.name_key
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (n or "").lower())).strip() or None


def _ev(i, name, prov=None, text=""):
    return {"idempotency_key": f"k{i}", "company_name_normalized": name, "registry_province": prov, "event_text_raw": text}


MASTERS = {
    "carnicas mirotz": [{"master_id": "m1", "provincia": "ALAVA", "cif": "B01234567"}],
    "talleres perez": [{"master_id": "m2", "provincia": "MADRID", "cif": "B11111111"},
                       {"master_id": "m3", "provincia": "SEVILLA", "cif": "B22222222"}],
}


def test_unique_name_links_and_province_boosts_confidence():
    links, st = BM.match_events([_ev(1, "CARNICAS MIROTZ", "ARABA/ÁLAVA")], MASTERS, key_fn)
    assert links == [{"idempotency_key": "k1", "master_id": "m1", "confidence": 0.88, "method": "name_exact"}]
    assert st == {"examined": 1, "linked": 1, "no_match": 0, "ambiguous": 0}
    links, _ = BM.match_events([_ev(2, "CARNICAS MIROTZ", "MADRID")], MASTERS, key_fn)
    assert links[0]["confidence"] == 0.80


def test_unknown_company_is_not_linked():
    links, st = BM.match_events([_ev(1, "EMPRESA QUE NO TENEMOS")], MASTERS, key_fn)
    assert links == [] and st["no_match"] == 1


def test_ambiguous_name_is_resolved_by_cif_then_province_else_skipped():
    links, _ = BM.match_events([_ev(1, "TALLERES PEREZ", "BARCELONA", "... CIF B22222222 ...")], MASTERS, key_fn)
    assert links[0]["master_id"] == "m3" and links[0]["method"] == "cif_exact" and links[0]["confidence"] == 0.95
    links, _ = BM.match_events([_ev(2, "TALLERES PEREZ", "SEVILLA")], MASTERS, key_fn)
    assert links[0]["master_id"] == "m3" and links[0]["method"] == "name_province"
    links, st = BM.match_events([_ev(3, "TALLERES PEREZ", "BARCELONA")], MASTERS, key_fn)   # nadie desempata
    assert links == [] and st["ambiguous"] == 1


def test_borme_dates_use_the_real_yyyymmdd_format():
    d = OU.parse_borme_date("20260723")
    assert (d.year, d.month, d.day) == (2026, 7, 23)
    assert OU.parse_borme_date("2026-07-23") == d and OU.parse_borme_date("xx") is None and OU.parse_borme_date(None) is None
    # el corte de la ventana de 24 meses debe poder compararse como texto con publication_date
    assert re.fullmatch(r"\d{8}", __import__("datetime").datetime(2024, 9, 29).strftime("%Y%m%d"))
    assert "20260723" >= "20240929" and "20240101" < "20240929"


if __name__ == "__main__":  # ejecución sin pytest
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("OK  ", name)
            except AssertionError as e:
                failed += 1; print("FAIL", name, "->", e)
    sys.exit(1 if failed else 0)
