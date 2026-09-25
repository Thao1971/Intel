"""Preview or publish candidate Iberinform sector valuation calibrations.

Default is read-only preview. --publish writes immutable candidate documents but never
activates them for valuation.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.engines.valuation.calibration_job import run_calibration  # noqa: E402

def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff-date", help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--max-companies", type=int)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--publish", action="store_true",
                        help="Write candidates; does not activate them")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    return parser.parse_args()

async def main():
    args = arguments()
    result = await run_calibration(
        cutoff_date=args.cutoff_date, max_companies=args.max_companies,
        batch_size=args.batch_size, publish=args.publish)
    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload)

if __name__ == "__main__":
    asyncio.run(main())
