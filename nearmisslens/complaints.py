"""Synthetic spoken complaints for testing the voice intake end to end. Each is filled in from one hotspot's
dominant conflict (road users, main movement, main approach), or describes a road-user pair no hotspot shows (a
decoy, which should match nothing), and is spoken by Meta's MMS-TTS. They test speech recognition, extraction and
matching; they are not residents' reports."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from . import voice

LANGS = {"eng": "English", "spa": "Spanish", "fra": "French"}
ARM_WORD = {"eng": {"N": "north", "E": "east", "S": "south", "W": "west"},
            "spa": {"N": "norte", "E": "este", "S": "sur", "W": "oeste"},
            "fra": {"N": "nord", "E": "est", "S": "sud", "W": "ouest"}}
MOVE_WORD = {"eng": {"left": "turning left", "right": "turning right", "through": "going straight", "u_turn": "making U-turns"},
             "spa": {"left": "girando a la izquierda", "right": "girando a la derecha", "through": "siguiendo recto",
                     "u_turn": "dando media vuelta"},
             "fra": {"left": "en tournant à gauche", "right": "en tournant à droite", "through": "en allant tout droit",
                     "u_turn": "en faisant demi-tour"}}
SUBJECT = {"eng": {"vehicle": "cars", "two_wheeler": "scooters", "pedestrian": "people on foot"},
           "spa": {"vehicle": "coches", "two_wheeler": "motos", "pedestrian": "peatones"},
           "fra": {"vehicle": "des voitures", "two_wheeler": "des scooters", "pedestrian": "des piétons"}}
OBJECT = {"eng": {"vehicle": "cars", "two_wheeler": "scooters", "pedestrian": "people on foot"},
          "spa": {"vehicle": "coches", "two_wheeler": "motos", "pedestrian": "peatones"},
          "fra": {"vehicle": "des voitures", "two_wheeler": "des scooters", "pedestrian": "des piétons"}}
OTHER = {"eng": {"vehicle": "other cars", "two_wheeler": "other scooters", "pedestrian": "other people on foot"},
         "spa": {"vehicle": "otros coches", "two_wheeler": "otras motos", "pedestrian": "otros peatones"},
         "fra": {"vehicle": "d'autres voitures", "two_wheeler": "d'autres scooters", "pedestrian": "d'autres piétons"}}
TEMPLATE = {
    "eng": "Every day at this junction, {u1} coming from the {arm} side and {move} nearly hit {u2}. "
           "Someone is going to get hurt.",
    "spa": "Todos los días en este cruce, {u1} que vienen del lado {arm} {move} casi chocan con {u2}. "
           "Alguien va a salir herido.",
    "fra": "Tous les jours à ce carrefour, {u1} venant du côté {arm} {move} manquent de percuter {u2}. "
           "Quelqu'un va être blessé.",
}


def sentence(lang: str, pair: tuple[str, str], move: str, arm: str) -> str:
    u2 = OTHER[lang][pair[1]] if pair[0] == pair[1] else OBJECT[lang][pair[1]]
    text = TEMPLATE[lang].format(u1=SUBJECT[lang][pair[0]], u2=u2, arm=ARM_WORD[lang][arm], move=MOVE_WORD[lang][move])
    return text[0].upper() + text[1:]


def _top(counts: dict, allowed) -> str | None:
    ok = {k: v for k, v in counts.items() if k in allowed and v}
    return max(ok, key=ok.get) if ok else None


def synthesize(facts: dict) -> list[dict]:
    """One complaint per hotspot (rotating through LANGS) and one decoy, each with the slots it was built from."""
    out = []
    langs = list(LANGS)
    for k, f in enumerate(facts["findings"]):
        d = f["dominant"]
        move, arm = _top(d.get("movements", {}), voice.MOVES), _top(d.get("approaches", {}), voice.ARMS)
        if not move or not arm:
            continue
        pair = tuple(d["pair"]) if d["pair"][0] != "pedestrian" else tuple(reversed(d["pair"]))
        lang = langs[k % len(langs)]
        out.append({"source": f"hotspot {f['rank']}", "lang": lang, "pair": list(pair), "movement": move, "approach": arm,
                    "text": sentence(lang, pair, move, arm)})
    seen = {frozenset(f["dominant"]["pair"]) for f in facts["findings"]}
    absent = [(a, b) for a in voice.USERS for b in voice.USERS if a <= b and frozenset((a, b)) not in seen]
    if absent and out:
        pair = absent[0] if absent[0][0] != "pedestrian" else tuple(reversed(absent[0]))
        ref = out[0]
        out.append({"source": "decoy", "lang": "eng", "pair": list(pair), "movement": ref["movement"],
                    "approach": ref["approach"], "text": sentence("eng", pair, ref["movement"], ref["approach"])})
    return out


def expected(c: dict, facts: dict) -> set:
    """Hotspots consistent with the slots the complaint was built from (empty for a decoy)."""
    truth = {"road_users": sorted(set(c["pair"])), "movement": c["movement"], "approach": c["approach"]}
    return {f["rank"] for f in facts["findings"] if voice.consistent(truth, f)[0]}


def speak(text: str, lang: str, out_dir: Path) -> Path:
    """16 kHz mono WAV of the text from facebook/mms-tts-<lang>, cached by text."""
    out = Path(out_dir) / f"{lang}_{hashlib.sha256(text.encode()).hexdigest()[:12]}.wav"
    if out.exists():
        return out
    import torch
    from scipy.io import wavfile
    from transformers import AutoTokenizer, VitsModel
    name = f"facebook/mms-tts-{lang}"
    model, tok = VitsModel.from_pretrained(name), AutoTokenizer.from_pretrained(name)
    torch.manual_seed(0)
    with torch.no_grad():
        wave = model(**tok(text, return_tensors="pt")).waveform[0].numpy()
    out.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(wave / max(np.abs(wave).max(), 1e-6) * 0.9, -1, 1)
    wavfile.write(out, model.config.sampling_rate, (pcm * 32767).astype(np.int16))
    return out
