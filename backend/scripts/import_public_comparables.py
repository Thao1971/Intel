import argparse, asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import db
from services.engines.valuation.public_comparables import load_export
from services.engines.valuation.comparable_snapshots import build_comparable_snapshots

def args():
    p=argparse.ArgumentParser()
    p.add_argument("path",type=Path)
    p.add_argument("--provider",required=True,choices=["marketscreener"])
    p.add_argument("--as-of",required=True)
    p.add_argument("--sheet")
    p.add_argument("--publish",action="store_true")
    return p.parse_args()

async def main():
    a=args(); result=load_export(a.path,a.provider,a.as_of,a.sheet)
    if a.publish:
        await db.valuation_public_comparable_imports.insert_one({
          "provider":a.provider,"as_of":a.as_of,"source_file":a.path.name,
          "record_count":result["record_count"],"rejected":result["rejected"],
          "imported_at":datetime.now(timezone.utc).isoformat()})
        for record in result["records"]:
            key={"provider":a.provider,"as_of":a.as_of,
                 "identifier":record.get("isin") or record.get("ticker") or record.get("name")}
            await db.valuation_public_comparables.update_one(
              key,{"$set":{**record,"identifier":key["identifier"],"active":True}},upsert=True)
        snapshots=build_comparable_snapshots(
          result["records"],provider=a.provider,region="spain",as_of=a.as_of)
        await db.valuation_public_comparable_snapshots.update_many(
          {"provider":a.provider,"region":"spain","active":True},
          {"$set":{"active":False}})
        if snapshots["snapshots"]:
            await db.valuation_public_comparable_snapshots.insert_many(
              snapshots["snapshots"],ordered=False)
    print(json.dumps({k:v for k,v in result.items() if k!="records"},
                     ensure_ascii=False,indent=2,default=str))
if __name__=="__main__": asyncio.run(main())
