"""Build and optionally publish listed-company percentile snapshots."""
import argparse,asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import db
from services.engines.valuation.comparable_snapshots import build_comparable_snapshots

def arguments():
 p=argparse.ArgumentParser();p.add_argument("input",type=Path);p.add_argument("--provider",default="marketscreener")
 p.add_argument("--region",default="spain");p.add_argument("--as-of",required=True)
 p.add_argument("--output",type=Path,required=True);p.add_argument("--publish",action="store_true");return p.parse_args()

async def main():
 a=arguments(); source=json.loads(a.input.read_text(encoding="utf-8"))
 result=build_comparable_snapshots(source.get("records",source),provider=a.provider,region=a.region,as_of=a.as_of)
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
 if a.publish:
  await db.valuation_public_comparable_snapshots.update_many(
   {"provider":a.provider,"region":a.region,"active":True},{"$set":{"active":False}})
  if result["snapshots"]: await db.valuation_public_comparable_snapshots.insert_many(result["snapshots"],ordered=False)
 print(json.dumps({k:v for k,v in result.items() if k!="snapshots"},ensure_ascii=False,indent=2))
if __name__=="__main__":asyncio.run(main())
