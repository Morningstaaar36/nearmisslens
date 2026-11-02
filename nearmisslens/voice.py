"""Spoken complaints as testable claims: Muse Voice Transcribe turns a recording into text, Muse Spark extracts the
road users, movement and approach it describes, and a fixed rule matches it to a measured hotspot, or reports that the
audit did not observe it."""
from __future__ import annotations

import json
from pathlib import Path

from .cache import file_sha256
from .cost import token_usd, voice_usd
from .meta_client import MetaClient, output_text
from .movements import ARMS
from .config import MODELS

ASR_MODEL = MODELS["voice"]
EXTRACT_MODEL = MODELS["reader"]
USERS = ("vehicle", "two_wheeler", "pedestrian")
MOVES = ("left", "right", "through", "u_turn")
COMPLAINT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["road_users", "movement", "approach", "concern", "language"],
    "properties": {
        "road_users": {"type": "array", "items": {"type": "string", "enum": list(USERS)}},
        "movement": {"type": "string", "enum": [*MOVES, "unknown"]},
        "approach": {"type": "string", "enum": [*ARMS, "unknown"]},
        "concern": {"type": "string"},
        "language": {"type": "string"},
    },
}
EXTRACT_INSTRUCTIONS = (
    "Extract the road-safety complaint in this transcript of a resident's recording about one junction. road_users: "
    "every kind of road user the complaint involves (cars, vans, buses and trucks are vehicle; scooters, mopeds, "
    "motorcycles and bicycles are two_wheeler; people walking are pedestrian). movement: what the road users the "
    "speaker blames are doing (left, right or through, u_turn for turning back), unknown if not said. approach: the "
    "compass side they come from (N, E, S, W), unknown if not said. concern: one sentence in English. language: the "
    "language of the transcript. Use only what the transcript says.")


def transcribe(client: MetaClient, wav: Path, tag: str, language_bias: list[str] | None = None,
               audio_key: str | None = None) -> dict:
    """One-shot transcription of a mono 16-bit WAV at 16 or 24 kHz. audio_key names generated audio by what produced
    it, so the cache does not depend on synthesis output bytes; recordings are keyed by their content."""
    settings = {"model": ASR_MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    if language_bias:
        settings["languageBias"] = language_bias
    request = {**settings, "audio": audio_key or file_sha256(wav)}

    def run():
        with open(wav, "rb") as f:
            return client.post_form("/asr/transcribe", {"request": (None, json.dumps(settings), "application/json"),
                                                         "audio": (Path(wav).name, f.read(), "audio/wav")},
                                    headers={"Accept": "application/json"})

    return client.cached("voice", request, run,
                         lambda r: (voice_usd(r.get("audioDurationMs", 0) / 1000), ASR_MODEL,
                                    {"audio_ms": r.get("audioDurationMs", 0)}),
                         0.001, f"transcribe {tag}", complete=lambda r: isinstance(r.get("transcript"), str))


def extract(client: MetaClient, transcript: str, tag: str) -> dict:
    request = {"model": EXTRACT_MODEL, "instructions": EXTRACT_INSTRUCTIONS, "schema": COMPLAINT_SCHEMA,
               "transcript": transcript}

    def run():
        return client.create_response({
            "model": EXTRACT_MODEL, "instructions": EXTRACT_INSTRUCTIONS, "reasoning": {"effort": "low"},
            "max_output_tokens": 2000,
            "text": {"format": {"type": "json_schema", "name": "complaint", "schema": COMPLAINT_SCHEMA, "strict": True}},
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": transcript}]}]})

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(EXTRACT_MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), EXTRACT_MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

    resp = client.cached("voice_extract", request, run, cost, 0.002, f"extract {tag}", require_text=True)
    return json.loads(output_text(resp))


def consistent(complaint: dict, finding: dict) -> tuple[bool, int, list[str]]:
    """Whether a hotspot's dominant conflicts show what the complaint describes: the same kinds of road user, plus the
    movement or the approach. Returns (consistent, agreeing details, reasons)."""
    d = finding["dominant"]
    users = set(complaint["road_users"])
    if users != set(d["pair"]):
        return False, 0, []
    why = [f"{' and '.join(sorted(users))} conflicts"]
    if complaint["movement"] in MOVES and d.get("movements", {}).get(complaint["movement"]):
        why.append(f"{d['movements'][complaint['movement']]} {complaint['movement']} movements")
    if complaint["approach"] in ARMS and d.get("approaches", {}).get(complaint["approach"]):
        why.append(f"{d['approaches'][complaint['approach']]} entries from {complaint['approach']}")
    return len(why) > 1, len(why) - 1, why


def match(complaint: dict, facts: dict) -> dict:
    """The highest-ranked hotspot most consistent with the complaint, or none."""
    best = None
    for f in facts["findings"]:
        ok, score, why = consistent(complaint, f)
        if ok and (best is None or score > best["score"]):
            best = {"rank": f["rank"], "score": score, "evidence": why}
    return best or {"rank": None, "score": 0, "evidence": []}


def word_error_rate(reference: str, hypothesis: str) -> float:
    norm = lambda s: "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in s).split()
    r, h = norm(reference), norm(hypothesis)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / max(len(r), 1)


def intake(client: MetaClient, wav: Path, facts: dict, tag: str, audio_key: str | None = None) -> dict:
    t = transcribe(client, wav, tag, audio_key=audio_key)
    complaint = extract(client, t["transcript"], tag)
    return {"audio": Path(wav).name, "transcript": t["transcript"], "audio_s": t.get("audioDurationMs", 0) / 1000,
            "complaint": complaint, "match": match(complaint, facts)}
