"""Review or activate a published Iberinform valuation calibration run."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db  # noqa: E402
from services.engines.valuation.calibration_promotion import activate_run, review_run  # noqa: E402


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("action", choices=("review", "activate"))
    parser.add_argument("--approver", required=True)
    parser.add_argument("--notes")
    parser.add_argument("--ruleset-version")
    return parser.parse_args()


async def main():
    args = arguments()
    if args.action == "review":
        result = await review_run(db, args.run_id, approver=args.approver, notes=args.notes)
    else:
        result = await activate_run(
            db, args.run_id, approver=args.approver, notes=args.notes,
            ruleset_version=args.ruleset_version)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
