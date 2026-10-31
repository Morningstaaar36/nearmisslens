"""The Junction Safety Copilot as a hosted web app on Modal.

A CPU container runs the same server as `nml app`. Memos and letters come from Muse Spark Open on Baseten (partner
inference). The open-data responses, briefs and drawings persist in a Modal volume, so a brief built once is instant
afterwards. Public mode caps new model calls per day and per address and never draws new illustrations.

    modal volume create nearmisslens-state          # once, then upload the caches (nml deploy-state)
    modal serve nearmisslens/modal_web.py           # a temporary URL while it runs
    modal deploy nearmisslens/modal_web.py          # the permanent URL"""
import os
import subprocess
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
PORT = 8000
app = modal.App("nearmisslens-copilot")
state = modal.Volume.from_name("nearmisslens-state", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("httpx==0.28.1", "numpy==1.26.4", "pandas==2.2.3", "scipy==1.14.1",
                      "opencv-python-headless==4.10.0.84", "meta-sam-parser==0.1.0")
         .env({"NML_DATA": "/state/data", "NML_CACHE": "/state/cache", "NML_RUNS": "/state/runs",
               "NML_HOST": "0.0.0.0", "NML_PUBLIC": "1", "PYTHONPATH": "/app"})
         .add_local_dir(ROOT / "validation", "/app/validation")
         .add_local_dir(ROOT / "nearmisslens", "/app/nearmisslens", ignore=["**/__pycache__/**"]))
keys = modal.Secret.from_dict({k: os.environ.get(k, "") for k in ("BASETEN_API_KEY", "MAPILLARY_CLIENT_TOKEN")})


@app.function(image=image, volumes={"/state": state}, secrets=[keys], cpu=1.0, memory=2048, timeout=3600,
              scaledown_window=600)
@modal.concurrent(max_inputs=20)
@modal.web_server(port=PORT, startup_timeout=120)
def web():
    subprocess.Popen(["python", "-c", f"from nearmisslens.app import serve; serve(port={PORT})"], cwd="/app")
