from __future__ import annotations

import argparse
import json
import sys

from .config import SETTINGS
from .cost import CostMeter


def cmd_cost(_args) -> int:
    print(json.dumps(CostMeter(SETTINGS.ledger, SETTINGS.budget_usd).summary(), indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nml", description="NearMissLens: an AI road-safety audit agent")
    parser.add_argument("--replay", action="store_true", help="serve model calls from the cache only")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cost", help="Meta API spend so far")
    args = parser.parse_args(argv)
    if args.replay:
        SETTINGS.replay = True
    return {"cost": cmd_cost}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
