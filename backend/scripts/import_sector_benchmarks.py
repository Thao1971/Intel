import argparse, asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import db
from services.engines.valuation.sector_benchmarks import load_sector_benchmark

def args():
    parser=argparse.ArgumentParser()
    parser.add_argument("path",type=Path)
    parser.add_argument("--region",required=True,choices=["europe","united_states"])
    parser.add_argument("--as-of",required=True)
    parser.add_argument("--publish",action="store_true")
    return parser.parse_args()

async def main():
    options=args()
    result=load_sector_benchmark(options.path,options.region,options.as_of)
    if options.publish:
        await db.valuation_sector_benchmark_imports.insert_one({
            "provider":result["provider"],"region":result["region"],
            "as_of":result["as_of"],"source_file":result["source_file"],
            "record_count":result["record_count"],
            "imported_at":datetime.now(timezone.utc).isoformat(),
        })
        for record in result["records"]:
            key={"provider":record["provider"],"region":record["region"],
                 "as_of":record["as_of"],"industry":record["industry"]}
            await db.valuation_sector_benchmarks.update_one(key,{"$set":record},upsert=True)
    print(json.dumps({k:v for k,v in result.items() if k!="records"},
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    asyncio.run(main())
