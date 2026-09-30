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


if __name__ == "__main__":  # ejecución sin pytest
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("OK  ", name)
            except AssertionError as e:
                failed += 1; print("FAIL", name, "->", e)
    sys.exit(1 if failed else 0)
