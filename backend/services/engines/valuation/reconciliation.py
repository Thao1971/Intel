"""Auditable reconciliation of the valuation methods produced by Intel."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .conventions import equity_bridge, number

RECONCILIATION_VERSION = "valuation-reconciliation-v1"


def _confidence(value: Any, default: float) -> float:
    parsed = number(value)
    return max(0.0, min(1.0, parsed if parsed is not None else default))


def _ordered_range(low: Any, central: Any, high: Any) -> Optional[Dict[str, float]]:
    values = [number(low), number(central), number(high)]
    if any(value is None for value in values):
        return None
    low_value, central_value, high_value = values
    if low_value < 0 or central_value < 0 or high_value < 0:
        return None
    ordered = sorted((low_value, central_value, high_value))
    return {"low": ordered[0], "central": ordered[1], "high": ordered[2]}


def _candidate(method: str, label: str, value_range: Dict[str, float],
               confidence: float, base_weight: float, quality_factor: float,
               source: str, explanation: str, lineage: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    raw_weight = base_weight * confidence * quality_factor
    return {
        "method": method, "label": label, "status": "applied",
        "enterprise_value_range": {key: round(value, 2) for key, value in value_range.items()},
        "confidence": round(confidence, 4), "base_weight": base_weight,
        "quality_factor": quality_factor, "raw_weight": raw_weight,
        "source": source, "explanation": explanation,
        "lineage": dict(lineage or {}),
    }


def _excluded(method: str, label: str, reason: str, explanation: str,
              source: Optional[str] = None) -> Dict[str, Any]:
    return {"method": method, "label": label, "status": "excluded", "reason": reason,
            "explanation": explanation, "source": source}


def reconcile_valuation(valuation: Mapping[str, Any], latest: Mapping[str, Any],
                        sector_rule: Optional[Mapping[str, Any]] = None,
                        private_transactions: Optional[Mapping[str, Any]] = None,
                        user_weights: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Combine independent EV indications and disclose every exclusion.

    Weights are mechanical: method base weight × method confidence × evidence
    quality, subsequently normalised across the methods that can actually be used.
    """
    applied: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    warnings: List[str] = []

    dcf = valuation.get("dcf") or {}
    scenarios = dcf.get("scenarios") or {}
    dcf_range = _ordered_range(
        (scenarios.get("conservative") or {}).get("enterprise_value"),
        (scenarios.get("base") or {}).get("enterprise_value"),
        (scenarios.get("optimistic") or {}).get("enterprise_value"))
    if dcf.get("status") == "available" and dcf_range:
        quality = .75 if dcf.get("decision_readiness") == "screen_grade" else 1.0
        applied.append(_candidate(
            "dcf", "Descuento de flujos de caja", dcf_range,
            _confidence(dcf.get("confidence"), .5), .50, quality,
            "Intel FCFF", "Se pondera por la calidad de las cuentas, los supuestos y el WACC.",
            dcf.get("lineage")))
    else:
        excluded.append(_excluded(
            "dcf", "Descuento de flujos de caja", dcf.get("reason", "dcf_unavailable"),
            "No existe una estimación DCF válida con los datos y supuestos disponibles.", "Intel FCFF"))

    basis = valuation.get("multiple_basis")
    listed_range = _ordered_range(
        (valuation.get("range") or {}).get("low"),
        (valuation.get("range") or {}).get("central", valuation.get("enterprise_value")),
        (valuation.get("range") or {}).get("high"))
    if valuation.get("method") in {"ev_ebitda", "ev_revenue", "ev_ebit"} and listed_range:
        if basis in {"market_observed", "observed_public_adjusted"}:
            applied.append(_candidate(
                "listed_comparables", "Compañías cotizadas comparables", listed_range,
                _confidence(valuation.get("confidence"), .5), .40, 1.0,
                "MarketScreener / Damodaran",
                "La referencia de cotizadas se ajusta a las características de la empresa privada.",
                valuation.get("lineage")))
        else:
            excluded.append(_excluded(
                "listed_comparables", "Compañías cotizadas comparables", "inferred_reference_not_observed",
                "El múltiplo es una referencia provisional y no una muestra de mercado observada.",
                "Intel provisional reference"))
    else:
        excluded.append(_excluded(
            "listed_comparables", "Compañías cotizadas comparables", "listed_comparable_unavailable",
            "No hay un múltiplo cotizado aplicable ni un rango completo de Enterprise Value.",
            "MarketScreener / Damodaran"))

    transactions = private_transactions or {}
    tx_range = _ordered_range(
        (transactions.get("range") or {}).get("low"),
        (transactions.get("range") or {}).get("central"),
        (transactions.get("range") or {}).get("high"))
    sample_size = int(number(transactions.get("sample_size")) or 0)
    if transactions.get("status") == "available" and tx_range and sample_size >= 3:
        applied.append(_candidate(
            "private_transactions", "Operaciones privadas comparables", tx_range,
            _confidence(transactions.get("confidence"), .65), .50, 1.0,
            transactions.get("source") or "TTR",
            f"Se utiliza una muestra de {sample_size} operaciones privadas comparables.",
            transactions.get("lineage")))
    else:
        reason = "insufficient_transaction_sample" if transactions else "private_transactions_not_connected"
        excluded.append(_excluded(
            "private_transactions", "Operaciones privadas comparables", reason,
            ("La muestra disponible tiene menos de tres operaciones comparables."
             if transactions else "TTR todavía no está conectado; no se estima ni se simula este método."),
            transactions.get("source") or "TTR"))

    equity = number(latest.get("equity"))
    bridge = equity_bridge(latest)
    archetype = (sector_rule or {}).get("archetype")
    asset_relevant = valuation.get("method") == "book_value" or archetype == "real_estate"
    if asset_relevant and equity is not None and equity >= 0 and bridge["net_debt_known"]:
        asset_ev = equity + bridge["net_debt"]
        asset_range = _ordered_range(asset_ev * .90, asset_ev, asset_ev * 1.10)
        if asset_range:
            applied.append(_candidate(
                "asset_value", "Valor patrimonial", asset_range, .40, .25, .80,
                "Iberinform", "Se usa el patrimonio contable como contraste patrimonial, convertido a EV mediante deuda neta.",
                {"financial_source": "Iberinform", "year": latest.get("year")}))
    elif asset_relevant:
        reason = "book_equity_unavailable" if equity is None else "net_debt_required_for_ev_bridge"
        excluded.append(_excluded(
            "asset_value", "Valor patrimonial", reason,
            "No puede incorporarse al rango de EV sin patrimonio contable y un puente completo de deuda y caja.",
            "Iberinform"))
    else:
        excluded.append(_excluded(
            "asset_value", "Valor patrimonial", "method_not_material_for_archetype",
            "El valor contable no es un método principal para este arquetipo de negocio.", "Iberinform"))

    supplied_weights = {}
    for item in applied:
        try:
            value = float((user_weights or {}).get(item["method"], 0))
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            supplied_weights[item["method"]] = value
    weighting_rule = "base_weight_x_confidence_x_quality_then_normalised"
    if supplied_weights:
        for item in applied:
            item["raw_weight"] = supplied_weights.get(item["method"], 0)
        weighting_rule = "user_supplied_available_methods_normalised"
    total_raw = sum(item["raw_weight"] for item in applied)
    if total_raw <= 0:
        return {
            "status": "unavailable", "engine_version": RECONCILIATION_VERSION,
            "methods_applied": [], "methods_excluded": excluded,
            "enterprise_value_range": None, "equity_value_range": None,
            "confidence": 0.0, "warnings": ["no_valuation_method_available"],
            "narrative": "No existe ningún método con evidencia suficiente para conciliar una valoración.",
        }

    for item in applied:
        item["weight"] = round(item.pop("raw_weight") / total_raw, 6)
    # Correct harmless rounding drift so the published weights add exactly to one.
    applied[-1]["weight"] = round(1 - sum(item["weight"] for item in applied[:-1]), 6)
    ev_range = {
        key: round(sum(item["weight"] * item["enterprise_value_range"][key] for item in applied), 2)
        for key in ("low", "central", "high")}
    final_bridge = equity_bridge(latest)
    if final_bridge["net_debt_known"]:
        equity_range = {key: round(value - final_bridge["net_debt"], 2) for key, value in ev_range.items()}
    else:
        equity_range = None
        warnings.extend(final_bridge["warnings"])

    confidence = round(sum(item["weight"] * item["confidence"] for item in applied), 2)
    names = ", ".join(item["label"] for item in applied)
    weight_text = "; ".join(f"{item['label']}: {item['weight']:.0%}" for item in applied)
    narrative = (f"La valoración se concilia con {names}. Los pesos resultan de la relevancia base, "
                 f"la confianza y la calidad de la evidencia ({weight_text}).")
    if equity_range is None:
        narrative += " El Equity Value queda pendiente hasta disponer de deuda financiera y caja."
    return {
        "status": "available", "engine_version": RECONCILIATION_VERSION,
        "methods_applied": applied, "methods_excluded": excluded,
        "enterprise_value_range": ev_range, "enterprise_value": ev_range["central"],
        "equity_value_range": equity_range,
        "equity_value": equity_range["central"] if equity_range else None,
        "equity_bridge": {**final_bridge, "enterprise_value": ev_range["central"],
                          "equity_value": equity_range["central"] if equity_range else None},
        "confidence": confidence,
        "decision_readiness": "decision_grade" if confidence >= .70 and len(applied) >= 2 else "screen_grade",
        "warnings": warnings, "narrative": narrative,
        "weighting_rule": weighting_rule,
    }
