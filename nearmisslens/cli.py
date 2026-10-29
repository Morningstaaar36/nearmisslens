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


def cmd_panel(args) -> int:
    from . import panel
    from .countermeasures import load_cmf
    from .meta_client import MetaClient
    src = SETTINGS.runs_dir / "audit" / f"{args.split}_{args.source}"
    if not (src / "facts.json").exists():
        print(f"no audit at {src}; run: nml audit {args.split} --source {args.source}")
        return 1
    client = MetaClient(SETTINGS)
    usd = sum(panel.BUDGET_USD.values())
    client.meter.check(usd, f"panel {args.split}")
    print(f"review panel: up to ${usd:.2f} (cached calls are free)")
    result = panel.run_panel(client, json.loads((src / "facts.json").read_text()), (src / "memo.md").read_text(),
                             load_cmf(), f"panel {args.split}_{args.source}")
    panel.write(result, src, f"{args.split} ({args.source})")
    print((src / "panel.md").read_text())
    return 0 if result["status"] == "complete" else 1


def cmd_export(args) -> int:
    from .export import export
    path = export(args.split, args.source)
    print(f"written {path} ({path.stat().st_size / 1e6:.1f} MB); preview: python -m http.server -d docs")
    return 0


def cmd_voice(args) -> int:
    from .runner import run_voice
    out = run_voice(args.split, args.source, args.audio)
    report = json.loads(out.read_text())
    for r in report["results"]:
        m = r["match"]
        where = f"hotspot {m['rank']} ({'; '.join(m['evidence'])})" if m["rank"] else "no hotspot in this audit shows it"
        print(f"- {r['transcript']}\n  -> {r['complaint']['concern']} [{where}]"
              + (f" {'correct' if r['correct'] else 'WRONG'}, WER {r['word_error_rate']}" if r.get("synthetic") else ""))
    print(json.dumps(report["summary"]))
    print(f"written to {out}")
    return 0


def cmd_baseline(args) -> int:
    from .baseline import run_b0
    print(json.dumps(run_b0(split=args.split), indent=1, default=float))
    return 0


def cmd_verifier(args) -> int:
    from .runner import run_verifier
    print(json.dumps(run_verifier(args.split), indent=1, default=float))
    return 0


def cmd_fetch(_args) -> int:
    from .fetch import fetch_all
    for p in fetch_all():
        print(f"ok {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nml", description="NearMissLens: an AI road-safety audit agent")
    parser.add_argument("--replay", action="store_true", help="serve model calls from the cache only")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download FLUID clips and derived data, and the CMF Clearinghouse table (about 2 GB)")
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
    pa = sub.add_parser("panel", help="Proposer, Skeptic and Judge agents review an audit, held to the data by a checker")
    pa.add_argument("split", choices=["dev", "test", "heldout"])
    pa.add_argument("--source", choices=["reference", "sam"], default="reference")
    ex = sub.add_parser("export", help="viewer data (docs/) from an audit run")
    ex.add_argument("split", choices=["dev", "test", "heldout"])
    ex.add_argument("--source", choices=["reference", "sam"], default="reference")
    vo = sub.add_parser("voice", help="match a spoken complaint to the audit's hotspots (Muse Voice Transcribe + Muse Spark); "
                                      "without --audio, test on synthetic complaints spoken by MMS-TTS")
    vo.add_argument("split", choices=["dev", "test", "heldout"])
    vo.add_argument("--source", choices=["reference", "sam"], default="reference")
    vo.add_argument("--audio", help="a recording in any format ffmpeg reads")
    b0 = sub.add_parser("baseline", help="B0: Muse Spark alone watches 10 s windows and lists near-misses, scored "
                                         "with the pipeline against the reference")
    b0.add_argument("split", choices=["dev", "test", "heldout"], nargs="?", default="test")
    vf = sub.add_parser("verifier", help="Muse Spark reviews every candidate conflict on SAM tracks; precision and "
                                         "recall against the reference before and after")
    vf.add_argument("split", choices=["dev", "test", "heldout"])
    st = sub.add_parser("selftest", help="end-to-end check on real data and cached model responses")
    st.add_argument("--live", action="store_true", help="allow Meta API calls for missing cache entries")
    args = parser.parse_args(argv)
    if args.replay:
        SETTINGS.replay = True
    from .cache import ReplayMiss
    from .cost import BudgetExceeded
    try:
        return run_command(args)
    except ReplayMiss as e:
        print(f"not in the replay cache: {e}. Run without --replay to fetch it from the Meta Model API (paid).")
    except BudgetExceeded as e:
        print(f"stopped by the spending cap: {e}")
    return 2


def run_command(args) -> int:
    return {"cost": cmd_cost, "metrics": cmd_metrics, "selftest": cmd_selftest, "evaluate": cmd_evaluate, "audit": cmd_audit,
            "panel": cmd_panel, "export": cmd_export,
            "voice": cmd_voice, "baseline": cmd_baseline,
            "verifier": cmd_verifier, "fetch": cmd_fetch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
