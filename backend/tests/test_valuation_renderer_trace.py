from documents.renderers.valuation_renderer import _valuation_trace_block


def test_trace_discloses_source_adjustments_and_missing_evidence():
    html = _valuation_trace_block({
        "method": "ev_ebitda",
        "multiple_benchmark": {
            "metric": "ev_ebitda", "source_level": "europe_listed",
            "providers": ["damodaran"], "regions": ["Europe"],
            "company_count": 83, "as_of": "2026-01-05",
            "industries": ["Advertising"],
        },
        "private_company_adjustment": {
            "public_multiple": 8.4117, "adjusted_multiple": 7.78,
            "total_adjustment": -.075,
            "components": [
                {"factor": "size", "basis": "medium", "adjustment": -.05},
                {"factor": "audited_accounts", "basis": True, "adjustment": .025},
            ],
            "unavailable_evidence": ["largest_customer_pct"],
        },
    })
    assert "8.41x" in html
    assert "7.78x" in html
    assert "83 compañías" in html
    assert "principal cliente" in html
    assert "no se aplica descuento" in html
