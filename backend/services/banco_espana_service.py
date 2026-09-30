"""Banco de España Connector — Macro-financial indicators from BDE official API and CSV datasets.

API endpoint: https://app.bde.es/bierest/resources/srdatosapp/favoritas (latest values)
CSV datasets: https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ (historical)

Phase 1 indicators:
- Euribor 12M/6M/3M/1M
- BCE main refinancing rate
- Credit to private sector (OSR)

NPL/Morosidad: NOT available via public API at aggregated level.
Requires CIRBE (restricted) or EBA reporting (separate source).
"""

import logging
import csv
import io
import re
import httpx
from datetime import datetime, timezone
from pymongo import UpdateOne
from typing import Optional, List, Dict
from database import db
from models import new_id, now_iso

logger = logging.getLogger(__name__)

BDE_API = "https://app.bde.es/bierest/resources/srdatosapp/favoritas"
BDE_CSV_BASE = "https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv"

# Series mapping: internal key → BDE series ID → display config
INDICATOR_MAP = {
    "euribor_12m": {
        "series_id": "D_1NBAF472", "name": "Euribor 12 meses",
        "category": "interest_rates", "unit": "%", "frequency": "monthly",
        "display_priority": 1, "homepage": True,
        "description": "Tipo de interes interbancario europeo a 12 meses. Referencia principal para hipotecas y financiacion empresarial.",
    },
    "euribor_6m": {
        "series_id": "D_1NBAE472", "name": "Euribor 6 meses",
        "category": "interest_rates", "unit": "%", "frequency": "monthly",
        "display_priority": 5, "homepage": False,
        "description": "Tipo de interes interbancario europeo a 6 meses.",
    },
    "euribor_3m": {
        "series_id": "D_1NBAD472", "name": "Euribor 3 meses",
        "category": "interest_rates", "unit": "%", "frequency": "monthly",
        "display_priority": 5, "homepage": False,
        "description": "Tipo de interes interbancario europeo a 3 meses.",
    },
    "euribor_1m": {
        "series_id": "D_1NBAC372", "name": "Euribor 1 mes",
        "category": "interest_rates", "unit": "%", "frequency": "monthly",
        "display_priority": 5, "homepage": False,
        "description": "Tipo de interes interbancario europeo a 1 mes.",
    },
    "bce_main_rate": {
        "series_id": "D_1TFK09A0_BCE", "name": "Tipo BCE operaciones principales",
        "category": "policy_rates", "unit": "%", "frequency": "monthly",
        "display_priority": 2, "homepage": True,
        "description": "Tipo de interes del BCE para operaciones principales de financiacion. Referencia clave de politica monetaria.",
    },
    "credit_private_sector": {
        "series_id": "DF_MESNAA20A1U62200Z01E", "name": "Credito al sector privado",
        "category": "credit", "unit": "M EUR", "frequency": "monthly",
        "display_priority": 3, "homepage": True,
        "description": "Volumen total de prestamos y creditos de OIFM a otros sectores residentes no IFM (incluye empresas y hogares).",
    },
}

# CSV file → series columns mapping (for historical ingestion)
CSV_SOURCES = {
    "be0115": {
        "url": f"{BDE_CSV_BASE}/be0115.csv",
        "series": ["D_1TFK09A0_BCE", "D_1NBAC372", "D_1NBAD472", "D_1NBAE472", "D_1NBAF472"],
    },
}

# Month name mapping for BDE CSV date parsing
MONTH_MAP = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12",
}


async def fetch_latest_indicators() -> List[Dict]:
    """Fetch latest values for all configured indicators from BDE API."""
    series_codes = ",".join(m["series_id"] for m in INDICATOR_MAP.values())

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(BDE_API, params={"idioma": "es", "series": series_codes},
                             headers={"Accept": "application/json"}, follow_redirects=True)
        r.raise_for_status()
        data = r.json()

    if not isinstance(data, list):
        return []

    results = []
    series_to_key = {m["series_id"]: k for k, m in INDICATOR_MAP.items()}

    for item in data:
        if "errNum" in item:
            continue
        series_id = item.get("serie")
        indicator_key = series_to_key.get(series_id)
        if not indicator_key:
            continue

        config = INDICATOR_MAP[indicator_key]
        results.append({
            "source": "banco_espana",
            "source_series_id": series_id,
            "indicator_key": indicator_key,
            "indicator_name": config["name"],
            "category": config["category"],
            "frequency": config["frequency"],
            "unit": item.get("simbolo", config["unit"]),
            "value": item.get("valor"),
            "trend": item.get("tendencia"),
            "period": item.get("fechaValor"),
            "date": item.get("fechaValor"),
            "description_short": item.get("descripcionCorta"),
            "display_priority": config.get("display_priority", 10),
            "homepage": config.get("homepage", False),
        })

    return results


async def fetch_historical_csv(csv_id: str = "be0115", recent_months: Optional[int] = None) -> Dict:
    """Fetch and parse historical data from BDE CSV dataset."""
    config = CSV_SOURCES.get(csv_id)
    if not config:
        return {"status": "error", "error": f"Unknown CSV: {csv_id}"}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(config["url"], headers={"Accept": "text/csv"})
        r.raise_for_status()

    content = r.text
    if content.startswith("<!DOCTYPE") or content.startswith("<html"):
        return {"status": "error", "error": "BDE returned HTML instead of CSV"}

    lines = content.split("\n")
    if len(lines) < 5:
        return {"status": "error", "error": "CSV too short"}

    # Parse BDE CSV format: row 0=codes, 1=aliases, 2=units, 3=descriptions, 4+=data
    codes = [c.strip('"').strip() for c in lines[0].split(",")]
    series_to_key = {m["series_id"]: k for k, m in INDICATOR_MAP.items()}

    # Find column indices for our target series
    col_map = {}
    for i, code in enumerate(codes):
        if code in series_to_key:
            col_map[i] = series_to_key[code]

    if not col_map:
        return {"status": "error", "error": "No target series found in CSV"}

    now = now_iso()
    ops = []
    cutoff = None
    if recent_months:
        d = datetime.now(timezone.utc)
        total = d.year * 12 + (d.month - 1) - recent_months
        cutoff = f"{total // 12}-{total % 12 + 1:02d}-01"

    for line in lines[4:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue

        date_str = parts[0].strip('"').strip()
        if not date_str or date_str in ("FUENTE", "NOTAS", ""):
            continue

        # Parse date: "ENE 2024" → "2024-01-01"
        parsed_date = _parse_bde_date(date_str)
        if not parsed_date or (cutoff and parsed_date[:10] < cutoff):
            continue

        for col_idx, indicator_key in col_map.items():
            if col_idx >= len(parts):
                continue
            val_str = parts[col_idx].strip('"').strip()
            if not val_str or val_str == "":
                continue
            try:
                value = float(val_str.replace(",", "."))
            except ValueError:
                continue

            config = INDICATOR_MAP[indicator_key]

            ops.append(UpdateOne(
                {"indicator_key": indicator_key, "date": parsed_date, "source": "banco_espana"},
                {"$set": {
                    "source": "banco_espana",
                    "source_series_id": config["series_id"],
                    "indicator_key": indicator_key,
                    "indicator_name": config["name"],
                    "category": config["category"],
                    "frequency": config["frequency"],
                    "unit": config["unit"],
                    "value": value,
                    "date": parsed_date,
                    "period": date_str,
                    "display_priority": config.get("display_priority", 10),
                    "homepage": config.get("homepage", False),
                    "source_url": CSV_SOURCES[csv_id]["url"],
                    "last_updated_at": now,
                    "status": "ok",
                }},
                upsert=True,
            ))

    inserted = updated = 0
    if ops:
        res = await db.macro_indicators.bulk_write(ops, ordered=False)
        inserted = res.upserted_count
        updated = res.matched_count

    # _compute_changes() lo ejecuta refresh_all_indicators una sola vez

    return {"status": "completed", "csv": csv_id, "inserted": inserted, "updated": updated}


def _parse_bde_date(date_str: str) -> Optional[str]:
    """Parse BDE date format: 'ENE 2024' → '2024-01-01T00:00:00Z'"""
    parts = date_str.strip().split()
    if len(parts) != 2:
        return None
    month_str, year_str = parts
    month = MONTH_MAP.get(month_str.upper())
    if not month:
        return None
    try:
        year = int(year_str)
        return f"{year}-{month}-01T00:00:00Z"
    except ValueError:
        return None


async def _compute_changes():
    """Compute YoY and MoM changes for all indicators."""
    for key in INDICATOR_MAP:
        history = await db.macro_indicators.find(
            {"indicator_key": key, "source": "banco_espana"},
            {"_id": 0, "date": 1, "value": 1}
        ).sort("date", -1).limit(15).to_list(15)

        if len(history) < 2:
            continue

        latest = history[0]
        prev_month = history[1] if len(history) > 1 else None
        prev_year = history[12] if len(history) > 12 else None

        update = {}
        if prev_month and prev_month["value"]:
            update["previous_value"] = prev_month["value"]
            update["change_abs"] = round(latest["value"] - prev_month["value"], 4)
            if prev_month["value"] != 0:
                update["change_pct"] = round((latest["value"] - prev_month["value"]) / abs(prev_month["value"]) * 100, 2)

        if prev_year and prev_year["value"]:
            update["yoy_value"] = prev_year["value"]
            update["yoy_change_abs"] = round(latest["value"] - prev_year["value"], 4)
            if prev_year["value"] != 0:
                update["yoy_change_pct"] = round((latest["value"] - prev_year["value"]) / abs(prev_year["value"]) * 100, 2)

        # Trend
        if update.get("change_abs") is not None:
            if update["change_abs"] > 0:
                update["trend_direction"] = "up"
            elif update["change_abs"] < 0:
                update["trend_direction"] = "down"
            else:
                update["trend_direction"] = "stable"
            update["trend_strength"] = "strong" if abs(update.get("change_pct", 0)) > 5 else "moderate" if abs(update.get("change_pct", 0)) > 1 else "weak"

        # Sparkline points (last 12)
        sparkline = [h["value"] for h in reversed(history[:12]) if h.get("value") is not None]
        update["sparkline_points"] = sparkline

        if update:
            await db.macro_indicators.update_one(
                {"indicator_key": key, "date": latest["date"], "source": "banco_espana"},
                {"$set": update}
            )


async def refresh_all_indicators(user_email: str = "system") -> Dict:
    """Fetch latest + historical, persist, compute changes."""
    now = now_iso()

    try:
        # 1. Fetch latest from API
        indicators = await fetch_latest_indicators()
        api_updated = 0
        for ind in indicators:
            result = await db.macro_indicators.update_one(
                {"indicator_key": ind["indicator_key"], "date": ind["date"], "source": "banco_espana"},
                {"$set": {**ind, "last_updated_at": now, "source_url": BDE_API, "status": "ok"}},
                upsert=True
            )
            if result.upserted_id:
                api_updated += 1

        # 2. Fetch historical from CSV
        # Carga completa solo la primera vez; despues, ultimos 36 meses
        already = await db.macro_indicators.count_documents({"source": "banco_espana"})
        csv_result = await fetch_historical_csv("be0115", recent_months=36 if already > 500 else None)
        if csv_result.get("status") == "error":
            raise RuntimeError(csv_result.get("error", "CSV BDE error"))

        # 3. Compute changes
        await _compute_changes()

        # Update provider status
        await db.data_provider_status.update_one(
            {"provider": "banco_espana"},
            {"$set": {"status": "ok", "last_sync_at": now, "last_error": None,
                      "records_count": await db.macro_indicators.count_documents({"source": "banco_espana"}),
                      "updated_at": now}},
            upsert=True
        )

        return {
            "status": "completed",
            "api_indicators": len(indicators),
            "api_updated": api_updated,
            "csv_inserted": csv_result.get("inserted", 0),
            "csv_updated": csv_result.get("updated", 0),
            "total_records": await db.macro_indicators.count_documents({"source": "banco_espana"}),
        }

    except Exception as e:
        logger.error(f"BDE refresh failed: {e}")
        await db.data_provider_status.update_one(
            {"provider": "banco_espana"},
            {"$set": {"status": "error", "last_error": str(e)[:200], "updated_at": now}},
            upsert=True
        )
        return {"status": "error", "error": str(e)[:200]}
