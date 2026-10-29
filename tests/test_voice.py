import json

from nearmisslens import complaints, voice
from tests.test_panel import facts as panel_facts


def facts():
    f = panel_facts()
    f["findings"][0]["dominant"] |= {"pair": ["two_wheeler", "vehicle"], "movements": {"left": 4, "through": 2},
                                     "approaches": {"N": 5, "E": 1}}
    second = json.loads(json.dumps(f["findings"][0]))
    second |= {"rank": 2}
    second["dominant"] |= {"pair": ["two_wheeler", "two_wheeler"], "movements": {"through": 3}, "approaches": {"S": 3}}
    f["findings"].append(second)
    return f


def complaint(users, movement="unknown", approach="unknown"):
    return {"road_users": users, "movement": movement, "approach": approach, "concern": "", "language": "English"}


def test_match_needs_the_same_road_users_and_a_movement_or_approach():
    f = facts()
    assert voice.match(complaint(["vehicle", "two_wheeler"], "left", "N"), f)["rank"] == 1
    assert voice.match(complaint(["vehicle", "two_wheeler"], "left", "N"), f)["score"] == 2
    assert voice.match(complaint(["two_wheeler"], approach="S"), f)["rank"] == 2
    assert voice.match(complaint(["vehicle", "two_wheeler"]), f)["rank"] is None
    assert voice.match(complaint(["pedestrian", "vehicle"], "left", "N"), f)["rank"] is None


def test_synthetic_complaints_come_from_hotspots_plus_a_decoy():
    f = facts()
    cs = complaints.synthesize(f)
    assert [c["source"] for c in cs] == ["hotspot 1", "hotspot 2", "decoy"]
    assert cs[0]["lang"] == "eng" and cs[1]["lang"] == "spa"
    assert "turning left" in cs[0]["text"] and "north" in cs[0]["text"] and "otras motos" in cs[1]["text"]
    assert complaints.expected(cs[0], f) == {1} and complaints.expected(cs[1], f) == {2}
    assert complaints.expected(cs[2], f) == set()


def test_word_error_rate():
    assert voice.word_error_rate("Cars turn left, often.", "cars turn left often") == 0
    assert voice.word_error_rate("a b c d", "a x c") == 0.5


class FakeClient:
    def __init__(self, transcript, extracted):
        self.transcript, self.extracted, self.forms, self.payloads = transcript, extracted, [], []

    def cached(self, namespace, request, run, cost_fn, estimate, what, require_text=False, complete=None):
        r = run()
        assert complete is None or complete(r)
        return r

    def post_form(self, path, files, headers=None):
        self.forms.append((path, json.loads(files["request"][1]), files["audio"][2]))
        return {"transcript": self.transcript, "audioDurationMs": 4000, "turns": []}

    def create_response(self, payload):
        self.payloads.append(payload)
        return {"status": "completed", "output_text": json.dumps(self.extracted)}


def test_intake_transcribes_extracts_and_matches(tmp_path):
    wav = tmp_path / "c.wav"
    wav.write_bytes(b"RIFF....WAVE")
    fc = FakeClient("Scooters from the north turning left nearly hit cars.",
                    complaint(["two_wheeler", "vehicle"], "left", "N"))
    r = voice.intake(fc, wav, facts(), "t")
    assert fc.forms[0][0] == "/asr/transcribe" and fc.forms[0][1]["model"] == voice.ASR_MODEL
    assert fc.forms[0][2] == "audio/wav" and fc.payloads[0]["text"]["format"]["strict"] is True
    assert r["match"]["rank"] == 1 and r["audio_s"] == 4.0
