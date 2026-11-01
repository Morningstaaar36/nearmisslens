"""Site check (NML-Bench T16): Muse Spark reads the corner's aerial photo and says what is there; SAM 3.1 must find each
thing Spark says is present near where Spark points; the city's own map layers and OpenStreetMap score both.

An engineer visits a site before recommending a fix. This is the remote version, with a second model as the check:
- Muse Spark (Meta API) answers present / absent / unsure for each attribute, with points on the image;
- SAM 3.1 segments the attribute's noun phrase on the same image;
- the gated answer is "present" only when SAM finds it within 15 m of a Spark point, "absent" only when both find
  nothing, and "unsure" otherwise.
The design (attributes, ground truth, thresholds, the rule for using an attribute) is in validation/experiments/T16.json."""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

from . import brief, context, sam_api
from .config import ROOT, SETTINGS
from .cost import token_usd
from .meta_client import output_text

SPEC = json.loads((ROOT / "validation" / "experiments" / "T16.json").read_text())
CATALOG = json.loads((Path(__file__).resolve().parent / "data" / "site_attributes.json").read_text())["attributes"]
MODEL = "muse-spark-1.3-contributor"
SIZE, SPAN_M = brief.AERIAL_PX, 2 * brief.AERIAL_RADIUS_M
M_PER_PX = SPAN_M / SIZE
ATTRS = list(CATALOG)
SCHEMA = {"type": "object", "additionalProperties": False, "required": ATTRS,
          "properties": {a: {"type": "object", "additionalProperties": False, "required": ["answer", "points"],
                             "properties": {"answer": {"type": "string", "enum": ["present", "absent", "unsure"]},
                                            "points": {"type": "array", "maxItems": 6, "items": {
                                                "type": "array", "items": {"type": "integer"}, "minItems": 2,
                                                "maxItems": 2}}}} for a in ATTRS}}


def photo(name: str, slug: str, lat: float, lon: float, city: str | None = None) -> Path | None:
    """The corner's aerial photo: the one saved with its brief if there is one, else a new one in runs/site/."""
    from .pages import _brief_dir
    saved = _brief_dir(name) / "aerial.jpg"
    if saved.exists():
        return saved
    return brief.aerial(lat, lon, city or context.city_of(lat, lon), SETTINGS.runs_dir / "site" / slug / "aerial.jpg")


def _circle(shape, radius_m: float) -> np.ndarray:
    h, w = shape[:2]
    yy, xx = np.mgrid[:h, :w]
    return (xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= (radius_m / M_PER_PX) ** 2


# ------------------------------------------------------------------------------------------------- the two models

def spark(client, img_path: Path, tag: str) -> dict:
    """Muse Spark's answer per attribute, with points in image pixels."""
    img = cv2.imread(str(img_path))
    url = sam_api.png_data_url(img)
    what = "; ".join(f"{a}: {CATALOG[a]['describe']}" for a in ATTRS)
    instructions = (f"This is a top-down aerial photo of a street intersection, {SIZE} x {SIZE} pixels covering "
                    f"{SPAN_M:.0f} m, with the intersection at the centre. For each attribute, answer present, absent "
                    f"or unsure for the area within {SPEC['radius_m']} m of the centre (a circle of radius "
                    f"{SPEC['radius_m'] / M_PER_PX:.0f} pixels), and give up to 6 [x, y] pixel points on the examples "
                    f"you see. Say unsure when trees, shadows or an overpass hide the street. Attributes: {what}.")
    request = {"model": MODEL, "image_sha": sam_api.hashlib.sha256(url.encode()).hexdigest(), "schema": SCHEMA,
               "instructions": instructions}
    payload = {"model": MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 3000, "instructions": instructions,
               "text": {"format": {"type": "json_schema", "name": "site", "schema": SCHEMA, "strict": True}},
               "input": [{"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": url}]}]}

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

    resp = client.cached("spark_site", request, lambda: client.create_response(payload), cost, 0.01,
                         f"site {tag}", require_text=True)
    return json.loads(output_text(resp))


def sam(client, img_path: Path, concept: str, tag: str) -> list:
    img = cv2.imread(str(img_path))
    return sam_api.segment_image(client, img, concept, f"site {tag}")


# ------------------------------------------------------------------------------------------------- the gate

def decide(spark_answer: dict, dets: list, shape, radius_m: float = SPEC["radius_m"], near_m: float = 15.0,
           min_cover: float = 0.002) -> dict:
    """The three arms' answers for one attribute at one corner."""
    circle = _circle(shape, radius_m)
    m = np.zeros(shape[:2], bool)
    for d in dets:
        if d.mask is not None and d.mask.shape == m.shape:
            m |= d.mask > 0
        else:
            m[int(max(d.y1, 0)):int(d.y2), int(max(d.x1, 0)):int(d.x2)] = True
    cover = float((m & circle).sum() / max(circle.sum(), 1))
    sam_present = cover >= min_cover
    ans = spark_answer.get("answer", "unsure")
    near_px = near_m / M_PER_PX
    ys, xs = np.nonzero(m)
    confirmed = bool(len(xs)) and any(np.min((xs - x) ** 2 + (ys - y) ** 2) <= near_px ** 2
                                      for x, y in (spark_answer.get("points") or []) if 0 <= x < shape[1] and 0 <= y < shape[0])
    gated = "present" if ans == "present" and confirmed else "absent" if ans == "absent" and not sam_present else "unsure"
    return {"spark": ans, "sam": "present" if sam_present else "absent", "gated": gated, "sam_cover": round(cover, 4),
            "spark_points": spark_answer.get("points") or [], "sam_confirmed_point": confirmed}


# ------------------------------------------------------------------------------------------------- ground truth

def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.pi / 180
    x = (lon2 - lon1) * k * math.cos((lat1 + lat2) / 2 * k)
    return 6371000 * math.hypot(x, (lat2 - lat1) * k)


def _osm_tile(a: dict, lat: float, lon: float) -> list[dict]:
    """The adapter's tagged OpenStreetMap nodes in the map tile holding the point (tile_deg degrees square, default 0.1).
    One request per tile, cached, instead of one per corner: nearby corners share it and public servers are spared."""
    d = float(a.get("tile_deg", 0.1))
    s, w = math.floor(lat / d) * d, math.floor(lon / d) * d
    box = f"{s - 0.001:.4f},{w - 0.001:.4f},{s + d + 0.001:.4f},{w + d + 0.001:.4f}"  # overlap covers points on an edge
    q = f'[out:json][timeout:120];{a["osm_filter"]}["{a["tag"]}"]({box});out;'
    js, _ = context.fetch(context.OVERPASS, data={"data": q}, timeout=180)
    return [e for e in js.get("elements", []) if "lat" in e]


def _truth_one(a: dict, lat: float, lon: float, radius_m: float):
    """One site_truth adapter's answer at the point: True, False, or None when the source says nothing."""
    if a["platform"] == "socrata":
        rows, _ = context.fetch(a["endpoint"], {"$where": f"within_circle({a['geo_field']},{lat},{lon},{radius_m})",
                                                "$limit": 500})
        rows = rows if isinstance(rows, list) else []
        rule = a.get("yes_when", "any")
        if rule == "any":
            return bool(rows)
        return any(str(r.get(rule["field"], "")).strip() in rule["in"] for r in rows)
    if a["platform"] == "osm":  # the OpenStreetMap API's map call for a box just around the point
        dlat = radius_m * 1.1 / 111320
        dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
        js, _ = context.fetch(f"{a.get('api', 'https://api.openstreetmap.org/api/0.6')}/map.json",
                              {"bbox": f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"}, timeout=60)
        match = a.get("match", {})
        vals = [str(e.get("tags", {}).get(a["tag"], "")) for e in js.get("elements", [])
                if e.get("type") == a.get("element", "node") and "lat" in e
                and all(e.get("tags", {}).get(k) == v for k, v in match.items())
                and _metres(lat, lon, e["lat"], e["lon"]) <= radius_m]
        tagged = [v for v in vals if v]
        return any(v.split(":")[0] in a["yes_values"] for v in tagged) if tagged else None
    if a["platform"] == "overpass":
        vals = [str(e.get("tags", {}).get(a["tag"], "")) for e in _osm_tile(a, lat, lon)
                if _metres(lat, lon, e["lat"], e["lon"]) <= radius_m]
        tagged = [v for v in vals if v]
        return any(v.split(":")[0] in a["yes_values"] for v in tagged) if tagged else None
    raise ValueError(f"unknown site_truth platform {a['platform']!r}")


def truth(lat: float, lon: float, radius_m: float = SPEC["radius_m"]) -> dict:
    """Each attribute's ground truth at the point from the registry's site_truth adapters that cover it (a city's own
    layer wins over a global one); None when no source covers it or the source is silent."""
    from . import opendata
    out, sources = {}, {}
    failed = {}
    for a in sorted(opendata.adapters_for(lat, lon, "site_truth"), key=lambda a: a.get("city") is None):
        if a["attribute"] in out and out[a["attribute"]] is not None:
            continue
        try:
            out[a["attribute"]] = _truth_one(a, lat, lon, radius_m)
            sources[a["attribute"]] = a["source"]
        except Exception as e:  # an unreachable source makes that attribute unknown here (excluded), not the corner
            failed[a["attribute"]] = f"{type(e).__name__}: {str(e)[:120]}"
    return {**{k: out.get(k) for k in ATTRS}, "sources": sources, **({"failed": failed} if failed else {})}


# ------------------------------------------------------------------------------------------------- T16

def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if not n:
        return [0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def score(rows: list[dict]) -> dict:
    """Accuracy on decided corners and coverage, per attribute and arm."""
    out = {}
    for a in ATTRS:
        out[a] = {}
        for arm in ("spark", "sam", "gated"):
            pairs = [(r["answers"][a][arm], r["truth"][a]) for r in rows if r.get("answers") and r["truth"].get(a) is not None]
            dec = [(x, t) for x, t in pairs if x in ("present", "absent")]
            ok = sum((x == "present") == bool(t) for x, t in dec)
            out[a][arm] = {"corners": len(pairs), "decided": len(dec), "coverage": round(len(dec) / max(len(pairs), 1), 3),
                           "accuracy": round(ok / len(dec), 3) if dec else None, "accuracy_ci95": wilson(ok, len(dec)),
                           "truth_yes": sum(bool(t) for _, t in pairs)}
        g = out[a]["gated"]
        out[a]["used_in_product"] = bool(g["accuracy"] is not None and g["accuracy"] >= 0.85 and g["coverage"] >= 0.5)
    return out


def run_t16(client, corners: list[dict], out: Path | None = None, workers: int = 4) -> dict:
    """Both models on every corner's photo, the gate, and the ground truth; corners run in parallel (the time goes on
    waiting for public servers) and results are written as each corner finishes."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from .evaluate import RESULTS_DIR
    out = out or RESULTS_DIR / "bench" / "experiment_T16.json"
    res = json.loads(out.read_text()) if out.exists() else {"id": "T16", "spec": SPEC, "rows": []}
    res["rows"] = [r for r in res["rows"] if not r.get("error")]  # failed corners are tried again
    done = {r["slug"] for r in res["rows"]}
    lock = threading.Lock()
    for r in res["rows"]:  # a ground-truth source that failed is asked again; the models' answers are kept
        if r.get("truth", {}).get("failed"):
            new = truth(r["lat"], r["lon"])
            if len(new.get("failed", {})) < len(r["truth"]["failed"]):
                r["truth"] = new

    def one(c: dict) -> None:
        row = {"slug": c["slug"], "name": c["name"], "lat": c["lat"], "lon": c["lon"]}
        try:
            row["truth"] = truth(c["lat"], c["lon"])
            p = photo(c["name"], c["slug"], c["lat"], c["lon"])
            if p is None:
                row["error"] = "no aerial photo"
            else:
                img = cv2.imread(str(p))
                sp = spark(client, p, c["slug"])
                row["answers"] = {a: decide(sp.get(a, {}), sam(client, p, CATALOG[a]["sam_concept"], c["slug"]),
                                            img.shape) for a in ATTRS}
        except Exception as e:  # one corner's failure is recorded, not fatal
            row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        with lock:
            res["rows"].append(row)
            out.write_text(json.dumps(res, indent=0, default=str))

    todo, seen = [], set(done)
    for c in corners:
        if c["slug"] not in seen:
            seen.add(c["slug"])
            todo.append(c)
    with ThreadPoolExecutor(max(1, workers)) as pool:
        list(pool.map(one, todo))
    res["summary"] = score(res["rows"])
    out.write_text(json.dumps(res, indent=0, default=str))
    return res
