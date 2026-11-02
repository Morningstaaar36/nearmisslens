"""The conflict verifier on Meta open weights: Muse Spark Open served by Baseten (partner inference, paid from the
partner credit, not the Meta budget). Same instructions, clip and speed trace as the hosted verifier; Baseten has no
strict JSON output, so the verdict comes back through a submit_verdict tool. NML-Bench reports agreement with the
hosted Muse Spark verdicts on the same candidate conflicts."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx

from .cache import Cache, request_key
from .config import SETTINGS
from .verifier import INSTRUCTIONS, VERDICT_SCHEMA
from .config import MODELS

BASE_URL = "https://inference.baseten.co/v1"
MODEL = MODELS["open"]
PRICE = {"input": 1.25, "output": 4.25}  # $ per 1M tokens (Baseten, same as hosted Spark Standard)


def _key() -> str:
    k = os.environ.get("BASETEN_API_KEY")
    if not k:
        raise RuntimeError("BASETEN_API_KEY is not set (put it in .env)")
    return k


def verify_open(clip: Path | None, trace_png: str, metric_text: str, clip_key: str, effort: str = "low") -> dict:
    """Muse Spark Open's verdict on one event; cached by the same identity as the hosted verifier's request."""
    cache = Cache(SETTINGS.cache_dir, replay=SETTINGS.replay)
    request = {"model": MODEL, "clip": clip_key, "trace": request_key("t", {"p": trace_png}), "metric": metric_text,
               "instructions": INSTRUCTIONS, "effort": effort} | ({"arm": "no_video"} if clip is None else {})
    key = request_key("open_verify", request)
    hit = cache.get("open_verify", key)
    if hit is not None:
        return hit
    parts = [{"type": "text", "text": f"Flagged metric: {metric_text}"}]
    if clip is not None:  # the no-video arm sends only the speed trace and the metric
        video = base64.b64encode(Path(clip).read_bytes()).decode()
        parts.append({"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video}"}})
    parts.append({"type": "image_url", "image_url": {"url": trace_png}})
    tool = {"type": "function", "function": {"name": "submit_verdict", "description": "Submit the verdict.",
                                             "parameters": VERDICT_SCHEMA}}
    body = {"model": MODEL, "reasoning_effort": effort, "max_tokens": 4000, "tools": [tool],
            "tool_choice": "required",
            "messages": [{"role": "system", "content": INSTRUCTIONS + " Call submit_verdict once with your verdict."},
                         {"role": "user", "content": parts}]}
    with httpx.Client(timeout=300) as c:
        r = c.post(f"{BASE_URL}/chat/completions", json=body, headers={"Authorization": f"Api-Key {_key()}"})
    if r.status_code != 200:
        raise RuntimeError(f"Baseten HTTP {r.status_code}: {r.text[:300]}")
    js = r.json()
    msg = js["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    verdict = json.loads(calls[0]["function"]["arguments"]) if calls else None
    u = js.get("usage") or {}
    usd = (u.get("prompt_tokens", 0) * PRICE["input"] + u.get("completion_tokens", 0) * PRICE["output"]) / 1e6
    out = {"verdict": verdict, "usd": round(usd, 6), "usage": u, "text": msg.get("content")}
    if verdict is not None:
        cache.put("open_verify", key, out)
    return out
