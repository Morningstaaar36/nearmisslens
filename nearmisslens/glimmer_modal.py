"""Muse Glimmer (Meta open weights, Apache-2.0) served on a Modal GPU for the open-weights agent tier.

Meta's official 4-bit GGUF (17 GB) runs in llama.cpp's server on one L4 (24 GB) and exposes an OpenAI-compatible
endpoint behind an API key; openclient.OpenWeightsClient talks to it with base_url and model changed.

    modal run nearmisslens/glimmer_modal.py::download   # once: weights into a Modal volume
    modal deploy nearmisslens/glimmer_modal.py          # endpoint; scales to zero after 5 minutes idle"""
import os
import subprocess

import modal

LLAMA = "b11946"  # first builds with the muse-glimmer architecture are >= b10353
REPO, GGUF = "meta-models/Muse-Glimmer-30B-GGUF", "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
MMPROJ = "mmproj-Muse-Glimmer-30B-Q4_K_M.gguf"  # vision projector, needed for image inputs
BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA}"

app = modal.App("nearmisslens-glimmer")
weights = modal.Volume.from_name("glimmer-weights", create_if_missing=True)
image = (modal.Image.from_registry("nvidia/cuda:12.8.1-runtime-ubuntu24.04", add_python="3.12")
         .apt_install("curl", "ca-certificates", "libgomp1")
         .run_commands(f"curl -sL -o /tmp/l.tgz {BASE}/llama-{LLAMA}-bin-ubuntu-cuda-12.8-x64.tar.gz",
                       "mkdir -p /opt/llama && tar -xzf /tmp/l.tgz -C /opt/llama && rm /tmp/l.tgz",
                       "find /opt/llama -name llama-server -exec ln -sf {} /usr/local/bin/llama-server \\;",
                       "find /opt/llama -name '*.so*' -exec dirname {} \\; | sort -u > /etc/ld.so.conf.d/llama.conf && ldconfig")
         .pip_install("huggingface_hub==0.36.0"))


@app.function(image=image, volumes={"/models": weights}, timeout=3600)
def download():
    from huggingface_hub import hf_hub_download
    paths = [hf_hub_download(REPO, f, local_dir="/models") for f in (GGUF, MMPROJ)]
    weights.commit()
    return paths


@app.function(image=image, gpu="L4", volumes={"/models": weights}, timeout=3600, scaledown_window=300,
              secrets=[modal.Secret.from_dict({"GLIMMER_API_KEY": os.environ.get("GLIMMER_API_KEY", "")})])
@modal.concurrent(max_inputs=4)
@modal.web_server(port=8080, startup_timeout=900)
def serve():
    subprocess.Popen(["llama-server", "-m", f"/models/{GGUF}", "--mmproj", f"/models/{MMPROJ}", "-ngl", "99",
                      "-c", "32768", "-np", "1",
                      "--host", "0.0.0.0", "--port", "8080", "--api-key", os.environ["GLIMMER_API_KEY"], "--jinja",
                      "-a", "muse-glimmer"])
