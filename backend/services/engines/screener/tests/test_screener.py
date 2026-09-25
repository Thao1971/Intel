from services.engines.screener import screener as S


def test_employee_filter_uses_canonical_size_path():
    match, groups = S._build_match({"employees_min": 10, "employees_max": 50})
    assert match["size.employees_total"] == {"$gte": 10, "$lte": 50}
    assert groups == []


def test_query_is_regex_escaped_and_covers_current_identity_shape():
    match, _ = S._build_match({"query": "A+B (SL)"})
    choices = match["$and"][0]["$or"]
    assert choices[0]["identity.legal_name"]["$regex"] == r"A\+B\ \(SL\)"
    assert any("identity.commercial_name" in item for item in choices)
    assert any("identity.aliases" in item for item in choices)


def test_growth_pipeline_has_no_mongodb_52_sortarray_dependency():
    stages = S._growth_stages(0.1, None, True)
    assert "$sortArray" not in repr(stages)
    assert any("growth_yoy" in repr(stage) for stage in stages)


def test_signal_filter_uses_lookup_instead_of_large_master_id_list():
    match, groups = S._build_match({"signals": ["growth"], "estado": "all"})
    assert "master_id" not in repr(match)
    stages = S._signal_filter_stages(groups)
    assert stages[0].get("$lookup", {}).get("from") == "signals"
