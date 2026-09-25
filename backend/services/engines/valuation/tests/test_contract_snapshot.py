import json
from pathlib import Path

from routes.engine_schemas import ValuationPackageResponse


SNAPSHOT = Path(__file__).resolve().parents[4] / "contracts" / "intel-beta-valuation.v1.schema.json"


def test_intel_beta_contract_snapshot_matches_typed_model():
    expected = ValuationPackageResponse.model_json_schema(ref_template="#/$defs/{model}")
    expected["$id"] = "https://arroba.com/contracts/intel-beta-valuation.v1.schema.json"
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert json.loads(SNAPSHOT.read_text()) == expected


def test_intel_beta_contract_requires_all_presentation_sections():
    schema = json.loads(SNAPSHOT.read_text())
    package = schema["$defs"]["ValuationPackage"]
    required = set(package["required"])
    assert {"summary", "methods", "scenarios", "assumptions", "comparables",
            "confidence", "sources_and_versions"} <= required
