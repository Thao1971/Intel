"""Sector Market engine — los 4 motores que faltaban para la Ficha Sectorial.

Cierra los huecos detectados en la auditoría de la Ficha Sectorial (2026-08-29),
usando SOLO dato real ya presente en Intel:

  crecimiento real por subsector   <- master_companies.financials.history
  serie mensual de BORME por CNAE  <- borme_events.publication_date + cnae_division
  operaciones M&A del sector       <- transactions_normalized (base CIS, con múltiplos)
  top organismos por sector        <- public_procurement_contracts + cpv->CNAE

No inventa datos: cada función degrada a vacío si no hay dato.
"""
from services.engines.sector_market import sector_market  # noqa: F401
