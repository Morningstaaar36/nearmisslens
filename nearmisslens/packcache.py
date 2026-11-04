"""The replay cache for the GitHub release (nml pack-cache): every cached model and public-data response, so the README's
--replay commands run without keys or network.

Before packing, contact details are removed from cached OpenStreetMap responses (e-mail and phone tags on shops and
offices near a junction are public in OSM, but the project has no reason to republish them), and the pack is refused if
any file holds something that looks like an API key."""
from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from pathlib import Path

from .config import SETTINGS

CONTACT = re.compile(r"(^|:)(e-?mail|phone|fax|mobile)$", re.I)
KEYISH = re.compile(rb"(Bearer\s+[A-Za-z0-9._-]{20,}|Api-Key\s+[A-Za-z0-9._-]{20,}|sk-[A-Za-z0-9]{20,}|"
                    rb"\"(api[_-]?key|authorization)\"\s*:\s*\"[^\"]{12,}\")", re.I)


def scrub(obj):
    """obj with every contact-detail key removed, at any depth."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if not CONTACT.search(str(k))}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def pack(out: Path, cache: Path | None = None) -> dict:
    cache = cache or SETTINGS.cache_dir
    files = sorted(p for p in cache.rglob("*") if p.is_file())
    bad = [str(p.relative_to(cache)) for p in files if KEYISH.search(p.read_bytes())]
    if bad:
        raise RuntimeError(f"refusing to pack: {len(bad)} cached files look like they hold a key, e.g. {bad[:3]}")
    scrubbed = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for p in files:
            rel = Path("cache") / p.relative_to(cache)
            data = p.read_bytes()
            if p.suffix == ".json" and "context" in p.relative_to(cache).parts[:1]:
                try:
                    obj = json.loads(data)
                except ValueError:
                    obj = None
                if obj is not None and scrub(obj) != obj:
                    scrubbed += 1
                    data = json.dumps(scrub(obj)).encode()
            info = tarfile.TarInfo(str(rel))
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    return {"files": len(files), "scrubbed": scrubbed, "mb": round(out.stat().st_size / 1e6, 1), "path": str(out)}


def starter_queries() -> list[str]:
    """The README's no-key example queries, one per line in replay/queries.txt (data, not code)."""
    from .context import STARTER_DIR
    lines = (STARTER_DIR.parent / "queries.txt").read_text().splitlines()
    return [x.strip() for x in lines if x.strip() and not x.startswith("#")]


def starter(queries: list[str] | None = None, cache: Path | None = None) -> dict:
    """The small replay pack committed in replay/context/: exactly the public-data answers the README's --replay
    engineer example reads, contact details removed, refused if any looks like it holds a key. It is built by
    running the example on the full local cache and keeping every answer served."""
    from . import context, engineer
    if not SETTINGS.replay:
        raise RuntimeError("build the starter pack with --replay, so only cached answers are read")
    cache = cache or SETTINGS.cache_dir
    context.SERVED.clear()
    for q in queries or starter_queries():
        engineer.plan(q)
    out = context.STARTER_DIR
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json.gz"):
        old.unlink()
    total = scrubbed = 0
    for key in sorted(context.SERVED):
        src = cache / "context" / f"{key}.json"
        if not src.exists():  # already served from the committed pack
            continue
        data = src.read_bytes()
        if KEYISH.search(data):
            raise RuntimeError(f"refusing to pack: {src.name} looks like it holds a key")
        obj = json.loads(data)
        if scrub(obj) != obj:
            scrubbed += 1
            obj = scrub(obj)
        blob = gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), compresslevel=9, mtime=0)
        (out / f"{key}.json.gz").write_bytes(blob)
        total += len(blob)
    return {"files": len(list(out.glob("*.json.gz"))), "scrubbed": scrubbed, "mb": round(total / 1e6, 2), "path": str(out)}
