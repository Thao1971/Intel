"""Public Procurement Connector — Ingests contracts from datos.gob.es / OpenPLACSP datasets.

V1: Manual sync with dataset URL (CSV). Filters by CPV scope.
NO scraping. NO feeds. NO automatic scheduling yet.
"""

import csv
import io
import re
import logging
from typing import Optional, List, Dict
from database import db
from models import new_id, now_iso
from services.text_normalize import normalize_strings
from services.entity_resolution import _normalize_name, _normalize_cif
from services.entity_resolution_provider import resolve_entity_provider as resolve_entity

logger = logging.getLogger(__name__)

# Initial CPV codes related to advertising, marketing, communication, events
INITIAL_CPV_SCOPE = [
    {"cpv": "79340000", "label": "Servicios de publicidad y marketing"},
    {"cpv": "79341000", "label": "Servicios de publicidad"},
    {"cpv": "79341100", "label": "Servicios de asesoramiento en publicidad"},
    {"cpv": "79341200", "label": "Servicios de gestion publicitaria"},
    {"cpv": "79342000", "label": "Servicios de marketing"},
    {"cpv": "79342100", "label": "Servicios de marketing directo"},
    {"cpv": "79416000", "label": "Servicios de relaciones publicas"},
    {"cpv": "79952000", "label": "Servicios de eventos"},
    {"cpv": "79950000", "label": "Servicios de organizacion de exposiciones y ferias"},
    {"cpv": "79822500", "label": "Servicios de diseno grafico"},
    {"cpv": "79820000", "label": "Servicios relacionados con la impresion"},
    {"cpv": "72000000", "label": "Servicios de tecnologia de la informacion"},
    {"cpv": "72200000", "label": "Servicios de programacion y consultoria informatica"},
    {"cpv": "72300000", "label": "Servicios de tratamiento de datos"},
    {"cpv": "79300000", "label": "Servicios de investigacion de mercados"},
    {"cpv": "79310000", "label": "Servicios de investigacion de mercados"},
    {"cpv": "92111000", "label": "Servicios de produccion cinematografica y de video"},
    {"cpv": "92110000", "label": "Servicios de produccion audiovisual"},
    {"cpv": "79400000", "label": "Servicios de consultoria empresarial y gestion"},
    {"cpv": "79410000", "label": "Servicios de consultoria empresarial y gestion"},
]

# Column name aliases for CSV parsing
COL_ALIASES = {
    "expediente": ["expediente", "numero_expediente", "n_expediente", "file_number", "ContractFolderID"],
    "title": ["objeto", "objeto_contrato", "titulo", "title", "description", "ContractTitle"],
    "cpv": ["cpv", "codigo_cpv", "cpv_code", "ItemClassificationCode"],
    "amount": ["importe", "importe_adjudicacion", "precio", "amount", "TotalAmount", "importe_sin_iva"],
    "awardee_name": ["adjudicatario", "nombre_adjudicatario", "empresa_adjudicataria", "AwardedPartyName"],
    "awardee_tax_id": ["nif_adjudicatario", "cif_adjudicatario", "nif", "cif", "AwardedPartyID"],
    "buyer_name": ["organo_contratacion", "organismo", "buyer", "BuyerName"],
    "award_date": ["fecha_adjudicacion", "fecha_formalizacion", "date", "AwardDate"],
    "publication_date": ["fecha_publicacion", "PublicationDate"],
    "status": ["estado", "status", "ResultCode"],
    "procedure_type": ["tipo_procedimiento", "procedure", "ProcedureCode"],
    "contract_type": ["tipo_contrato", "contract_type", "TypeCode"],
}


def _find_column(headers: List[str], field: str) -> Optional[int]:
    """Find column index by checking aliases."""
    aliases = COL_ALIASES.get(field, [field])
    for i, h in enumerate(headers):
        h_clean = h.strip().lower().replace(" ", "_").replace("-", "_")
        for alias in aliases:
            if alias.lower() == h_clean or alias.lower() in h_clean:
                return i
    return None


def _parse_amount(val: str) -> Optional[float]:
    if not val:
        return None
    val = val.strip().replace("€", "").replace(",", ".").replace(" ", "")
    try:
        return round(float(val), 2)
    except ValueError:
        return None


def _cpv_matches_scope(cpv: str, scope: set) -> bool:
    """Check if CPV code matches any in scope (prefix match)."""
    if not cpv:
        return False
    cpv = cpv.strip()
    for s in scope:
        if cpv.startswith(s[:4]):  # Match on first 4 digits (division level)
            return True
    return False


async def parse_and_ingest_csv(csv_content: str, source_url: str, user_email: str) -> Dict:
    """Parse a CSV dataset and ingest matching contracts."""
    now = now_iso()

    # Get active CPV scope
    scope_docs = await db.procurement_cpv_scope.find({"enabled": True}, {"_id": 0, "cpv": 1}).to_list(100)
    cpv_scope = {d["cpv"] for d in scope_docs}
    if not cpv_scope:
        # Fallback to initial scope
        cpv_scope = {c["cpv"] for c in INITIAL_CPV_SCOPE}

    reader = csv.reader(io.StringIO(csv_content), delimiter=";")
    rows = list(reader)

    if len(rows) < 2:
        return {"status": "error", "error": "Dataset vacio o sin filas", "rows": len(rows)}

    headers = rows[0]
    col_map = {}
    for field in COL_ALIASES:
        idx = _find_column(headers, field)
        if idx is not None:
            col_map[field] = idx

    stats = {"total_rows": len(rows) - 1, "cpv_matched": 0, "imported": 0, "skipped": 0, "duplicates": 0, "matched_companies": 0, "errors": 0}

    for row_num, row in enumerate(rows[1:], start=2):
        try:
            def get(field):
                idx = col_map.get(field)
                if idx is not None and idx < len(row):
                    return row[idx].strip()
                return None

            cpv = get("cpv")

            # Filter by CPV scope
            if not _cpv_matches_scope(cpv, cpv_scope):
                stats["skipped"] += 1
                continue

            stats["cpv_matched"] += 1

            expediente = get("expediente") or f"row_{row_num}"
            title = get("title")
            awardee_name = get("awardee_name")
            awardee_tax_id = get("awardee_tax_id")
            amount = _parse_amount(get("amount") or "")

            # Skip if no title and no awardee
            if not title and not awardee_name:
                stats["skipped"] += 1
                continue

            # Deduplicate by expediente
            existing = await db.public_procurement_contracts.find_one({"expediente": expediente})
            if existing:
                stats["duplicates"] += 1
                continue

            # Try matching against companies_master
            matched_company_id = None
            matched_company_name = None
            match_confidence = 0
            match_signals = []

            if awardee_tax_id or awardee_name:
                resolution = await resolve_entity(
                    legal_name=awardee_name,
                    cif=awardee_tax_id,
                    source="public_procurement",
                )
                if resolution["match_id"] and resolution["score"] >= 0.7:
                    matched_company_id = resolution["match_id"]
                    mc = await db.companies_master.find_one({"master_company_id": resolution["match_id"]}, {"_id": 0, "legal_name": 1})
                    matched_company_name = mc.get("legal_name") if mc else None
                    match_confidence = round(resolution["score"] * 100, 1)
                    match_signals = [c.get("method", "") for c in resolution.get("candidates", [])[:1]]
                    stats["matched_companies"] += 1

            contract = {
                "contract_id": f"proc_{new_id()[:12]}",
                "expediente": expediente,
                "title": title,
                "description": title,
                "cpv_code": cpv,
                "cpv_label": None,
                "contracting_authority": get("buyer_name"),
                "buyer_name": get("buyer_name"),
                "awardee_name": awardee_name,
                "awardee_tax_id": awardee_tax_id,
                "matched_company_id": matched_company_id,
                "matched_company_name": matched_company_name,
                "amount": amount,
                "currency": "EUR",
                "publication_date": get("publication_date"),
                "award_date": get("award_date"),
                "status": get("status") or "adjudicado",
                "procedure_type": get("procedure_type"),
                "contract_type": get("contract_type"),
                "source_url": source_url,
                "source_provider": "datos.gob.es",
                "source_record_id": expediente,
                "source_row": row_num,
                "imported_at": now,
                "updated_at": now,
                "match_confidence": match_confidence,
                "match_signals": match_signals,
                "visible_in_valuo": match_confidence >= 80,
                "review_status": "pending_review" if 0 < match_confidence < 80 else "auto_matched" if match_confidence >= 80 else "unmatched",
            }

            await db.public_procurement_contracts.insert_one(normalize_strings({**contract}))
            stats["imported"] += 1

        except Exception as e:
            logger.error(f"Row {row_num} error: {e}")
            stats["errors"] += 1

    # Update provider status
    await db.data_provider_status.update_one(
        {"provider": "public_procurement"},
        {"$set": {
            "status": "ok",
            "last_sync_at": now,
            "records_count": await db.public_procurement_contracts.count_documents({}, hint="_id_"),
            "last_error": None,
            "updated_at": now,
        }},
        upsert=True
    )

    # Sync log
    await db.procurement_sync_logs.insert_one({
        "sync_id": new_id(), "source_url": source_url,
        "synced_by": user_email, **stats, "synced_at": now,
    })

    return {"status": "completed", **stats}
