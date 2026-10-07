"""PLACSP Connector — Ingests real procurement data from official PLACSP ZIPs.

Source: contrataciondelsectorpublico.gob.es (Atom XML, CODICE 2.07)
Downloads annual ZIP files, parses Atom XML entries, extracts contracts.

Datasets available:
  - Licitaciones: ~4M entries (2012-present)
  - Contratos menores: ~2M entries (2018-present)
  - Plataformas agregadas: ~1.7M entries (2016-present)
"""

import asyncio
import logging
import os
import io
import zipfile
import hashlib
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from datetime import datetime, timezone
import httpx
from database import db
from models import new_id, now_iso
from services.text_normalize import normalize_strings

logger = logging.getLogger(__name__)

BASE_URL = "https://contrataciondelsectorpublico.gob.es/sindicacion"

DATASET_URLS = {
    "licitaciones": f"{BASE_URL}/sindicacion_643/licitacionesPerfilesContratanteCompleto3_{{year}}.zip",
    "menores": f"{BASE_URL}/sindicacion_1143/contratosMenoresPerfilesContratantes_{{year}}.zip",
    "agregadas": f"{BASE_URL}/sindicacion_1044/PlataformasAgregadasSinMenores_{{year}}.zip",
}

NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'cbc': 'urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2',
    'cac': 'urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2',
    'cac-place-ext': 'urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2',
    'cbc-place-ext': 'urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2',
}

# Contract type codes (CODICE)
CONTRACT_TYPES = {"1": "suministros", "2": "servicios", "3": "obras", "21": "privado", "31": "patrimonial", "40": "administrativo_especial", "7": "gestion_servicios", "8": "concesion_obras", "50": "concesion_servicios"}
PROCEDURE_CODES = {"1": "abierto", "2": "restringido", "3": "negociado", "4": "dialogo_competitivo", "6": "contrato_menor", "7": "basado_acuerdo_marco", "8": "simplificado", "9": "asociacion_innovacion", "100": "normas_internas"}
RESULT_CODES = {"1": "adjudicacion_provisional", "2": "adjudicacion_provisional_sin_publicar", "3": "adjudicacion_definitiva", "4": "formalizado", "5": "parcialmente_formalizado", "7": "desistimiento", "8": "resuelto", "9": "anulado"}


async def sync_placsp(years: List[int] = None, dataset: str = "menores",
                      max_files: int = None) -> Dict:
    """Download and process PLACSP ZIP for given years.
    
    Args:
        years: Years to sync. Defaults to current + previous year.
        dataset: 'menores', 'licitaciones', or 'agregadas'.
        max_files: Limit atom files processed per ZIP (for testing).
    """
    now = now_iso()
    current_year = datetime.now(timezone.utc).year

    if not years:
        years = [current_year - 1, current_year]

    if dataset not in DATASET_URLS:
        return {"status": "error", "message": f"Unknown dataset: {dataset}"}

    total_imported = 0
    total_skipped = 0
    errors = []
    years_processed = []

    for year in years:
        url = DATASET_URLS[dataset].format(year=year)
        logger.info(f"PLACSP: downloading {dataset} {year}...")

        try:
            zip_data = await _download_zip(url)
            if not zip_data:
                errors.append(f"{year}: download failed")
                continue

            # CPU-bound: fuera del event loop para no congelar el resto de la API
            contracts = await asyncio.to_thread(_parse_zip, zip_data, max_files=max_files)
            logger.info(f"PLACSP {year}: parsed {len(contracts)} contracts")

            if contracts:
                imported, skipped = await _store_contracts(contracts, dataset, year, now)
                total_imported += imported
                total_skipped += skipped
                years_processed.append(year)
                logger.info(f"PLACSP {year}: imported={imported}, skipped(dupes)={skipped}")

        except Exception as e:
            err = f"{year}: {str(e)[:200]}"
            errors.append(err)
            logger.error(f"PLACSP error: {err}")

    # Compute checksum
    checksum = None
    if total_imported > 0:
        count = await db.public_procurement_contracts.count_documents({}, hint="_id_")
        checksum = hashlib.sha256(f"{count}:{now}".encode()).hexdigest()[:16]

    # Status: previously any run with `errors` was labeled "partial" even when
    # EVERY year failed and total_imported stayed at 0 — indistinguishable from a
    # genuine partial success (some years ok, some not). Now a total failure is
    # reported as "error".
    if not errors:
        status = "completed"
    elif total_imported == 0:
        status = "error"
    else:
        status = "partial"

    # Log
    await db.procurement_sync_logs.insert_one({
        "sync_id": new_id(),
        "synced_at": now,
        "source": "placsp_auto",
        "dataset": dataset,
        "years": years_processed,
        "total_imported": total_imported,
        "total_skipped": total_skipped,
        "errors": errors,
        "checksum": checksum,
        "status": status,
    })

    return {
        "status": status,
        "dataset": dataset,
        "years": years_processed,
        "imported": total_imported,
        "skipped": total_skipped,
        "errors": errors,
        "checksum": checksum,
        "synced_at": now,
    }


async def _download_zip(url: str) -> Optional[bytes]:
    """Download ZIP file with timeout."""
    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                logger.info(f"  Downloaded: {len(resp.content) / 1024 / 1024:.1f} MB")
                return resp.content
            else:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
    except Exception as e:
        logger.error(f"  Download error: {e}")
        return None


def _parse_zip(zip_data: bytes, max_files: int = None) -> List[Dict]:
    """Parse all atom files in a ZIP into contract documents."""
    contracts = []

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        atom_files = [f for f in zf.namelist() if f.endswith('.atom')]
        if max_files:
            atom_files = atom_files[:max_files]

        for i, fname in enumerate(atom_files):
            try:
                with zf.open(fname) as f:
                    xml_data = f.read()
                entries = _parse_atom(xml_data)
                contracts.extend(entries)

                if (i + 1) % 50 == 0:
                    logger.info(f"  Parsed {i+1}/{len(atom_files)} files ({len(contracts)} contracts)")
            except Exception as e:
                logger.warning(f"  Error parsing {fname}: {e}")

    return contracts


def _parse_atom(xml_data: bytes) -> List[Dict]:
    """Parse a single Atom XML file into contract dicts."""
    contracts = []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []

    for entry in root.findall('atom:entry', NS):
        try:
            c = _parse_entry(entry)
            if c:
                contracts.append(c)
        except Exception:
            continue

    return contracts


def _parse_entry(entry) -> Optional[Dict]:
    """Parse a single Atom entry into a contract document."""
    cfs = entry.find('.//cac-place-ext:ContractFolderStatus', NS)
    if cfs is None:
        return None

    folder_id = cfs.findtext('cbc:ContractFolderID', '', NS)
    if not folder_id:
        return None

    status_code = cfs.findtext('cbc-place-ext:ContractFolderStatusCode', '', NS)

    # Buyer (contracting authority)
    party = cfs.find('.//cac-place-ext:LocatedContractingParty/cac:Party', NS)
    buyer_name = party.findtext('cac:PartyName/cbc:Name', '', NS) if party else ''
    buyer_nif = _extract_nif(party) if party else ''
    buyer_city = party.findtext('cac:PostalAddress/cbc:CityName', '', NS) if party else ''

    # Parent entity (CCAA hierarchy)
    parent = cfs.find('.//cac-place-ext:LocatedContractingParty/cac-place-ext:ParentLocatedParty/cac:PartyName/cbc:Name', NS)
    parent_entity = parent.text if parent is not None else ''

    # Project details
    proj = cfs.find('cac:ProcurementProject', NS)
    title = proj.findtext('cbc:Name', '', NS) if proj else ''
    type_code = proj.findtext('cbc:TypeCode', '', NS) if proj else ''
    cpv = proj.findtext('cac:RequiredCommodityClassification/cbc:ItemClassificationCode', '', NS) if proj else ''
    budget_str = proj.findtext('cac:BudgetAmount/cbc:TotalAmount', '', NS) if proj else ''
    nuts = proj.findtext('cac:RealizedLocation/cbc:CountrySubentityCode', '', NS) if proj else ''

    # Tender result
    tr = cfs.find('cac:TenderResult', NS)
    award_date = tr.findtext('cbc:AwardDate', '', NS) if tr else ''
    result_code = tr.findtext('cbc:ResultCode', '', NS) if tr else ''

    # Winner
    winner = tr.find('cac:WinningParty', NS) if tr else None
    winner_name = winner.findtext('cac:PartyName/cbc:Name', '', NS) if winner else ''
    winner_nif = _extract_nif(winner) if winner else ''
    awarded_str = ''
    if tr:
        awarded_str = tr.findtext('cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount', '', NS)

    # Procedure
    proc = cfs.find('cac:TenderingProcess', NS)
    procedure_code = proc.findtext('cbc:ProcedureCode', '', NS) if proc else ''

    # Publication date
    pub_info = cfs.find('cac-place-ext:ValidNoticeInfo', NS)
    pub_date = ''
    if pub_info:
        pub_date = pub_info.findtext('.//cac-place-ext:AdditionalPublicationDocumentReference/cbc:IssueDate', '', NS)

    # Parse amounts
    budget = _parse_float(budget_str)
    awarded = _parse_float(awarded_str)
    amount = awarded if awarded > 0 else budget

    return {
        "expediente": folder_id,
        "title": title[:500],
        "status": RESULT_CODES.get(result_code, status_code),
        "cpv_code": cpv,
        "contract_type": CONTRACT_TYPES.get(type_code, type_code),
        "procedure_type": PROCEDURE_CODES.get(procedure_code, procedure_code),
        "amount": amount,
        "budget_amount": budget,
        "awarded_amount": awarded,
        "currency": "EUR",
        "publication_date": pub_date or None,
        "award_date": award_date or None,
        "buyer_name": buyer_name,
        "buyer_nif": buyer_nif,
        "buyer_city": buyer_city,
        "parent_entity": parent_entity,
        "nuts_code": nuts,
        "awardee_name": winner_name,
        "awardee_tax_id": winner_nif,
    }


def _extract_nif(party_element) -> str:
    if party_element is None:
        return ''
    for pid in party_element.findall('cac:PartyIdentification', NS):
        id_el = pid.find('cbc:ID', NS)
        if id_el is not None and id_el.get('schemeName') == 'NIF':
            return id_el.text or ''
    return ''


def _parse_float(s: str) -> float:
    if not s:
        return 0
    try:
        return float(s.replace(',', '.'))
    except ValueError:
        return 0


async def _store_contracts(contracts: List[Dict], dataset: str, year: int, now: str) -> tuple:
    """Store contracts, skipping duplicates by expediente."""
    imported = 0
    skipped = 0

    for c in contracts:
        if not c["expediente"]:
            skipped += 1
            continue

        c = normalize_strings(c)
        # Upsert by expediente (idempotent)
        result = await db.public_procurement_contracts.update_one(
            {"expediente": c["expediente"]},
            {"$set": {
                **c,
                "source_provider": "placsp",
                "source_dataset": dataset,
                "source_year": year,
                "imported_at": now,
                "updated_at": now,
            },
            "$setOnInsert": {
                "contract_id": new_id(),
                "matched_company_id": None,
                "matched_company_name": None,
                "match_confidence": None,
                "review_status": "pending",
                "visible_in_valuo": True,
            }},
            upsert=True,
        )

        if result.upserted_id:
            imported += 1
        else:
            skipped += 1

    return imported, skipped
