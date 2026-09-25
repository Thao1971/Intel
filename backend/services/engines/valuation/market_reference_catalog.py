"""Versioned market-reference catalogue served by the valuation back office."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[4]
_MARKET = _ROOT / "data" / "valuation" / "market"
_FILES = {
    "public_spain": _MARKET / "marketscreener" / "public_comparable_snapshots_spain_2025.json",
    "public_history": _MARKET / "damodaran" / "public_comparable_history_international_2020_2025.json",
    "private_transactions": _MARKET / "private_transactions" / "private_transaction_reference_southern_europe_h1_2026.json",
}


def _normalise(value: Optional[str]) -> Optional[str]:
    return value.strip().casefold() if value else None


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict[str, Any]]:
    return {name: json.loads(path.read_text(encoding="utf-8")) for name, path in _FILES.items()}


def validate_market_reference_catalog() -> dict[str, int]:
    data = _load_all()
    required = ("public_spain", "public_history", "private_transactions")
    if any(name not in data for name in required):
        raise ValueError("Incomplete market reference catalogue")
    counts = {
        "public_spain_snapshots": len(data["public_spain"].get("snapshots", [])),
        "public_history_points": len(data["public_history"].get("points", [])),
        "private_transaction_categories": len(data["private_transactions"].get("categories", [])),
        "private_transaction_size_points": len(data["private_transactions"].get("size_curve", {}).get("observations", [])),
    }
    if not all(counts.values()):
        raise ValueError(f"Invalid empty market reference catalogue: {counts}")
    return counts


def market_reference_catalog(
    *, category: Optional[str] = None, region: Optional[str] = None, include_history: bool = True
) -> dict[str, Any]:
    """Return canonical, versioned sources used by the market-reference screens.

    The catalogue intentionally keeps listed-company observations and private
    transactions as distinct evidence layers. The reconciliation engine decides
    their weighting for a specific company; this endpoint does not manufacture a
    blended market multiple.
    """
    data = _load_all()
    category_key, region_key = _normalise(category), _normalise(region)

    aliases = {
        "inmobiliario": "real_estate",
        "medios y publicidad": "media_content",
        "construcción e ingeniería": "construction",
        "energia": "energy_utilities",
        "energía": "energy_utilities",
    }
    requested = aliases.get(category_key, category_key)

    def matches(item: dict[str, Any]) -> bool:
        labels = (item.get("category"), item.get("archetype"), item.get("source_sector"))
        return not category_key or any(
            _normalise(label) in {category_key, requested} for label in labels if label
        )

    spain = [item for item in data["public_spain"].get("snapshots", []) if matches(item)]
    history = [item for item in data["public_history"].get("points", []) if matches(item)]
    if region_key:
        history = [item for item in history if _normalise(item.get("region")) == region_key]
    private = [item for item in data["private_transactions"].get("categories", []) if matches(item)]

    return {
        "catalog_version": "market-reference-catalog-v1",
        "integrity": validate_market_reference_catalog(),
        "public_listed": {
            "as_of": data["public_spain"].get("as_of"),
            "snapshot_version": data["public_spain"].get("snapshot_version"),
            "region": data["public_spain"].get("region"),
            "references": spain,
        },
        "public_history": {
            "history_version": data["public_history"].get("history_version"),
            "coverage": data["public_history"].get("coverage"),
            "points": history if include_history else [],
        },
        "private_transactions": {
            "reference_version": data["private_transactions"].get("reference_version"),
            "as_of": data["private_transactions"].get("as_of"),
            "region": data["private_transactions"].get("region"),
            "scope": data["private_transactions"].get("scope"),
            "metric": data["private_transactions"].get("metric"),
            "size_curve": data["private_transactions"].get("size_curve"),
            "references": private,
        },
    }
