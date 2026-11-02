from __future__ import annotations

import argparse
import json
import sys

from .config import SETTINGS, portable, resolve
from .cost import CostMeter
from .runlog import metrics_markdown, read_metrics
from .config import MODELS


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
    from .evaluate import RESULTS_DIR, results_markdown, run_split, signal_agreement, write_results
    from .meta_client import MetaClient
    client = MetaClient(SETTINGS)
    summaries = []
    for name in args.splits:
        summaries.append(run_split(name, client, SETTINGS.data_dir / "work", RESULTS_DIR))
        run_split(name, client, SETTINGS.data_dir / "work", RESULTS_DIR, stitch=True)
        signal_agreement(name)
    write_results()
    print(results_markdown(summaries))
    return 0


def cmd_results(_args) -> int:
    from .evaluate import SPLITS, RESULTS_DIR, signal_agreement, write_results
    for name in SPLITS:
        if (RESULTS_DIR / name / "summary.json").exists():
            signal_agreement(name)
    print(write_results())
    return 0


def cmd_audit(args) -> int:
    from .runner import run_audit
    out = run_audit(args.split, args.source, verify_n=args.verify, illustrate=args.illustrate)
    print((out / "memo.md").read_text())
    print(f"written to {out}")
    return 0


def cmd_panel(args) -> int:
    from . import panel
    from .audit import facts_id
    from .countermeasures import load_cmf
    from .meta_client import MetaClient
    src = SETTINGS.runs_dir / "audit" / f"{args.split}_{args.source}"
    if not (src / "facts.json").exists():
        print(f"no audit at {src}; run: nml audit {args.split} --source {args.source}")
        return 1
    client = MetaClient(SETTINGS)
    usd = sum(panel.BUDGET_USD.values())
    client.check_budget(usd, f"panel {args.split}")
    print(f"review panel: up to ${usd:.2f} (cached calls are free)")
    facts_json = (src / "facts.json").read_text()
    result = panel.run_panel(client, json.loads(facts_json), (src / "memo.md").read_text(),
                             load_cmf(), f"panel {args.split}_{args.source}")
    result["facts_id"] = facts_id(facts_json)
    panel.write(result, src, f"{args.split} ({args.source})")
    print((src / "panel.md").read_text())
    return 0 if result["status"] == "complete" else 1


def cmd_export(args) -> int:
    from .export import export
    path = export(args.split, args.source)
    print(f"written {path} ({path.stat().st_size / 1e6:.1f} MB); preview: python -m http.server -d docs/video")
    return 0


def cmd_programs(args) -> int:
    from . import programscout
    res = programscout.discover(_memo_client(not args.meta), args.city, save=not args.dry_run,
                                skip_known=not args.all)
    for a in res["found"]:
        print(f"found: {a['source']} | date {a['date_field']} | filter {a.get('where')} | {a['label']} | "
              f"{a.get('countermeasure')} | {a['provenance']['validation']['usable_dated']} usable dated records")
    print(f"{len(res['tried'])} other layers turned down")
    return 0


def cmd_gate(args) -> int:
    from . import bench, treatments
    out = treatments.run_suite(treatments.auto_spec(args.city))
    for k, g in out["gates"].items():
        m = out["runs"][g["primary"]][g["outcome"]] or {}
        print(f"{g['treatment']}: {'passed' if g['passed'] else 'not shown (' + str(g['reason']) + ')'}; "
              f"{m.get('change_pct')}% {m.get('ci95')} on {m.get('sites')} sites")
    bench.write_bench_md()
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


def cmd_fetch(args) -> int:
    from . import fluid
    from .fetch import CLIPS, fetch_all
    for p in fetch_all(clips=fluid.FLIGHTS if args.all else CLIPS):
        print(f"ok {p}")
    return 0


def cmd_demo(args) -> int:
    if args.copilot:
        from .demo_copilot import render as render_copilot
        render_copilot()
        return 0
    from .demo import render
    render(args.audit)
    return 0


def cmd_experiment(_args) -> int:
    from .evaluate import experiment_usd, two_wheeler_experiment
    from .meta_client import MetaClient
    client = MetaClient(SETTINGS)
    usd = experiment_usd()
    client.check_budget(usd, "two-wheeler experiment")
    print(f"two-wheeler experiment on dev: up to ${usd:.2f} (cached calls are free)")
    for r in two_wheeler_experiment(client):
        print(json.dumps(r, default=float))
    return 0


def cmd_bench(args) -> int:
    from . import bench, evaluate
    from .meta_client import MetaClient
    client = MetaClient(SETTINGS)
    if args.free:
        print(json.dumps(bench.persistence()["summary"], indent=1, default=float))
        print(json.dumps(bench.fix_test()["summary"], indent=1, default=float))
    if args.kinematics:
        print(json.dumps(evaluate.tune_kinematics()["chosen"], indent=1, default=float))
        for split in ("test", "heldout"):
            evaluate.rescore_split(split)
        evaluate.write_results()
    if args.fresh:
        usd = bench.fresh_estimate()
        client.check_budget(usd, "fresh flights")
        print(f"fresh flights: SAM 3.1 on 11 one-minute windows, up to ${usd:.2f} (cached calls are free)")
        print(json.dumps(bench.fresh_flights(client).get("pooled"), indent=1, default=float))
    if args.agents:
        print(json.dumps(bench.complaints_bench(client)["summary"], indent=1, default=float))
        bench.panel_ablation(client)
        print(json.dumps(bench.context_bench(client)["summary"], indent=1, default=float))
    if args.conductor:
        print(json.dumps(bench.conductor_bench(client)["policies"], indent=1, default=float))
    text = bench.write_bench_md()
    print(f"written validation/BENCH.md ({len(text.splitlines())} lines)")
    return 0


def cmd_ask(args) -> int:
    from . import ask
    from .countermeasures import load_cmf
    from .meta_client import MetaClient
    client = MetaClient(SETTINGS)
    name = f"{args.split}_{args.source}"
    if args.serve:
        from .serve import serve
        return serve(name, args.port)
    text = args.text
    if args.audio:
        from pathlib import Path
        from .runner import as_wav
        from .voice import transcribe
        text = transcribe(client, as_wav(Path(args.audio), SETTINGS.data_dir / "work" / "voice"), f"ask {name}")["transcript"]
        print(f"transcript: {text}")
    facts, memo_md = ask.load(name, SETTINGS.runs_dir)
    out = ask.answer(client, text, facts, memo_md, load_cmf(), SETTINGS.data_dir / "work" / "ask_frames", f"ask {name}",
                     model=args.model, budget_usd=0.12 if "wonder" in args.model else 0.02)
    print(json.dumps(out["result"], indent=1))
    print(f"{out['turns']} turns, ${out['usd']}, stopped: {out['stopped']}")
    return 0


def cmd_context(args) -> int:
    from . import context
    from .meta_client import MetaClient
    d = context.dossier(args.lat, args.lon)
    print(json.dumps({k: v for k, v in d.items() if k != "street"} | {"street": {k: v for k, v in (d.get("street") or {}).items()
                                                                              if k != "roads"}}, indent=1, default=str))
    if not args.no_memo:
        m = context.memo(MetaClient(SETTINGS), d, f"context {args.lat},{args.lon}")
        print("\n" + m["memo"] + f"\n(${m['usd']}, checker errors: {m['errors'] or 'none'})")
    return 0


def cmd_office(args) -> int:
    from . import office
    from .countermeasures import load_cmf
    from .meta_client import MetaClient
    client = MetaClient(SETTINGS)
    client.check_budget(office.BUDGET_USD, "office")
    name = f"{args.split}_{args.source}"

    def ask_person(summary: str) -> dict:
        if args.auto:
            return {"approved": True, "by": "auto", "note": ""}
        print(f"\nThe manager asks for sign-off:\n  {summary}")
        ans = input("approve? [y/N/comment] ").strip()
        return {"approved": ans.lower().startswith("y"), "by": "city engineer (CLI)", "note": ans}

    out = office.run(client, name, args.complaint or [], load_cmf(), signoff=ask_person, tag=f"office {name}")
    path = office.write(out, SETTINGS.runs_dir / "audit" / name)
    for e in out["timeline"]:
        print(f"[turn {e['turn']}] " + (f"thinks: {e['text'][:160]}" if e["kind"] == "thought" else
                                         f"{e['tool']}({json.dumps(e['arguments'])[:100]}) {e['seconds']}s"))
    wo = out["work_order"]
    print("\nWORK ORDER:\n" + (wo["work_order"] if wo else f"none ({out['stopped']})"))
    print(f"{out['turns']} turns, ${out['usd']}, refusals {out['refusals']}; written {path}")
    return 0


def _memo_client(open_weights: bool):
    if open_weights:
        from .openclient import OpenWeightsClient
        return OpenWeightsClient()
    from .meta_client import MetaClient
    return MetaClient(SETTINGS)


def cmd_engineer(args) -> int:
    from . import engineer
    letter_client = _memo_client(not args.meta) if args.letter else None
    rep = engineer.run(args.query, _memo_client(True), letter_client=letter_client) if args.agent else \
        engineer.plan(args.query, letter_client=letter_client)
    # each mode keeps its own report, so a fixed-order run never overwrites an agent run
    out = SETTINGS.runs_dir / "engineer" / "cli" / rep["mode"] / f"{engineer.slug(rep['junction']['name'])}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(portable(json.dumps(rep, indent=1, default=str)))
    print(engineer.text(rep))
    lt = (rep["findings"].get("draft_request") or {}).get("letter")
    if lt:
        print("\n" + lt)
    if args.agent:
        print(f"\nagent: {rep.get('turns')} turns, ${rep.get('usd')}, stopped: {rep.get('stopped')}; "
              f"summary: {rep.get('summary')}")
    print(f"\nwritten {portable(str(out))}")
    return 0 if not rep["claim_errors"] else 1


def cmd_desk(args) -> int:
    from . import desk_runs
    from .meta_client import MetaClient
    from .openclient import OpenWeightsClient
    if args.spec == "T22":
        reps = desk_runs.run_governed(OpenWeightsClient())
        print(f"{len(reps)} governed cases, {sum(bool(r.get('finished')) for r in reps)} finished")
        return 0
    res = desk_runs.run_desk(args.spec, MetaClient(SETTINGS), OpenWeightsClient(), fresh=args.fresh)
    print(f"{sum(bool(c.get('finished')) for c in res['cases'])} of {len(res['cases'])} published")
    return 0


def cmd_alone(args) -> int:
    from . import baseline_desk
    from .meta_client import MetaClient
    res = baseline_desk.run(args.spec, MetaClient(SETTINGS), args.inputs)
    print(baseline_desk.summary(res))
    return 0


def cmd_cameras(args) -> int:
    import time as _t
    from . import cameras
    from .evaluate import RESULTS_DIR
    path = RESULTS_DIR / "bench" / f"cameras_{args.city}_picks.json"
    if args.action == "pick" or not path.exists():
        picks = cameras.pick(args.city, args.n)
        path.write_text(json.dumps(picks, indent=1))
        print(f"{len(picks)} cameras at the intersections with the most injury crashes: {path}")
    picks = json.loads(path.read_text())
    if args.action == "once":
        print(json.dumps(cameras.collect_once(picks, cameras.adapter(args.city))))
    elif args.action == "collect":
        cameras.collect(args.city, picks, args.every, _t.time() + 3600 * args.hours, log=lambda s: print(s, flush=True))
    return 0


def cmd_agent_cases(args) -> int:
    from . import engineer
    reps = engineer.agent_cases(args.city, _memo_client(True), top=args.top)
    usd = sum(r.get("usd") or 0 for r in reps)
    print(f"{len(reps)} agent cases, {sum(bool(r.get('finished')) for r in reps)} finished, "
          f"{sum(len(r.get('refused_attempts') or []) for r in reps)} refused attempts, ${usd:.2f}")
    return 0


def cmd_pack_cache(args) -> int:
    from pathlib import Path
    from . import packcache
    out = packcache.pack(Path(args.out))
    print(f"{out['files']} files, contact details removed from {out['scrubbed']}, {out['mb']} MB: {out['path']}")
    return 0


def cmd_ask_engineer(args) -> int:
    from . import askeng, citywide
    city = args.city or next(iter(citywide.cities()), None)
    out = askeng.ask(city, args.slug, args.question, _memo_client(True))
    print(out["answer"] or f"no answer ({out['stopped']})")
    for c in out["claims"]:
        print(f"- {c['text']}  [{c['receipt']}]")
    for r in out["refused"]:
        print(f"  refused: {r['text']}  ({'; '.join(r['errors'])})")
    print(f"{out['turns']} turns, ${out['usd']}, {out['seconds']} s")
    return 0 if out["answer"] else 1


def cmd_plan(args) -> int:
    from . import plan
    out = plan.build(args.city)
    path = plan.write(out)
    path.with_suffix(".csv").write_text(plan.to_csv(out))
    s, r = out["summary"], out["regression_to_mean"]
    print(f"{out['city_name']}: {s['corners']} corners, {s['injury_crashes_total']:,} injury crashes "
          f"(harm ${(s['harm_usd_per_year'] or s['harm_usd_per_year_summed']) / 1e6:,.0f}M a year)")
    print(f"  supported low-cost fix at {s['corners_with_supported_fix']} corners {s['supported_by_tier']}: "
          f"{s['crashes_avoided_per_year_total']} crashes a year, {s['crashes_avoided_per_year_after_rtm']} after "
          f"regression to the mean (factor {r.get('factor')}); textbook estimate {s['textbook_crashes_avoided_per_year']}")
    for g in out["agencies"]:
        print(f"  {g['party']}: {g['intersections']} corners, letter "
              f"{'checked' if g['letter']['body'] else 'refused: ' + '; '.join(g['letter']['refused'])}")
    print(f"written {path} and {path.with_suffix('.csv').name}")
    return 0 if all(g["letter"]["body"] for g in out["agencies"]) else 1


def cmd_pages(args) -> int:
    from pathlib import Path
    from . import pages
    lc = _memo_client(not args.meta) if args.letters else None
    mc = None
    if args.model_check:
        from .meta_client import MetaClient
        mc = MetaClient(SETTINGS)
    out = pages.build(args.city, args.live or "", Path(args.out) if args.out else pages.DOCS, letters=args.letters,
                      letter_client=lc, workers=args.workers, saved_only=args.saved_only, model_check_client=mc)
    print(f"{out['corners']} corners, {out['letters']} letters, {out['mb']} MB in {out['path']}; claims refused: "
          f"{out['claim_errors']}. Preview: python -m http.server -d {out['path']}")
    return 0


def cmd_brief(args) -> int:
    from . import brief
    from .meta_client import MetaClient
    target = dict(address=args.place) if args.place else dict(lat=args.lat, lon=args.lon)
    f = brief.build(**target, client=_memo_client(not args.meta), memo=not args.no_memo)
    if args.illustrate and f.get("aerial_photo") and f["fixes"]["options"]:
        from pathlib import Path
        out = resolve(f["aerial_photo"]).parent
        f["illustration"] = brief.illustrate_fix(MetaClient(SETTINGS), resolve(f["aerial_photo"]), f["fixes"]["options"],
                                                 out, out.name)
        (out / "brief.json").write_text(portable(json.dumps(f, indent=1, default=str)))
    cr = f["dossier"].get("crashes") or {}
    print(f"{f['junction']}\n  {cr.get('crashes')} crashes, {cr.get('injury_crashes')} injury crashes in "
          f"{f['dossier']['years']} years ({cr.get('source', cr.get('error'))}); plan gap: {f['dossier'].get('plan_gap')}")
    for o in f["fixes"]["options"][:6]:
        print(f"  - {o['countermeasure']}: CMF {o['cmf_id']} ({o['cmf']}, {o['stars']}), "
              f"{o['expected_crashes_avoided_per_year']} crashes avoided/yr, ${o['harm_avoided_usd_per_year']:,.0f}/yr of harm"
              + (f" [verify on site: {o['verify_on_site']}]" if o["verify_on_site"] else ""))
    if f.get("brief", {}).get("brief"):
        print("\n" + f["brief"]["brief"])
    if args.letter:
        from pathlib import Path
        from . import letter
        d = f["dossier"]
        res = letter.draft(_memo_client(not args.meta), f, letter.offices(d["lat"], d["lon"]),
                           tag=f"letter {f['junction'][:40]}")
        print("\n" + (res["letter"] or f"no letter: {res['checker_errors']}"))
        if res["letter"] and f.get("aerial_photo"):
            (resolve(f["aerial_photo"]).parent / "letter.md").write_text(res["letter"])
    return 0


def cmd_discover(args) -> int:
    from . import datascout
    r = datascout.discover(_memo_client(not args.meta), args.lat, args.lon, save=not args.dry_run)
    for t in r["tried"]:
        print(f"  rejected {t['candidate']}: {str(t['rejected'])[:160]}")
    a = r["adapter"]
    print(f"adapter for {r['place']['city']}: " + (f"{a['id']} ({a['source']}), validation {a['provenance']['validation']}"
                                                 if a else "none found"))
    return 0 if a else 1


def cmd_programs(args) -> int:
    from . import programscout
    res = programscout.discover(_memo_client(not args.meta), args.city, save=not args.dry_run,
                                skip_known=not args.all)
    for a in res["found"]:
        print(f"found: {a['source']} | date {a['date_field']} | filter {a.get('where')} | {a['label']} | "
              f"{a.get('countermeasure')} | {a['provenance']['validation']['usable_dated']} usable dated records")
    print(f"{len(res['tried'])} other layers turned down")
    return 0


def cmd_gate(args) -> int:
    from . import bench, treatments
    out = treatments.run_suite(treatments.auto_spec(args.city))
    for k, g in out["gates"].items():
        m = out["runs"][g["primary"]][g["outcome"]] or {}
        print(f"{g['treatment']}: {'passed' if g['passed'] else 'not shown (' + str(g['reason']) + ')'}; "
              f"{m.get('change_pct')}% {m.get('ci95')} on {m.get('sites')} sites")
    bench.write_bench_md()
    return 0


def cmd_voice_studio(args) -> int:
    from . import voicestudio
    return voicestudio.serve(args.port)


def cmd_treatments(args) -> int:
    from . import bench, treatments
    names = args.study or sorted(p.stem for p in treatments.STUDIES.glob("*.json"))
    for name in names:
        out = treatments.run_suite(treatments.load_spec(name))
        print(name, json.dumps({k: {"passed": g["passed"], "reason": g["reason"],
                                    "effect": out["runs"][g["primary"]][g["outcome"]]} for k, g in out["gates"].items()},
                               indent=1, default=float))
    bench.write_bench_md()
    return 0


def cmd_citywide(args) -> int:
    from . import citywide
    city = args.city or citywide.cities()[0]
    df = citywide.screen(city)
    print(json.dumps(citywide.write(df, city=city), indent=1))
    return 0


def cmd_app(args) -> int:
    from .app import serve
    return serve(args.port, open_weights=not args.meta, illustrate=args.illustrate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nml", description="NearMissLens: an agentic safety engineer for city streets")
    parser.add_argument("--replay", action="store_true", help="serve model calls from the cache only")
    sub = parser.add_subparsers(dest="cmd", required=True)
    fe = sub.add_parser("fetch", help="download FLUID clips and derived data, and the CMF Clearinghouse table (about 2 GB)")
    fe.add_argument("--all", action="store_true", help="all 14 FLUID flights for NML-Bench (about 19 GB more)")
    sub.add_parser("cost", help="Meta API spend so far")
    sub.add_parser("experiment", help="two-wheeler concepts and tile grids on the development clip (PREREG change 8)")
    sub.add_parser("results", help="regenerate validation/RESULTS.md from stored results (free)")
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
    pa = sub.add_parser("panel", help="Proposer, Skeptic and Arbiter agents review an audit, held to the data by a checker")
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
    de = sub.add_parser("demo", help="render the demo video from viewer recordings and run outputs")
    de.add_argument("--audit", help="viewer audit key, e.g. heldout_sam (default: the best available)")
    de.add_argument("--copilot", action="store_true", help="the safety-engineer demo: your voice-studio takes, Kokoro guide voice for lines not yet recorded")
    bn = sub.add_parser("bench", help="NML-Bench (validation/BENCH_PREREG.md); without flags only rewrites BENCH.md")
    bn.add_argument("--free", action="store_true", help="T3 persistence and T7 fix test on all 14 flights ($0)")
    bn.add_argument("--kinematics", action="store_true", help="tune Kalman/RTS on dev, re-score test and held-out ($0)")
    bn.add_argument("--fresh", action="store_true", help="T1-T2 on the 11 fresh windows (paid SAM 3.1, cached)")
    bn.add_argument("--agents", action="store_true", help="T4 complaints, T5 panel ablation, T8 city context (paid, small)")
    bn.add_argument("--conductor", action="store_true", help="T6 budgeted perception on the held-out site (paid)")
    ak = sub.add_parser("ask", help="intake agent: check a resident's complaint against an audit")
    ak.add_argument("split", choices=["dev", "test", "heldout"])
    ak.add_argument("text", nargs="?", default="")
    ak.add_argument("--source", choices=["reference", "sam"], default="sam")
    ak.add_argument("--audio", help="a recording in any format ffmpeg reads (Muse Voice Transcribe)")
    ak.add_argument("--model", default=MODELS["large"])
    ak.add_argument("--serve", action="store_true", help="local web page with a microphone button")
    ak.add_argument("--port", type=int, default=8765)
    cx = sub.add_parser("context", help="what the official record says about a junction (OSM, crashes, city plans)")
    cx.add_argument("lat", type=float)
    cx.add_argument("lon", type=float)
    cx.add_argument("--no-memo", action="store_true")
    of = sub.add_parser("office", help="manager agent: end-to-end review with human sign-off and a work order")
    of.add_argument("split", choices=["dev", "test", "heldout"])
    of.add_argument("--source", choices=["reference", "sam"], default="sam")
    of.add_argument("--complaint", action="append", help="a resident complaint to check (repeatable)")
    of.add_argument("--auto", action="store_true", help="approve the sign-off automatically")
    br = sub.add_parser("brief", help="Junction Safety Brief: official record, ranked cited fixes, checked memo")
    br.add_argument("place", nargs="?", help='an intersection, e.g. "Delancey Street & Essex Street, Manhattan, NY"')
    br.add_argument("--lat", type=float)
    br.add_argument("--lon", type=float)
    br.add_argument("--illustrate", action="store_true", help="draw the top fix on the aerial photo (Muse Image + SAM)")
    br.add_argument("--no-memo", action="store_true")
    br.add_argument("--meta", action="store_true", help="memo on the Meta API instead of Muse Spark Open (Baseten)")
    br.add_argument("--letter", action="store_true", help="also draft a checked letter to the council member and community board")
    dsc = sub.add_parser("discover", help="data agent: find and validate a city's open crash data for the registry")
    dsc.add_argument("lat", type=float)
    dsc.add_argument("lon", type=float)
    dsc.add_argument("--dry-run", action="store_true")
    dsc.add_argument("--meta", action="store_true")
    dk = sub.add_parser("desk", help="run the desk on a registered spec (T21, T21b, T21c) or the governed agent (T22); paid unless --replay")
    dk.add_argument("spec")
    dk.add_argument("--fresh", action="store_true", help="run every case again instead of resuming from saved results")
    al = sub.add_parser("alone", help="T24: Muse Spark with web_search alone on a desk run's inputs, scored by code (paid)")
    al.add_argument("spec", nargs="?", default="T24")
    al.add_argument("--inputs", default="T21c", help="the registered desk run whose inputs it gets")
    cm = sub.add_parser("cameras", help="Corner Watch: pick the city's camera corners by injury crashes; collect frames (free)")
    cm.add_argument("action", choices=["pick", "once", "collect"])
    cm.add_argument("city")
    cm.add_argument("--n", type=int, default=40)
    cm.add_argument("--every", type=int, default=600, help="seconds between rounds (never faster than the city refreshes)")
    cm.add_argument("--hours", type=float, default=24.0)
    ag = sub.add_parser("agent-cases", help="Muse Spark Open writes its own case for a city's top corners (paid; saved cases are reused)")
    ag.add_argument("city")
    ag.add_argument("--top", type=int, default=20)
    pl = sub.add_parser("plan", help="the city's action plan from its saved cases: evidence-tiered fixes, totals, one checked letter per agency")
    pl.add_argument("city")
    cw = sub.add_parser("citywide", help="plan-gap screen of every priority intersection a city lists (open data)")
    cw.add_argument("--city", help="registry city id (default: the first city with a priority-intersection list)")
    pg = sub.add_parser("programs", help="program agent: find a city's dated safety programs for the causal gate")
    pg.add_argument("city")
    pg.add_argument("--dry-run", action="store_true")
    pg.add_argument("--all", action="store_true", help="also re-map layers already in the registry")
    pg.add_argument("--meta", action="store_true")
    ga = sub.add_parser("gate", help="run the causal gate on every program the program agent found for a city")
    ga.add_argument("city")
    vs = sub.add_parser("voice-studio", help="voice studio: record the demo narration line by line in the browser")
    vs.add_argument("--port", type=int, default=8792)
    tm = sub.add_parser("treatments", help="city treatment studies with the causal gate (validation/studies/*.json)")
    tm.add_argument("study", nargs="*", help="study ids (default: all registered studies)")
    ap = sub.add_parser("app", help="Junction Safety Copilot web app on 127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--illustrate", action="store_true")
    ap.add_argument("--meta", action="store_true")
    en = sub.add_parser("engineer", help="the safety engineer: worst corner, what its crashes have in common, what the "
                                         "city tried, the fix, who must act, the request; every claim with a receipt")
    en.add_argument("query", help='a city id (e.g. nyc: take its worst corner) or an intersection address')
    en.add_argument("--agent", action="store_true", help="let Muse Spark Open choose the steps and write the claims")
    en.add_argument("--letter", action="store_true", help="draft the checked request letter (Muse Spark Open)")
    en.add_argument("--meta", action="store_true", help="draft the letter on the Meta API instead")
    ae = sub.add_parser("ask-engineer", help="ask a question about a corner; Muse Spark Open answers from its receipts, checked")
    ae.add_argument("slug", help="the corner id (as in the copilot's URL)")
    ae.add_argument("question")
    ae.add_argument("--city", help="a registry city id (default: the first city with a saved screen)")
    pk = sub.add_parser("pack-cache", help="the replay cache for the GitHub release, contact details removed, refused if a key is found")
    pk.add_argument("--out", default="runs/release/nearmisslens_replay_cache.tar.gz")
    pg2 = sub.add_parser("pages", help="the static copilot for GitHub Pages: one engineer report per screened corner (docs/)")
    pg2.add_argument("--city", help="a registry city id (default: the first city with a saved screen)")
    pg2.add_argument("--live", help="https URL of the live endpoint for addresses outside the precomputed corners")
    pg2.add_argument("--letters", type=int, default=0, help="draft checked letters for the worst N corners (Muse Spark Open)")
    pg2.add_argument("--meta", action="store_true", help="draft letters on the Meta API instead")
    pg2.add_argument("--workers", type=int, default=3)
    pg2.add_argument("--saved-only", action="store_true", help="only corners already built (a quick preview)")
    pg2.add_argument("--model-check", action="store_true", help="recheck agent cases with the model-read check too (T20b)")
    pg2.add_argument("--out", help="write somewhere other than docs/")
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
            "verifier": cmd_verifier, "fetch": cmd_fetch,
            "demo": cmd_demo, "results": cmd_results,
            "experiment": cmd_experiment, "bench": cmd_bench, "ask": cmd_ask, "context": cmd_context,
            "office": cmd_office, "brief": cmd_brief, "discover": cmd_discover, "citywide": cmd_citywide, "treatments": cmd_treatments,
            "voice-studio": cmd_voice_studio, "programs": cmd_programs, "gate": cmd_gate,
            "app": cmd_app, "engineer": cmd_engineer, "pages": cmd_pages, "plan": cmd_plan, "agent-cases": cmd_agent_cases, "cameras": cmd_cameras, "desk": cmd_desk, "alone": cmd_alone, "pack-cache": cmd_pack_cache, "ask-engineer": cmd_ask_engineer}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
