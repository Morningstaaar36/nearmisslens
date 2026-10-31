"""Junction Safety Copilot: a local web app for a city engineer. Search an address or click a NYC Vision Zero priority
intersection; the agents assemble the official record, rank cited fixes by expected crashes avoided, show the city's
aerial photo and a street-level photo, and write a checked Safety Brief. Runs on 127.0.0.1; keys stay on the machine."""
from __future__ import annotations

import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import brief, letter
from .config import SETTINGS
from .evaluate import RESULTS_DIR

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Junction Safety Copilot</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
<style>
:root{--bg:#0f1115;--fg:#e8eaed;--mut:#9aa0a6;--acc:#f5a524;--ok:#3ecf8e;--bad:#ef5350;--card:#181b22;--line:#2a2f3a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:19px;margin:0}.sub{color:var(--mut);font-size:13px}
input{flex:1;min-width:220px;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:9px}
button{background:var(--acc);color:#111;border:0;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);height:calc(100vh - 64px)}
#map{height:100%}#side{overflow:auto;padding:16px}
@media(max-width:860px){main{grid-template-columns:1fr;height:auto}#map{height:50vh}}
.card{background:var(--card);border-radius:12px;padding:14px;margin-bottom:14px}
.kpi{display:flex;gap:18px;flex-wrap:wrap}.kpi div{min-width:110px}.kpi b{font-size:22px;display:block}
.gap{color:var(--bad);font-weight:700}.nogap{color:var(--ok);font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.verify{color:var(--mut);font-style:italic}.local{color:var(--ok);font-size:12px;margin-top:4px}.imgs{display:grid;grid-template-columns:1fr 1fr;gap:8px}.imgs img{width:100%;border-radius:8px}
.memo{line-height:1.55}.legend{font-size:12px;color:var(--mut)}
</style></head><body>
<header><h1>Junction Safety Copilot</h1><span class="sub">Official record → cited fixes → checked brief. __CITIES__.</span>
<input id="q" placeholder="an intersection, e.g. __EXAMPLE__"><button id="go">Brief</button></header>
<main><div id="map"></div><div id="side"><div class="card"><b>How to use</b><p class="sub">Click a dot (NYC Vision Zero priority intersections; red = injury crashes and no recorded safety treatment in 5 years) or search an intersection. The brief takes 20–90 s the first time.</p><div id="top"></div></div><div id="out"></div></div></main>
<script>
const map=L.map('map').setView(__VIEW__,11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
fetch('/citywide').then(r=>r.json()).then(d=>{
 if(!d.rows)return;const s=d.summary;
 const usd=s.harm_usd_per_year?` Their injury crashes cost about <b>$${(s.harm_usd_per_year/1e6).toFixed(0)} million a year</b> in the U.S. DOT's official values.`:'';
 document.getElementById('top').innerHTML=`<p><b>${s.plan_gap} of ${s.intersections}</b> ${esc(d.city_name)} priority intersections had ≥10 injury crashes in 5 years and no recorded safety treatment nearby in that period (${(s.injury_crashes_distinct??s.injury_crashes_total).toLocaleString()} injury crashes, ${s.killed_distinct??s.killed_total} deaths at all ${s.intersections}).${usd}</p>`;
 for(const r of d.rows){const c=L.circleMarker([r.lat,r.lon],{radius:4+Math.sqrt(r.injury_crashes||0)/2,color:r.plan_gap?'#ef5350':'#3ecf8e',weight:1,fillOpacity:.6}).addTo(map);
  c.bindTooltip(`${esc(r.name)}: ${r.injury_crashes} injury crashes`);c.on('click',()=>run({lat:r.lat,lon:r.lon,name:r.name}));}});
fetch('/evidence').then(r=>r.json()).then(e=>{
 if(!e.programs||!e.programs.length)return;
 const pct=v=>(v>0?'+':'')+v+'%';
 const rows=e.programs.map(p=>`<tr><td>${p.passed?'<span class="nogap">✓ works</span>':'<span class="legend">✗ not shown</span>'}</td><td><b>${esc(p.program)}</b><div class="legend">${esc(p.city_name)} · ${p.sites??'?'} sites · vs ${esc(p.comparison)}</div></td><td>${p.effect_pct!=null?pct(p.effect_pct):'n/a'}${p.ci_pct?`<div class="legend">${pct(p.ci_pct[0])} to ${pct(p.ci_pct[1])}</div>`:''}</td><td class="legend">${p.passed?'placebo date before the install: '+pct(p.placebo_pct)+', no change':esc(p.reason||'')}</td></tr>`).join('');
 const f=e.fake_programs?`<p class="legend">The gate was also tested on ${e.fake_programs.gate.programs} fake programs (random sites and dates, nothing installed): it claimed an effect for ${(100*e.fake_programs.gate.rate).toFixed(1)}% of them, against ${(100*e.fake_programs.naive.rate).toFixed(1)}% for a simple before/after.</p>`:'';
 const div=document.createElement('div');div.className='card';
 div.innerHTML=`<b>What has worked here</b> <span class="legend">each program tested on the city's own crash records; a fix only counts if a fake earlier date shows no change</span><table style="margin-top:6px">${rows}</table>${f}`;
 document.getElementById('top').after(div);});
document.getElementById('go').onclick=()=>run({address:document.getElementById('q').value});
const qs=new URLSearchParams(location.search);
if(qs.get('q')){document.getElementById('q').value=qs.get('q');run(qs.get('lat')?{address:qs.get('q'),lat:+qs.get('lat'),lon:+qs.get('lon')}:{address:qs.get('q')});}
async function run(q){
 const out=document.getElementById('out');out.innerHTML='<div class="card">Assembling the official record, ranking fixes, writing the brief…</div>';
 const t0=Date.now();const r=await fetch('/brief',{method:'POST',body:JSON.stringify(q)});const f=await r.json();
 if(f.error){out.innerHTML=`<div class="card">Could not build the brief: ${esc(f.error)}</div>`;return;}
 const d=f.dossier,cr=d.crashes||{},pl=d.plans||{},fx=f.fixes||{};map.setView([d.lat,d.lon],17);
 const usd=v=>v==null?'n/a':'$'+Math.round(v).toLocaleString();
 const rows=(fx.options||[]).slice(0,8).map(o=>`<tr><td><b>${esc(o.countermeasure)}</b>${o.verify_on_site?`<div class="verify">verify on site: ${esc(o.verify_on_site)}</div>`:''}${o.local_evidence?`<div class="local">Tested on this city's own installs: ${esc(o.local_evidence.text)}</div>`:''}</td><td>CMF ${esc(o.cmf_id)}<br>${o.cmf} · ${esc(o.stars)}</td><td>${esc(o.targets)}<br>${o.target_crashes_per_year}/yr</td><td><b>${o.expected_crashes_avoided_per_year}</b>/yr</td><td><b>${usd(o.harm_avoided_usd_per_year)}</b>/yr<div class="legend">pays for itself under ${usd(o.break_even_cost_usd)}</div></td></tr>`).join('');
 const hm=fx.harm?`<div><b>$${(fx.harm.usd_per_year/1e6).toFixed(1)}M</b>a year in harm (USDOT)</div>`:'';
 const imgs=[f.aerial_photo?`<figure><img src="/media?p=${encodeURIComponent(f.aerial_photo)}"><figcaption class="legend">City aerial photo</figcaption></figure>`:'',
  f.street_photo?`<figure><img src="/media?p=${encodeURIComponent(f.street_photo.image)}"><figcaption class="legend">Street level, ${esc(f.street_photo.captured)} (<a href="${f.street_photo.url}" target="_blank">Mapillary</a>, CC BY-SA)</figcaption></figure>`:''].join('');
 const ill=f.illustration?`<div class="card"><b>Proposed fix, drawn by Muse Image on the city photo</b> (${esc(f.illustration.countermeasure)}; SAM 3.1 check ${f.illustration.check_passed?'passed':'failed'})<img style="width:100%;border-radius:8px;margin-top:8px" src="/media?p=${encodeURIComponent(f.illustration.image)}"></div>`:'';
 const nums=f.brief&&f.brief.brief?(f.brief.brief.match(/\d[\d,]*(\.\d+)?/g)||[]).length:0;
 const local=(fx.options||[]).filter(o=>o.local_evidence).length;
 const receipts=`<div class="card"><b>Receipts</b> <span class="legend">which check verified what</span><ul class="legend" style="margin:6px 0 0 18px;padding:0">
 ${f.brief&&f.brief.brief?`<li>${nums} numbers in the brief, each found in the official record by the checker${f.brief.attempts>1?` (${f.brief.attempts-1} draft(s) rejected and fixed)`:''}</li>`:''}
 <li>${(fx.options||[]).slice(0,8).length} fixes, each citing a CMF Clearinghouse record; dollar values from USDOT's official crash costs</li>
 ${local?`<li>${local} fix(es) with this city's own before/after result, shown only because it passed the placebo check</li>`:''}
 ${f.illustration?`<li>the drawing ${f.illustration.check_passed?'passed':'failed'} the SAM 3.1 check (the fix was actually drawn; real cars untouched)</li>`:''}
 <li>sources: ${esc(cr.source||'no crash data')} · ${esc(pl.source||'no plan data')}</li></ul></div>`;
 const memo=f.brief&&f.brief.brief?`<div class="card memo"><b>Safety Brief</b> <span class="legend">every number checked against the record</span>${DOMPurify.sanitize(marked.parse(f.brief.brief))}</div>`:'';
 out.innerHTML=`<div class="card"><h2 style="margin:0 0 4px">${esc(f.junction)}</h2><div class="kpi">
 <div><b>${cr.crashes??'n/a'}</b>crashes, 5 yr</div><div><b>${cr.injury_crashes??'n/a'}</b>injury crashes</div>
 <div><b>${(cr.pedestrian_injured||0)+(cr.pedestrian_killed||0)}</b>pedestrians hurt</div><div><b>${(cr.cyclist_injured||0)+(cr.cyclist_killed||0)}</b>cyclists hurt</div>${hm}</div>
 <p>${pl.designated?'On the city\'s priority network.':'Not on the city\'s priority lists.'} ${d.plan_gap?'<span class="gap">Plan gap: no recorded safety treatment in the period.</span>':(d.plan_gap===false?'<span class="nogap">Recorded treatment in the period.</span>':'')}</p>
 <p class="legend">${esc(cr.source||'')} · ${esc(pl.source||'')} · ${((Date.now()-t0)/1000).toFixed(0)} s</p></div>
 <div class="imgs">${imgs}</div>${ill}
 <div class="card"><b>Ranked fixes</b> <span class="legend">${esc(fx.method||'')}</span><table><tr><th>FHWA Proven Safety Countermeasure</th><th>CMF Clearinghouse</th><th>Targets</th><th>Expected crashes avoided</th><th>Harm avoided (USDOT $)</th></tr>${rows}</table>${(fx.in_place||[]).map(x=>`<p class="legend">Already in place (city records): ${esc(x.countermeasure)}${x.year?' since '+x.year:''}; not proposed again.</p>`).join('')}</div>${memo}${receipts}
 <div class="card"><b>Ask for the fix</b> <span class="legend">a letter to the people who can request it, checked against the record; you review and send it</span><div style="margin-top:8px"><button id="ltr">Draft a letter</button></div><div id="ltrout"></div></div>`;
 document.getElementById('ltr').onclick=async()=>{const o=document.getElementById('ltrout');o.innerHTML='<p class="legend">Finding the council district and community board, drafting…</p>';
  const lr=await (await fetch('/letter',{method:'POST',body:JSON.stringify(q)})).json();
  if(lr.error||!lr.letter){o.innerHTML=`<p>Could not draft the letter: ${esc(lr.error||(lr.checker_errors||[]).join('; '))}</p>`;return;}
  o.innerHTML=`<textarea id="ltrtxt" style="width:100%;min-height:340px;margin-top:8px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.5 system-ui">${esc(lr.letter)}</textarea>
  <p class="legend">${lr.rejected_drafts?lr.rejected_drafts+' draft(s) rejected by the checker and fixed · ':''}$${lr.usd} · <a href="#" id="cp">copy</a></p>`;
  document.getElementById('cp').onclick=e=>{e.preventDefault();navigator.clipboard.writeText(document.getElementById('ltrtxt').value);};};}
</script></body></html>"""


def evidence() -> dict:
    """What the causal gate found for every registered program (validation/results/bench/study_*.json), and how the
    gate fared on fake programs (T12)."""
    from . import opendata, treatments
    programs = []
    for res in treatments.results():
        for key, g in res.get("gates", {}).items():
            m = (res["runs"].get(g["primary"]) or {}).get(g["outcome"]) or {}
            pl = (res["runs"].get(g["placebos"][-1]) or {}).get(g["outcome"]) if g.get("placebos") else None
            programs.append({"city": res["city"], "city_name": (opendata.city(res["city"]) or {}).get("name", res["city"]),
                             "study": res["id"], "program": g["treatment"], "countermeasure": g.get("countermeasure"),
                             "passed": g["passed"], "reason": g["reason"], "outcome": g["outcome"],
                             "effect_pct": m.get("change_pct"), "sites": m.get("sites"),
                             "ci_pct": [round(100 * (v - 1), 1) for v in m["ci95"]] if m.get("ci95") else None,
                             "placebo_pct": pl and pl.get("change_pct"),
                             "comparison": g["primary"][len(key) + 1:].replace("_", " ")})
    t12 = RESULTS_DIR / "bench" / "experiment_T12.json"
    fake = json.loads(t12.read_text())["summary"] if t12.exists() else None
    return {"programs": programs, "fake_programs": fake}


def serve(port: int = 8770, open_weights: bool = True, illustrate: bool = False) -> int:
    from .meta_client import MetaClient
    if open_weights:
        from .openclient import OpenWeightsClient
        memo_client = OpenWeightsClient()
    else:
        memo_client = MetaClient(SETTINGS)
    image_client = MetaClient(SETTINGS) if illustrate else None
    roots = [SETTINGS.runs_dir.resolve(), SETTINGS.data_dir.resolve()]
    from . import citywide, opendata
    screens = citywide.screened()
    rows = screens[0][1].get("rows", []) if screens else []
    example = max(rows, key=lambda r: r.get("injury_crashes") or 0)["name"] if rows else "Main Street & 1st Avenue"
    s_, w_, n_, e_ = opendata.city(screens[0][0])["bbox"] if screens else opendata.load_cities()[0]["bbox"]
    page = (PAGE.replace("__CITIES__", ", ".join(c["name"] for c in opendata.load_cities()))
            .replace("__EXAMPLE__", example).replace("__VIEW__", f"[{(s_ + n_) / 2:.4f},{(w_ + e_) / 2:.4f}]"))
    screen_json = json.dumps({**screens[0][1], "city": screens[0][0],
                              "city_name": opendata.city(screens[0][0])["name"]}).encode() if screens else b"{}"
    evidence_json = json.dumps(evidence()).encode()
    done: dict[str, bytes] = {}  # briefs already built in this session, by request
    # public mode (the hosted demo): new model calls are capped per day and per address; nothing new is drawn
    public = os.environ.get("NML_PUBLIC") == "1"
    illustrate = illustrate and not public
    calls: dict[str, list[float]] = {}
    daily_cap, hourly_cap = int(os.environ.get("NML_PUBLIC_DAILY", "400")), int(os.environ.get("NML_PUBLIC_HOURLY", "30"))

    def allow(addr: str, forwarded: str | None) -> bool:
        who = (forwarded or addr).split(",")[0].strip()
        now = time.time()
        day = [t for t in calls.get("*", []) if now - t < 86400]
        mine = [t for t in calls.get(who, []) if now - t < 3600]
        if len(day) >= daily_cap or len(mine) >= hourly_cap:
            return False
        calls["*"], calls[who] = day + [now], mine + [now]
        return True

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/citywide":
                return self._send(200, screen_json, "application/json")
            if u.path == "/evidence":
                return self._send(200, evidence_json, "application/json")
            if u.path == "/media":
                p = Path(unquote(parse_qs(u.query).get("p", [""])[0])).resolve()
                if p.exists() and any(str(p).startswith(str(r)) for r in roots):
                    return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/jpeg")
                return self._send(404, b"not found", "text/plain")
            self._send(200, page.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
            q = json.loads(raw)
            if public and not allow(self.client_address[0], self.headers.get("X-Forwarded-For")):
                return self._send(200, json.dumps({"error": "the public demo's limit for new briefs is reached; "
                                                            "try again later or run it yourself (nml app)"}).encode(),
                                  "application/json")
            if urlparse(self.path).path == "/letter":  # a draft letter from the brief already built for q
                try:
                    k = json.dumps(q, sort_keys=True)
                    f = json.loads(done[k]) if k in done else brief.build(q.get("address") or q.get("name"), q.get("lat"),
                                                                           q.get("lon"), client=memo_client, memo=False)
                    d = f["dossier"]
                    res = letter.draft(memo_client, f, letter.offices(d["lat"], d["lon"]),
                                       tag=f"letter {f['junction'][:40]}")
                    return self._send(200, json.dumps(res, default=str).encode(), "application/json")
                except Exception as e:  # shown to the user, not hidden
                    return self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")
            key = json.dumps(q, sort_keys=True)
            if key in done:
                return self._send(200, done[key], "application/json")
            try:
                t = time.time()
                f = brief.build(q.get("address") or q.get("name"), q.get("lat"), q.get("lon"), client=memo_client, memo=True)
                if illustrate and not f.get("illustration") and f.get("aerial_photo") and f["fixes"]["options"]:
                    out = Path(f["aerial_photo"]).parent
                    f["illustration"] = brief.illustrate_fix(image_client, Path(f["aerial_photo"]), f["fixes"]["options"],
                                                             out, out.name)
                f["seconds"] = round(time.time() - t, 1)
                done[key] = json.dumps(f, default=str).encode()
                self._send(200, done[key], "application/json")
            except Exception as e:  # shown to the user, not hidden
                self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")

        def log_message(self, *a):
            pass

    print(f"Junction Safety Copilot: http://127.0.0.1:{port}  (memos on {'Muse Spark Open, Baseten' if open_weights else 'Meta API'}; Ctrl+C to stop)")
    ThreadingHTTPServer((os.environ.get("NML_HOST", "127.0.0.1"), port), H).serve_forever()
    return 0
