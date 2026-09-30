"""Tests unitarios (sin base de datos) del trabajo de recálculo de señales.

    python -m pytest backend/tests/test_signal_recompute.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import signal_recompute as SR  # noqa: E402


class MemStore:
    def __init__(self): self.rows = {}; self.calls = 0
    async def update(self, run_id, patch): self.calls += 1; self.rows.setdefault(run_id, {}).update(patch)


def test_counts_progress_and_survives_a_failing_company():
    async def analyze(mid):
        if mid == "m3": raise ValueError("datos rotos")
        return {"signals": [1]} if mid != "m2" else {"signals": []}
    st = MemStore()
    res = asyncio.run(SR.run_recompute("r1", ["m1", "m2", "m3", "m4"], store=st, analyze=analyze, heartbeat_every=2))
    assert res["status"] == "completed" and res["total"] == 4 and res["processed"] == 4
    assert res["with_signals"] == 2 and res["errors"] == 1
    assert res["first_errors"] == [{"master_id": "m3", "error": "ValueError: datos rotos"}]
    assert st.rows["r1"]["status"] == "completed" and st.calls >= 4          # inicio + 2 latidos + final


def test_empty_run_completes():
    res = asyncio.run(SR.run_recompute("r2", [], store=MemStore(), analyze=lambda m: None))
    assert res["status"] == "completed" and res["total"] == 0 and res["processed"] == 0


def test_workers_run_in_parallel_up_to_the_limit_and_process_everything_once():
    seen, running, peak = [], 0, 0
    async def analyze(mid):
        nonlocal running, peak
        running += 1; peak = max(peak, running)
        await asyncio.sleep(0.01)
        seen.append(mid); running -= 1
        return {"signals": [1]}
    ids = [f"m{i}" for i in range(30)]
    res = asyncio.run(SR.run_recompute("r3", ids, store=MemStore(), analyze=analyze, workers=5, heartbeat_every=10))
    assert res["status"] == "completed" and res["processed"] == 30 and res["with_signals"] == 30
    assert sorted(seen) == sorted(ids) and len(seen) == 30       # ninguna empresa dos veces ni saltada
    assert 2 <= peak <= 5                                          # hubo paralelismo y no superó el límite


def test_a_failing_company_does_not_stop_the_other_workers():
    async def analyze(mid):
        if mid in ("m1", "m7"): raise RuntimeError("x")
        return {"signals": [1]}
    res = asyncio.run(SR.run_recompute("r4", [f"m{i}" for i in range(12)], store=MemStore(), analyze=analyze, workers=4))
    assert res["status"] == "completed" and res["processed"] == 12 and res["errors"] == 2 and res["with_signals"] == 10


def test_workers_are_clamped():
    assert SR.clamp_workers(None) == 1 and SR.clamp_workers("x") == 1 and SR.clamp_workers(0) == 1
    assert SR.clamp_workers(5) == 5 and SR.clamp_workers(999) == SR.MAX_WORKERS


def test_more_workers_than_companies_is_fine():
    async def analyze(mid): return {"signals": [1]}
    res = asyncio.run(SR.run_recompute("r5", ["a", "b"], store=MemStore(), analyze=analyze, workers=12))
    assert res["processed"] == 2 and res["with_signals"] == 2


if __name__ == "__main__":  # ejecución sin pytest
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("OK  ", name)
            except AssertionError as e:
                failed += 1; print("FAIL", name, "->", e)
    sys.exit(1 if failed else 0)
