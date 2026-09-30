"""Criterios de relevancia de las oportunidades: UN solo sitio.

Qué empresas merecen aparecer como oportunidad de M&A no es una decisión técnica del motor de señales
(que trata igual a todas las empresas), sino de negocio. Estas constantes son ese criterio por defecto
para la beta; se aplican en:

  · `borme_bridge.py`   -> la señal de sucesión solo se genera si la empresa alcanza el suelo de ingresos
                           y el administrador cumple la antigüedad mínima (ver `officer_utils.succession_gate`).
  · `opportunity_view.py` -> el nivel "Oportunidad" exige el suelo de ingresos; las señales de tipo
                           `SIZE_GATED_SIGNAL_TYPES` no se muestran por debajo de él.

Cómo cambiarlo:
  · Globalmente, sin tocar código: variable de entorno `ARROBA_MIN_REVENUE_EUR` (euros).
  · Por comprador: un mandato con `revenue_min` sobrescribe el suelo en la vista
    (`GET /signal-intelligence/opportunities/enriched/view?mandate_id=...`).

Límite conocido: la señal de sucesión se genera con el suelo GLOBAL (las señales no dependen de un
mandato). Un mandato puede SUBIR el suelo para sucesión y BAJARLO para el nivel Oportunidad, pero no
puede recuperar señales de sucesión de empresas por debajo del suelo global.
"""

import os
from typing import Dict, Optional, Tuple

DEFAULT_MIN_REVENUE_EUR = 1_000_000.0
ENV_MIN_REVENUE = "ARROBA_MIN_REVENUE_EUR"

# Antigüedad mínima del administrador para la señal de sucesión (años). Provisional: sin calibrar
# contra sucesiones reales. No se sube en `thresholds.py` porque `ensure_thresholds` siembra con
# $setOnInsert y el valor ya guardado en la base (15) no se actualizaría; el motor usa el mayor de ambos.
SUCCESSION_MIN_TENURE_YEARS = 20.0

# Señales cuya relevancia depende del tamaño de la empresa: por debajo del suelo no se muestran.
SIZE_GATED_SIGNAL_TYPES = frozenset({"opportunity.succession_signal"})


def configured_min_revenue() -> Tuple[float, str]:
    """(suelo, origen). Origen: 'config' si lo fija el entorno, 'default' si es el valor por defecto."""
    raw = os.environ.get(ENV_MIN_REVENUE)
    if raw not in (None, ""):
        try:
            value = float(raw)
            if value >= 0:
                return value, "config"
        except ValueError:
            pass   # valor inválido: se ignora y se usa el defecto (no se rompe el arranque por un typo)
    return DEFAULT_MIN_REVENUE_EUR, "default"


def effective_min_revenue(mandate: Optional[Dict] = None, override: Optional[float] = None) -> Tuple[float, str]:
    """Suelo efectivo: `override` explícito (p. ej. el `revenue_min` del mandato de compra del usuario, que envía
    el front de Beta), luego el `revenue_min` de un mandato de Intel; si no, el configurado / por defecto."""
    if isinstance(override, (int, float)) and not isinstance(override, bool) and override >= 0:
        return float(override), "mandate"
    rmin = (mandate or {}).get("revenue_min")
    if isinstance(rmin, (int, float)) and not isinstance(rmin, bool) and rmin >= 0:
        return float(rmin), "mandate"
    return configured_min_revenue()


def meets_size_floor(revenue: Optional[float], floor: float) -> bool:
    """Ingresos desconocidos NO superan el suelo: no se puede afirmar relevancia sin dato."""
    return isinstance(revenue, (int, float)) and not isinstance(revenue, bool) and revenue >= floor
