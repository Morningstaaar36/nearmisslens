"""Voice studio: record the demo's narration line by line in the browser.

The page shows each scene's line (from demo_copilot.script(), so the numbers are the current results), records it
with the microphone, plays it back and lets you redo it. Takes are saved as runs/demo/voice/<NN>_<scene>.wav with the
text they were recorded for; `nml demo --copilot` uses a take whenever its text still matches the script, and the
local synthetic voice otherwise. Local only (127.0.0.1).

    uv run nml voice      # then open http://127.0.0.1:8792"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import SETTINGS

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>NearMissLens voice studio</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1115;--fg:#e8eaed;--mut:#9aa0a6;--acc:#f5a524;--ok:#3ecf8e;--no:#ef5350;--card:#181b22}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0}.sub{color:var(--mut)}
.card{background:var(--card);border-radius:14px;padding:16px;margin-top:14px}
.line{font-size:21px;line-height:1.6;margin:8px 0 12px}
button{background:var(--acc);color:#111;border:0;border-radius:999px;padding:10px 18px;font-weight:700;cursor:pointer;margin-right:6px}
button.rec{background:var(--no);color:#fff}.done{color:var(--ok)}.stale{color:var(--acc)}
</style></head><body><main>
<h1>Voice studio</h1><p class="sub">Read each line at a calm pace. Press Record, read, press Stop. Play it back; record again if you want.
Lines marked "recorded" are used in the video; if a line's text changes later it shows "needs a new take".</p>
<div id="list"></div>
<script>
let rec=null,chunks=[];
async function load(){const ls=await (await fetch('/lines')).json();
 document.getElementById('list').innerHTML=ls.map(l=>`<div class="card" id="c${l.k}"><div class="sub">${l.k+1} of ${ls.length} · ${l.name} · about ${l.seconds} s
 · <span class="${l.state==='recorded'?'done':(l.state==='stale'?'stale':'')}">${l.state==='recorded'?'recorded':(l.state==='stale'?'needs a new take':'not recorded')}</span></div>
 <div class="line">${l.text}</div><button onclick="toggle(${l.k},this)">● Record</button>${l.state!=='none'?`<button onclick="new Audio('/take?k=${l.k}&t='+Date.now()).play()">▶ Play</button>`:''}</div>`).join('');}
async function toggle(k,b){
 if(rec&&rec.state==='recording'){rec.stop();return;}
 const s=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
 rec=new MediaRecorder(s);chunks=[];rec.ondataavailable=d=>chunks.push(d.data);
 rec.onstop=async()=>{s.getTracks().forEach(t=>t.stop());b.textContent='saving…';
  await fetch('/take?k='+k,{method:'POST',body:new Blob(chunks,{type:rec.mimeType})});load();};
 rec.start();b.textContent='■ Stop';b.classList.add('rec');}
load();
</script></main></body></html>"""


def voice_dir() -> Path:
    d = SETTINGS.runs_dir / "demo" / "voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def take(k: int, name: str, text: str) -> Path | None:
    """The recorded take for a scene, if one exists for exactly this text."""
    wav, meta = voice_dir() / f"{k:02d}_{name}.wav", voice_dir() / f"{k:02d}_{name}.json"
    if wav.exists() and meta.exists() and json.loads(meta.read_text()).get("text") == _digest(text):
        return wav
    return None


def serve(port: int = 8792) -> int:
    from . import demo_copilot

    def lines():
        out = []
        for k, s in enumerate(demo_copilot.script()):
            wav = voice_dir() / f"{k:02d}_{s.name}.wav"
            state = "recorded" if take(k, s.name, s.narration) else ("stale" if wav.exists() else "none")
            out.append({"k": k, "name": s.name, "text": s.narration, "state": state,
                        "seconds": round(len(s.narration.split()) / 2.5)})
        return out

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/lines":
                return self._send(200, json.dumps(lines()).encode(), "application/json")
            if u.path == "/take":
                k = int(parse_qs(u.query)["k"][0])
                hit = sorted(voice_dir().glob(f"{k:02d}_*.wav"))
                return self._send(200, hit[0].read_bytes(), "audio/wav") if hit else self._send(404, b"", "text/plain")
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            k = int(parse_qs(urlparse(self.path).query)["k"][0])
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            line = lines()[k]
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(body)
            wav = voice_dir() / f"{k:02d}_{line['name']}.wav"
            # 24 kHz mono, trimmed of silence at both ends, loudness normalised
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f.name, "-ac", "1", "-ar", "24000", "-af",
                            "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                            "silenceremove=start_periods=1:start_threshold=-45dB,areverse,loudnorm=I=-16",
                            str(wav)], check=True)
            (voice_dir() / f"{k:02d}_{line['name']}.json").write_text(json.dumps({"text": _digest(line["text"])}))
            Path(f.name).unlink(missing_ok=True)
            self._send(200, b"{}", "application/json")

        def log_message(self, *a):
            pass

    print(f"Voice studio: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    return 0
