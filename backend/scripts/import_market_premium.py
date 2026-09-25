"""Store a dated ERP or Spain country-risk-premium observation."""
import argparse,asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import db
from services.engines.valuation.market_premia import premium_snapshot,store_premium

def arguments():
    p=argparse.ArgumentParser()
    p.add_argument("kind",choices=("mature_market_erp","spain_country_risk_premium"))
    p.add_argument("value",type=float,help="Decimal, e.g. 0.0423")
    p.add_argument("--observation-date",required=True)
    p.add_argument("--source",required=True)
    p.add_argument("--source-url",required=True)
    return p.parse_args()

async def main():
    a=arguments(); snapshot=premium_snapshot(a.kind,a.value,a.observation_date,a.source,a.source_url)
    print(json.dumps(await store_premium(db,snapshot),ensure_ascii=False,indent=2))
if __name__=="__main__": asyncio.run(main())
