"""The copilot's live endpoint on Modal: the same server as `nml app`, in public mode.

The page and the precomputed reports (docs/) ship in the image, so the city's priority corners open instantly. New
addresses run the deterministic engineer (no model; a daily request cap). Letters come from Muse Spark Open on
Baseten, and "Check a claim" runs the desk (Muse Spark), one case at a time, both under a daily dollar cap. Records are
read as of the date in validation/ASOF, the same date as the saved site, so the five-year baselines shipped in
validation/ are used and a first request never rebuilds a city's baseline. Both caps are global and live in a modal.Dict, and at most one container runs, so
they cannot be multiplied; no visitor IP or request log is kept. When a cap is reached the page still shows the full
report and says the letter is paused for the day.

    modal secret create nearmisslens-keys MODEL_API_KEY=... BASETEN_API_KEY=...   # once; keys stay in Modal's store
    modal serve nearmisslens/modal_web.py                          # a temporary URL while it runs
    modal deploy nearmisslens/modal_web.py                         # the permanent URL (then: nml pages --live URL)"""
import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
PORT = 8000
# the records' date: read from the repo when deploying; inside the container this file is not at ROOT, and the image
# already carries the date in its environment
_ASOF_FILE = ROOT / "validation" / "ASOF"
ASOF = _ASOF_FILE.read_text().strip() if _ASOF_FILE.exists() else os.environ.get("NML_ASOF", "")
app = modal.App("nearmisslens-copilot")
state = modal.Volume.from_name("nearmisslens-state", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("httpx==0.28.1", "numpy==1.26.4", "pandas==2.2.3", "scipy==1.14.1",
                      "opencv-python-headless==4.10.0.84", "meta-sam-parser==0.1.0", "modal")
         .env({"NML_DATA": "/state/data", "NML_CACHE": "/state/cache", "NML_RUNS": "/state/runs",
               "NML_HOST": "0.0.0.0", "NML_PUBLIC": "1", "PYTHONPATH": "/app",
               "NML_BUDGET_DICT": "nearmisslens-budget", "NML_DAILY_USD": "3.00", "NML_DAILY_REQUESTS": "300",
               "NML_CHECK_BUDGET_USD": "0.50", "NML_ALLOWED_ORIGINS": "https://morningstaaar36.github.io", "NML_ASOF": ASOF})
         .add_local_dir(ROOT / "validation", "/app/validation")
         .add_local_dir(ROOT / "docs", "/app/docs", ignore=["video/**", "img/**", "*.md"])
         .add_local_dir(ROOT / "nearmisslens", "/app/nearmisslens", ignore=["**/__pycache__/**"]))
keys = modal.Secret.from_name("nearmisslens-keys")


@app.function(image=image, volumes={"/state": state}, secrets=[keys], cpu=1.0, memory=2048, timeout=3600,
              scaledown_window=300, max_containers=1)
@modal.concurrent(max_inputs=8)
@modal.web_server(port=PORT, startup_timeout=120)
def web():
    import subprocess
    subprocess.Popen(["python", "-c", f"from nearmisslens.app import serve; serve(port={PORT})"], cwd="/app")
