"""Junction Safety Copilot: a local web app for a city engineer. Search an address or click a NYC Vision Zero priority
intersection; the agents assemble the official record, rank cited fixes by expected crashes avoided, show the city's
aerial photo and a street-level photo, and write a checked Safety Brief. Runs on 127.0.0.1; keys stay on the machine."""
from __future__ import annotations

import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import brief
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
.verify{color:var(--mut);font-style:italic}.imgs{display:grid;grid-template-columns:1fr 1fr;gap:8px}.imgs img{width:100%;border-radius:8px}
.memo{line-height:1.55}.legend{font-size:12px;color:var(--mut)}
</style></head><body>
<header><h1>Junction Safety Copilot</h1><span class="sub">Official record → cited fixes → checked brief. NYC, DC, Chicago, LA.</span>
<input id="q" placeholder="e.g. Delancey Street & Essex Street, Manhattan, NY"><button id="go">Brief</button></header>
<main><div id="map"></div><div id="side"><div class="card"><b>How to use</b><p class="sub">Click a dot (NYC Vision Zero priority intersections; red = injury crashes and no recorded safety treatment in 5 years) or search an intersection. The brief takes 20–90 s the first time.</p><div id="top"></div></div><div id="out"></div></div></main>
<script>
const map=L.map('map').setView([40.73,-73.94],11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
fetch('/citywide').then(r=>r.json()).then(d=>{
 if(!d.rows)return;const s=d.summary;
 document.getElementById('top').innerHTML=`<p><b>${s.plan_gap} of ${s.intersections}</b> NYC priority intersections had ≥10 injury crashes in 5 years and no recorded safety treatment nearby in that period (${s.injury_crashes_total} injury crashes, ${s.killed_total} deaths in total).</p>`;
 for(const r of d.rows){const c=L.circleMarker([r.lat,r.lon],{radius:4+Math.sqrt(r.injury_crashes||0)/2,color:r.plan_gap?'#ef5350':'#3ecf8e',weight:1,fillOpacity:.6}).addTo(map);
  c.bindTooltip(`${esc(r.name)}: ${r.injury_crashes} injury crashes`);c.on('click',()=>run({lat:r.lat,lon:r.lon,name:r.name}));}});
document.getElementById('go').onclick=()=>run({address:document.getElementById('q').value});
const qs=new URLSearchParams(location.search);
if(qs.get('q')){document.getElementById('q').value=qs.get('q');run({address:qs.get('q')});}
async function run(q){
 const out=document.getElementById('out');out.innerHTML='<div class="card">Assembling the official record, ranking fixes, writing the brief…</div>';
 const t0=Date.now();const r=await fetch('/brief',{method:'POST',body:JSON.stringify(q)});const f=await r.json();
 if(f.error){out.innerHTML=`<div class="card">Could not build the brief: ${esc(f.error)}</div>`;return;}
 const d=f.dossier,cr=d.crashes||{},pl=d.plans||{},fx=f.fixes||{};map.setView([d.lat,d.lon],17);
 const rows=(fx.options||[]).slice(0,8).map(o=>`<tr><td><b>${esc(o.countermeasure)}</b>${o.verify_on_site?`<div class="verify">verify on site: ${esc(o.verify_on_site)}</div>`:''}</td><td>CMF ${esc(o.cmf_id)}<br>${o.cmf} · ${esc(o.stars)}</td><td>${esc(o.targets)}<br>${o.target_crashes_per_year}/yr</td><td><b>${o.expected_crashes_avoided_per_year}</b>/yr</td></tr>`).join('');
 const imgs=[f.aerial_photo?`<figure><img src="/media?p=${encodeURIComponent(f.aerial_photo)}"><figcaption class="legend">City aerial photo</figcaption></figure>`:'',
  f.street_photo?`<figure><img src="/media?p=${encodeURIComponent(f.street_photo.image)}"><figcaption class="legend">Street level, ${esc(f.street_photo.captured)} (<a href="${f.street_photo.url}" target="_blank">Mapillary</a>, CC BY-SA)</figcaption></figure>`:''].join('');
 const ill=f.illustration?`<div class="card"><b>Proposed fix, drawn by Muse Image on the city photo</b> (${esc(f.illustration.countermeasure)}; SAM 3.1 check ${f.illustration.check_passed?'passed':'failed'})<img style="width:100%;border-radius:8px;margin-top:8px" src="/media?p=${encodeURIComponent(f.illustration.image)}"></div>`:'';
 const memo=f.brief&&f.brief.brief?`<div class="card memo"><b>Safety Brief</b> <span class="legend">every number checked against the record</span>${DOMPurify.sanitize(marked.parse(f.brief.brief))}</div>`:'';
 out.innerHTML=`<div class="card"><h2 style="margin:0 0 4px">${esc(f.junction)}</h2><div class="kpi">
 <div><b>${cr.crashes??'n/a'}</b>crashes, 5 yr</div><div><b>${cr.injury_crashes??'n/a'}</b>injury crashes</div>
 <div><b>${(cr.pedestrian_injured||0)+(cr.pedestrian_killed||0)}</b>pedestrians hurt</div><div><b>${(cr.cyclist_injured||0)+(cr.cyclist_killed||0)}</b>cyclists hurt</div></div>
 <p>${pl.designated?'On the city\'s priority network.':'Not on the city\'s priority lists.'} ${d.plan_gap?'<span class="gap">Plan gap: no recorded safety treatment in the period.</span>':(d.plan_gap===false?'<span class="nogap">Recorded treatment in the period.</span>':'')}</p>
 <p class="legend">${esc(cr.source||'')} · ${esc(pl.source||'')} · ${((Date.now()-t0)/1000).toFixed(0)} s</p></div>
 <div class="imgs">${imgs}</div>${ill}
 <div class="card"><b>Ranked fixes</b> <span class="legend">${esc(fx.method||'')}</span><table><tr><th>FHWA Proven Safety Countermeasure</th><th>CMF Clearinghouse</th><th>Targets</th><th>Expected crashes avoided</th></tr>${rows}</table></div>${memo}`;}
</script></body></html>"""


def serve(port: int = 8770, open_weights: bool = True, illustrate: bool = False) -> int:
    from .meta_client import MetaClient
    if open_weights:
        from .openclient import OpenWeightsClient
        memo_client = OpenWeightsClient()
    else:
        memo_client = MetaClient(SETTINGS)
    image_client = MetaClient(SETTINGS) if illustrate else None
    roots = [SETTINGS.runs_dir.resolve(), SETTINGS.data_dir.resolve()]
    done: dict[str, bytes] = {}  # briefs already built in this session, by request

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
                p = RESULTS_DIR / "bench" / "citywide_nyc.json"
                return self._send(200, p.read_bytes() if p.exists() else b"{}", "application/json")
            if u.path == "/media":
                p = Path(unquote(parse_qs(u.query).get("p", [""])[0])).resolve()
                if p.exists() and any(str(p).startswith(str(r)) for r in roots):
                    return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/jpeg")
                return self._send(404, b"not found", "text/plain")
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
            q = json.loads(raw)
            key = json.dumps(q, sort_keys=True)
            if key in done:
                return self._send(200, done[key], "application/json")
            try:
                t = time.time()
                f = brief.build(q.get("address"), q.get("lat"), q.get("lon"), client=memo_client, memo=True)
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
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    return 0
