import asyncio, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import db
from services.engines.valuation.ecb_risk_free import refresh_ecb_risk_free
async def main():
    print(json.dumps(await refresh_ecb_risk_free(db),indent=2,ensure_ascii=False))
if __name__=="__main__": asyncio.run(main())
