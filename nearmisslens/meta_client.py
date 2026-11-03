from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

import httpx

from .cache import Cache, file_sha256, request_key
from .config import SETTINGS, Settings
from .cost import CostMeter

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class IncompleteResponse(RuntimeError):
    def __init__(self, message: str, usd: float = 0.0):
        super().__init__(message)
        self.usd = usd  # a cut-off response is still paid for


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status


def iter_sse(lines: Iterator[str]) -> Iterator[dict]:
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            payload = "\n".join(data)
            data = []
            if payload and payload != "[DONE]":
                yield json.loads(payload)
    if data and data[0] != "[DONE]":
        yield json.loads("\n".join(data))


def collect_stream(events: Iterator[dict]) -> dict:
    text: list[str] = []
    final: dict = {}
    for ev in events:
        kind = ev.get("type", "")
        if kind == "response.output_text.delta":
            text.append(ev.get("delta", ""))
        elif kind in ("response.completed", "response.incomplete"):
            final = ev.get("response", {})
        elif kind in ("error", "response.failed"):
            raise ApiError(500, json.dumps(ev))
    if not final:
        final = {"status": "stream_ended", "incomplete_details": {"reason": "stream closed before response.completed"}}
    final.setdefault("output_text", "".join(text))
    return final


def output_text(response: dict) -> str:
    if response.get("output_text"):
        return response["output_text"]
    parts = []
    for item in response.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
    return "".join(parts)


class MetaClient:
    def __init__(self, settings: Settings = SETTINGS):
        self.s = settings
        self.cache = Cache(settings.cache_dir, replay=settings.replay)
        self.meter = CostMeter(settings.ledger, settings.budget_usd)
        self._http: httpx.Client | None = None

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                base_url=self.s.api_base,
                headers={"Authorization": f"Bearer {self.s.api_key()}"},
                timeout=httpx.Timeout(600.0, connect=30.0),
            )
        return self._http

    def _retrying(self, fn, attempts: int = 6):
        for i in range(attempts):
            try:
                return fn()
            except ApiError as e:
                if e.status not in RETRY_STATUS or i == attempts - 1:
                    raise
            except (httpx.TransportError, httpx.TimeoutException):
                if i == attempts - 1:
                    raise
            time.sleep(min(60, 2 ** i))

    def stream_response(self, payload: dict) -> dict:
        def call():
            with self.http.stream("POST", "/responses", json={**payload, "stream": True}) as r:
                if r.status_code != 200:
                    raise ApiError(r.status_code, r.read().decode(errors="replace"))
                return collect_stream(iter_sse(r.iter_lines()))
        return self._retrying(call)

    def create_response(self, payload: dict) -> dict:
        def call():
            r = self.http.post("/responses", json={**payload, "stream": False})
            if r.status_code != 200:
                raise ApiError(r.status_code, r.text)
            return r.json()
        return self._retrying(call)

    def cached(self, namespace: str, request: dict, run, cost_fn, estimate_usd: float, what: str,
               require_text: bool = False, complete=None) -> dict:
        """Serve from cache, or reserve budget, call, record the real cost and cache only complete results."""
        key = request_key(namespace, request)
        hit = self.cache.get(namespace, key)
        if hit is not None:
            return hit
        self.meter.reserve(estimate_usd, what)
        try:
            result = run()
            usd, model, usage = cost_fn(result)
            self.meter.record(model, usd, what, **usage)
        finally:
            self.meter.release(estimate_usd)
        status = result.get("status")
        done = complete(result) if complete else status == "completed"
        if not done or (require_text and not output_text(result).strip()):
            raise IncompleteResponse(f"{what}: status={status!r}, details={result.get('incomplete_details')}", usd)
        self.cache.put(namespace, key, result)
        return result

    def check_budget(self, estimate_usd: float, what: str) -> None:
        """Refuse a run whose estimate does not fit under the cap; replays make no calls and are not checked."""
        if not self.s.replay:
            self.meter.check(estimate_usd, what)

    def post_json(self, path: str, body: dict) -> dict:
        def call():
            r = self.http.post(path, json=body)
            if r.status_code != 200:
                raise ApiError(r.status_code, r.text)
            return r.json()
        return self._retrying(call)

    def post_form(self, path: str, files: dict, headers: dict | None = None) -> dict:
        def call():
            r = self.http.post(path, files=files, headers=headers or {})
            if r.status_code != 200:
                raise ApiError(r.status_code, r.text)
            return r.json()
        return self._retrying(call)

    def upload_file(self, path: Path, expire_seconds: int = 7 * 24 * 3600) -> str:
        path = Path(path)
        req = {"sha256": file_sha256(path), "name": path.name}
        key = request_key("files", req)
        hit = self.cache.get("files", key)
        margin = 3600
        if hit is not None and (hit.get("expires_at") or 0) > time.time() + margin:
            return hit["id"]

        def call():
            with path.open("rb") as f:
                r = self.http.post(
                    "/files",
                    data={"purpose": "user_data", "expires_after[anchor]": "created_at",
                          "expires_after[seconds]": str(expire_seconds)},
                    files={"file": (path.name, f, "application/octet-stream")},
                )
            if r.status_code != 200:
                raise ApiError(r.status_code, r.text)
            return r.json()

        out = self._retrying(call)
        self.cache.put("files", key, out)
        return out["id"]

    def delete_file(self, file_id: str) -> None:
        self.http.delete(f"/files/{file_id}")
