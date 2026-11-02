"""Run the agents on Meta open weights: a client with the MetaClient interface (cached, create_response) that serves
Responses-API agent turns from Muse Spark Open on Baseten's OpenAI-compatible chat endpoint. Requests and answers are
translated both ways, so ask.answer, context.memo and office.run work unchanged. Spend is paid from the Baseten
partner credit and logged in runs/ledger_baseten.jsonl, apart from the Meta budget."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from .cache import Cache, request_key
from .config import MODELS, SETTINGS
from .cost import TOKEN_USD_PER_M
from .meta_client import IncompleteResponse, output_text

BASE_URL = "https://inference.baseten.co/v1"
MODEL = MODELS["open"]
PRICE = dict(zip(("input", "output"), TOKEN_USD_PER_M[MODELS["open_label"]][:2]))  # one price table: cost.py
FORCE_FINISH_AFTER = 6


def to_chat(payload: dict, model: str = MODEL, force_after: int = FORCE_FINISH_AFTER) -> dict:
    """A Responses-API agent request as a chat-completions request."""
    msgs = [{"role": "system", "content": payload.get("instructions", "")}]
    pending_images: list[dict] = []
    for item in payload.get("input", []):
        kind = item.get("type")
        if kind == "message" and item.get("role") == "user":
            parts = []
            for c in item["content"]:
                if c["type"] == "input_text":
                    parts.append({"type": "text", "text": c["text"]})
                elif c["type"] == "input_image":
                    parts.append({"type": "image_url", "image_url": {"url": c["image_url"]}})
            msgs.append({"role": "user", "content": parts})
        elif kind == "message" and item.get("role") == "assistant":
            text = "".join(c.get("text", "") for c in item.get("content", []))
            msgs.append({"role": "assistant", "content": text})
        elif kind == "function_call":
            call = {"id": item["call_id"], "type": "function",
                    "function": {"name": item["name"], "arguments": item.get("arguments") or "{}"}}
            if msgs[-1]["role"] == "assistant" and msgs[-1].get("tool_calls") is not None:
                msgs[-1]["tool_calls"].append(call)
            else:
                msgs.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind == "function_call_output":
            out = item["output"]
            if isinstance(out, list):  # tool results with images: text in the tool message, images in a user turn
                text = " ".join(p["text"] for p in out if p["type"] == "input_text")
                pending_images += [{"type": "image_url", "image_url": {"url": p["image_url"]}}
                                   for p in out if p["type"] == "input_image"]
                out = text
            msgs.append({"role": "tool", "tool_call_id": item["call_id"], "content": out})
    if pending_images:
        msgs.append({"role": "user", "content": [{"type": "text", "text": "Images returned by the tools above:"}]
                     + pending_images})
    tools = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t["parameters"]}} for t in payload.get("tools", [])]
    body = {"model": model, "messages": msgs, "max_tokens": payload.get("max_output_tokens", 4000),
            "reasoning_effort": (payload.get("reasoning") or {}).get("effort", "low")}
    if tools:
        calls = sum(1 for i in payload.get("input", []) if i.get("type") == "function_call")
        names = {t["function"]["name"] for t in tools}
        # Spark Open, required to call a tool every turn, keeps reading; after force_after calls it must finish, and
        # an agent with a commit step (the gated analyst) is made to commit before it can finish
        committed = any(i.get("type") == "function_call" and i.get("name") == "commit_design"
                        for i in payload.get("input", []))
        step = "commit_design" if "commit_design" in names and not committed else "finish"
        if payload.get("x_next_tool") in names:  # the governor's choice: the next missing required tool (adapter A1)
            step = payload["x_next_tool"]
        choice = ({"type": "function", "function": {"name": step}} if calls >= force_after and step in names
                  else "required")
        body |= {"tools": tools, "tool_choice": choice}
    return body


def from_chat(js: dict) -> dict:
    """A chat-completions answer as a Responses-API response (function calls, text, reasoning summary, usage)."""
    msg = js["choices"][0]["message"]
    output = []
    if msg.get("reasoning_content"):
        output.append({"type": "reasoning", "summary": [{"type": "summary_text", "text": msg["reasoning_content"][:1500]}]})
    for tc in msg.get("tool_calls") or []:
        output.append({"type": "function_call", "call_id": tc["id"], "name": tc["function"]["name"],
                       "arguments": tc["function"].get("arguments") or "{}"})
    if msg.get("content"):
        output.append({"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": msg["content"]}]})
    u = js.get("usage") or {}
    cut = js["choices"][0].get("finish_reason") == "length"  # stopped by the token limit: not a complete answer
    return {"status": "incomplete" if cut else "completed", **({"incomplete_details": {"reason": "max_output_tokens"}}
                                                                 if cut else {}), "output": output,
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0),
                      "input_tokens_details": {"cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}}}


class OpenWeightsClient:
    """Drop-in for MetaClient in the agent loop; every answer comes from a Meta open-weights model: Muse Spark Open
    on Baseten (default) or Muse Glimmer on Modal (glimmer())."""

    def __init__(self, ledger: Path | None = None, base_url: str = BASE_URL, model: str = MODEL,
                 key_env: str = "BASETEN_API_KEY", auth: str = "Api-Key", price: dict | None = PRICE,
                 force_finish_after: int = FORCE_FINISH_AFTER):
        self.cache = Cache(SETTINGS.cache_dir, replay=SETTINGS.replay)
        self.ledger = ledger or SETTINGS.runs_dir / "ledger_baseten.jsonl"
        self.base_url, self.model, self.key_env, self.auth, self.price = base_url, model, key_env, auth, price
        self.spent = 0.0
        self.force_finish_after = force_finish_after

    @classmethod
    def glimmer(cls) -> "OpenWeightsClient":
        """Muse Glimmer on the Modal endpoint (GLIMMER_URL); billed by GPU time, so token cost is logged as 0."""
        url = os.environ.get("GLIMMER_URL", "").rstrip("/")
        if not url:
            raise RuntimeError("GLIMMER_URL is not set: deploy nearmisslens/glimmer_modal.py and put its URL in .env")
        return cls(ledger=SETTINGS.runs_dir / "ledger_modal.jsonl", base_url=f"{url}/v1", model=MODELS["glimmer"],
                   key_env="GLIMMER_API_KEY", auth="Bearer", price=None)

    def create_response(self, payload: dict) -> dict:
        key = os.environ.get(self.key_env)
        if not key:
            raise RuntimeError(f"{self.key_env} is not set (put it in .env)")
        body = to_chat(payload, self.model, self.force_finish_after)
        for attempt in range(8):
            # Modal answers long requests with a 303 to a result URL; a cold start returns 503 while the model loads
            with httpx.Client(timeout=900, follow_redirects=True) as c:
                r = c.post(f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"{self.auth} {key}"})
            if r.status_code == 200:
                return from_chat(r.json())
            if r.status_code not in (303, 408, 429, 500, 502, 503, 504):
                break
            time.sleep(min(60, 5 * 2 ** attempt))
        raise IncompleteResponse(f"{self.base_url} HTTP {r.status_code}: {r.text[:300]}")

    def cached(self, namespace: str, request: dict, run, cost_fn, estimate_usd: float, what: str,
               require_text: bool = False, complete=None) -> dict:
        served = "baseten" if self.base_url == BASE_URL else self.base_url  # keeps earlier Baseten cache keys valid
        req = {**request, "model": self.model, "served_by": served, "force_finish_after": self.force_finish_after}
        k = request_key(f"open_{namespace}", req)
        hit = self.cache.get(f"open_{namespace}", k)
        if hit is not None:
            return hit
        result = run()
        u = result.get("usage") or {}
        usd = self.usd(u)
        self.spent += usd
        with open(self.ledger, "a") as f:
            f.write(json.dumps({"t": time.time(), "model": self.model, "usd": round(usd, 6), "what": what, **u}) + "\n")
        done = complete(result) if complete else result.get("status") == "completed"
        if not done or (require_text and not output_text(result).strip()):  # never cache a cut or empty answer
            raise IncompleteResponse(f"{what}: status={result.get('status')!r}, details={result.get('incomplete_details')}")
        self.cache.put(f"open_{namespace}", k, result)
        return result

    def usd(self, usage: dict) -> float:
        """What a call costs at this server's token prices (0 for GPU-time billing, which is not measured here)."""
        if not self.price:
            return 0.0
        return (usage.get("input_tokens", 0) * self.price["input"]
                + usage.get("output_tokens", 0) * self.price["output"]) / 1e6

    def check_budget(self, estimate_usd: float, what: str) -> None:
        return None
