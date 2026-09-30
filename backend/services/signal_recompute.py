"""Recálculo SOLO de señales, con progreso (sin pasar por el bootstrap completo de 24-30 h).

`bootstrap.build_signals_canonical` hace lo mismo pero solo existe dentro de la cadena completa de carga.
Aquí se expone como trabajo aparte, acotable por sección CNAE o por número de empresas para probarlo antes
de lanzarlo sobre todo el universo. `persist` cierra (`status: disappeared`) las señales que ya no se
cumplen, así que este recálculo es lo que retira, p. ej., la composición de "expansión" de una empresa con
ingresos negativos o las sucesiones que dejan de cumplir el criterio de tamaño y antigüedad.

El estado del trabajo se guarda en `signal_recompute_runs` (una fila por ejecución).
"""

from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

HEARTBEAT_EVERY = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _DbStore:
    """Persistencia por defecto del progreso (colección `signal_recompute_runs`)."""

    async def update(self, run_id: str, patch: Dict) -> None:
        from database import db
        await db.signal_recompute_runs.update_one({"run_id": run_id}, {"$set": patch}, upsert=True)

    async def get(self, run_id: str) -> Optional[Dict]:
        from database import db
        return await db.signal_recompute_runs.find_one({"run_id": run_id}, {"_id": 0})


async def _default_analyze(master_id: str):
    from services.engines.signal import engine as sig_engine
    return await sig_engine.analyze(master_id, persist=True)


async def run_recompute(run_id: str, master_ids: List[str], *, store=None,
                        analyze: Optional[Callable[[str], Awaitable]] = None,
                        heartbeat_every: int = HEARTBEAT_EVERY) -> Dict:
    """Recalcula y persiste las señales de cada empresa. Un error en una empresa no aborta el lote."""
    store = store or _DbStore()
    analyze = analyze or _default_analyze
    total = len(master_ids)
    done = with_signals = errors = 0
    first_errors: List[Dict] = []
    await store.update(run_id, {"run_id": run_id, "status": "running", "total": total, "processed": 0,
                                "with_signals": 0, "errors": 0, "started_at": _now()})
    try:
        for mid in master_ids:
            try:
                r = await analyze(mid)
                if r and r.get("signals"):
                    with_signals += 1
            except Exception as e:  # noqa: BLE001 — nunca abortar el lote por una empresa
                errors += 1
                if len(first_errors) < 5:
                    first_errors.append({"master_id": mid, "error": f"{type(e).__name__}: {str(e)[:160]}"})
            done += 1
            if done % heartbeat_every == 0:
                await store.update(run_id, {"processed": done, "with_signals": with_signals, "errors": errors,
                                            "updated_at": _now()})
        status = "completed"
    except Exception as e:  # noqa: BLE001 — fallo inesperado del propio trabajo
        status = "failed"
        first_errors.append({"error": f"{type(e).__name__}: {str(e)[:160]}"})
    result = {"status": status, "total": total, "processed": done, "with_signals": with_signals,
              "errors": errors, "first_errors": first_errors, "finished_at": _now()}
    await store.update(run_id, result)
    return result
