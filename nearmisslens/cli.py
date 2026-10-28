from __future__ import annotations

import argparse
import json
import sys

from .config import SETTINGS
from .cost import CostMeter
from .runlog import metrics_markdown, read_metrics


def cmd_cost(_args) -> int:
    print(json.dumps(CostMeter(SETTINGS.ledger, SETTINGS.budget_usd).summary(), indent=1))
    return 0


def cmd_metrics(_args) -> int:
    print(metrics_markdown(read_metrics()))
    return 0


def cmd_selftest(args) -> int:
    from .selftest import main as run_selftest
    return run_selftest(replay=not args.live)


def cmd_evaluate(args) -> int:
    import json
    from .config import ROOT
    from .evaluate import SPLITS, results_markdown, run_split
    from .meta_client import MetaClient
    client = MetaClient(SETTINGS)
    out_root = ROOT / "validation" / "results"
    summaries = []
    for name in args.splits:
        summaries.append(run_split(name, client, SETTINGS.data_dir / "work", out_root))
    existing = []
    for name in SPLITS:
        p = out_root / name / "summary.json"
        if p.exists():
            existing.append(json.loads(p.read_text()))
    (ROOT / "validation" / "RESULTS.md").write_text(results_markdown(existing))
    print(results_markdown(summaries))
    return 0


def cmd_audit(args) -> int:
    from .runner import run_audit
    out = run_audit(args.split, args.source, verify_n=args.verify, illustrate=args.illustrate)
    print((out / "memo.md").read_text())
    print(f"written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nml", description="NearMissLens: an AI road-safety audit agent")
    parser.add_argument("--replay", action="store_true", help="serve model calls from the cache only")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cost", help="Meta API spend so far")
    sub.add_parser("metrics", help="latest logged metrics per stage, clip and class")
    ev = sub.add_parser("evaluate", help="track and score pre-registered splits (dev, test, heldout)")
    ev.add_argument("splits", nargs="+", choices=["dev", "test", "heldout"])
    au = sub.add_parser("audit", help="site audit memo: conflicts, hotspots, cited countermeasures")
    au.add_argument("split", choices=["dev", "test", "heldout"])
    au.add_argument("--source", choices=["reference", "sam"], default="reference",
                    help="reference: FLUID trajectories (no model calls); sam: SAM 3.1 tracks from nml evaluate")
    au.add_argument("--verify", type=int, default=0, metavar="N",
                    help="Muse Spark reviews the video of each hotspot's N most severe conflicts")
    au.add_argument("--illustrate", action="store_true",
                    help="Muse Image before/after of the first illustratable countermeasure per hotspot, checked by SAM 3.1")
    st = sub.add_parser("selftest", help="end-to-end check on real data and cached model responses")
    st.add_argument("--live", action="store_true", help="allow Meta API calls for missing cache entries")
    args = parser.parse_args(argv)
    if args.replay:
        SETTINGS.replay = True
    return {"cost": cmd_cost, "metrics": cmd_metrics, "selftest": cmd_selftest, "evaluate": cmd_evaluate, "audit": cmd_audit}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
