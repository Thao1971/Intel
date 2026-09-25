import asyncio
from services.engines.valuation.market_premia import premium_snapshot,store_premium

class Collection:
    def __init__(self): self.rows=[]
    async def update_one(self,q,u,upsert=False):
        if not any(all(r.get(k)==v for k,v in q.items()) for r in self.rows):
            self.rows.append(dict(u["$setOnInsert"]))
class DB:
    def __init__(self): self.valuation_market_snapshots=Collection()

def test_premium_is_validated_and_stored_idempotently():
    db=DB(); snap=premium_snapshot("mature_market_erp",.0423,"2026-01-05","Damodaran","https://example.test")
    asyncio.run(store_premium(db,snap)); asyncio.run(store_premium(db,snap))
    assert len(db.valuation_market_snapshots.rows)==1
    assert db.valuation_market_snapshots.rows[0]["series_key"]=="ERP.MATURE_MARKET"

def test_invalid_premium_is_rejected():
    try: premium_snapshot("mature_market_erp",.5,"2026-01-05","x","https://example.test")
    except ValueError as exc: assert "between" in str(exc)
    else: raise AssertionError("invalid premium accepted")
