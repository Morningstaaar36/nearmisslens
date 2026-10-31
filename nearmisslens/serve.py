"""Live intake page for the demo: record a complaint in the browser, Muse Voice Transcribe turns it into text, the
intake agent checks it against the junction's audit, and the page shows the verdict, the answer, the evidence frames
and the agent's timeline. Local only (127.0.0.1); the API key never reaches the browser."""
from __future__ import annotations

import json
import mimetypes
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ask
from .config import SETTINGS, resolve
from .countermeasures import load_cmf
from .meta_client import MetaClient
from .runner import as_wav
from .voice import transcribe

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>NearMissLens intake</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1115;--fg:#e8eaed;--mut:#9aa0a6;--acc:#f5a524;--ok:#3ecf8e;--no:#ef5350;--card:#181b22}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 20px}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
button{background:var(--acc);color:#111;border:0;border-radius:999px;padding:12px 22px;font-weight:700;font-size:16px;cursor:pointer}
button.rec{background:var(--no);color:#fff}
textarea{width:100%;min-height:64px;background:var(--card);color:var(--fg);border:1px solid #2a2f3a;border-radius:10px;padding:10px;font:inherit}
.card{background:var(--card);border-radius:14px;padding:16px;margin-top:16px}
.verdict{font-size:20px;font-weight:800}.supported{color:var(--ok)}.not_observed{color:var(--no)}.unclear{color:var(--mut)}
.tl{font:13px/1.45 ui-monospace,monospace;color:var(--mut);white-space:pre-wrap}
.imgs{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:10px}
.imgs img{width:100%;border-radius:10px}
</style></head><body><main>
<h1>Tell us about a dangerous junction</h1>
<p class="sub">Speak or type a complaint. The intake agent checks it against the measured near-misses for <b>__AUDIT__</b>.</p>
<div class="row"><button id="rec">● Record</button><span id="st" class="sub"></span></div>
<p class="sub">or type it:</p><textarea id="txt" placeholder="Scooters turning right from the north side keep nearly hitting cars."></textarea>
<div class="row" style="margin-top:8px"><button id="send">Check complaint</button></div>
<div id="out"></div>
<script>
let rec=null,chunks=[];const st=document.getElementById('st');
document.getElementById('rec').onclick=async e=>{
 if(rec&&rec.state==='recording'){rec.stop();e.target.textContent='● Record';e.target.classList.remove('rec');return;}
 const s=await navigator.mediaDevices.getUserMedia({audio:true});rec=new MediaRecorder(s);chunks=[];
 rec.ondataavailable=d=>chunks.push(d.data);rec.onstop=()=>{s.getTracks().forEach(t=>t.stop());send(new Blob(chunks,{type:rec.mimeType}));};
 rec.start();e.target.textContent='■ Stop';e.target.classList.add('rec');st.textContent='listening…';};
document.getElementById('send').onclick=()=>send(null);
async function send(blob){
 st.textContent='working…';const t0=Date.now();
 const r=await fetch(blob?'/ask_audio':'/ask_text',{method:'POST',body:blob||document.getElementById('txt').value});
 const j=await r.json();st.textContent='done in '+((Date.now()-t0)/1000).toFixed(1)+' s';
 if(j.error){document.getElementById('out').innerHTML=`<div class="card">Could not check the complaint: ${j.error}</div>`;return;}
 const res=j.result||{};const imgs=(j.images||[]).map(p=>`<img src="/media?p=${encodeURIComponent(p)}">`).join('');
 const tl=(j.timeline||[]).map(e=>e.kind==='thought'?`· ${e.text}`:`→ ${e.tool}(${JSON.stringify(e.arguments)}) ${e.seconds}s`).join('\\n');
 document.getElementById('out').innerHTML=`<div class="card"><div class="sub">heard: “${j.transcript||''}”</div>
 <div class="verdict ${res.verdict}">${(res.verdict||'no answer').replace('_',' ')}${res.rank?' · hotspot '+res.rank:''}</div>
 <p>${res.answer||''}</p><div class="sub">countermeasures: ${(res.cmf_ids||[]).map(c=>'CMF '+c).join(', ')||'none'} · ${j.model} · $${j.usd} · ${j.turns} turns${j.refusals?' · '+j.refusals+' answers rejected by the checker':''}</div>
 <div class="imgs">${imgs}</div></div><div class="card"><div class="sub">agent timeline</div><div class="tl">${tl}</div></div>`;}
</script></main></body></html>"""


def serve(audit_name: str, port: int = 8765, model: str = "muse-wonder-1.0") -> int:
    client = MetaClient(SETTINGS)
    facts, memo_md = ask.load(audit_name, SETTINGS.runs_dir)
    cmf = load_cmf()
    frames = SETTINGS.data_dir / "work" / "ask_frames"
    allowed_roots = [SETTINGS.data_dir.resolve(), SETTINGS.runs_dir.resolve()]

    def answer(text: str, transcript: str | None = None) -> dict:
        out = ask.answer(client, text, facts, memo_md, cmf, frames, f"live {audit_name} {int(time.time())}",
                         model=model, budget_usd=0.12 if "wonder" in model else 0.02)
        images = [p for e in out["timeline"] if e["kind"] == "tool" and e["tool"] == "evidence"
                  for p in (e["result"] or {}).get("_images", [])]
        steps = [s for s in out["timeline"]]
        return {**out, "transcript": transcript or text, "images": images, "timeline": steps}

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/media?p="):
                from urllib.parse import unquote
                p = resolve(unquote(self.path.split("=", 1)[1])).resolve()
                if p.exists() and any(str(p).startswith(str(r)) for r in allowed_roots):
                    return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/jpeg")
                return self._send(404, b"not found", "text/plain")
            self._send(200, PAGE.replace("__AUDIT__", audit_name).encode(), "text/html; charset=utf-8")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                if self.path == "/ask_text":
                    res = answer(body.decode())
                else:
                    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                        f.write(body)
                    wav = as_wav(Path(f.name), SETTINGS.data_dir / "work" / "voice")
                    try:
                        text = transcribe(client, wav, f"live {audit_name}")["transcript"]
                    finally:  # the recording is not kept, only the transcript
                        Path(f.name).unlink(missing_ok=True)
                        Path(wav).unlink(missing_ok=True)
                    res = answer(text, text)
                self._send(200, json.dumps(res, default=str).encode(), "application/json")
            except Exception as e:  # shown on the page, not hidden
                self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")

        def log_message(self, *a):
            pass

    print(f"NearMissLens intake for {audit_name}: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    return 0
