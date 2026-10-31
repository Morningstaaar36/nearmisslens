"""Frames for the demo video drawn from the results files (PIL only): the opening junction, the four gates, every
program's gated effect next to the naive one, and the AI analyst with and without the gate."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .demo import H, INK, MARKING, PAPER, W, font, wrap

MUTED, GREEN, GREY, ORANGE, RED = (91, 104, 113), (30, 140, 90), (150, 158, 165), (226, 132, 30), (200, 60, 50)


def _canvas(title: str, work: Path) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 18, W, H], fill=MARKING)
    d.text((140, 90), title, font=font(72, work), fill=INK)
    return img, d


def hook(aerial: Path, title: str, lines: list[str], out: Path, work: Path) -> Path:
    """The junction's aerial photo on the left, its record on the right."""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    photo = Image.open(aerial).convert("RGB").resize((H - 18, H - 18))
    img.paste(photo, (0, 0))
    d.rectangle([0, H - 18, W, H], fill=MARKING)
    x, y = H + 70, 230
    for line in wrap(d, title, font(70, work), W - x - 100):
        d.text((x, y), line, font=font(70, work), fill=INK)
        y += 86
    y += 40
    for text in lines:
        for line in wrap(d, text, font(44, work), W - x - 100):
            d.text((x, y), line, font=font(44, work), fill=MUTED)
            y += 60
        y += 22
    img.save(out)
    return out


def gates(out: Path, work: Path) -> Path:
    """Agent proposes, the gate tries to disprove, the claim is shown or refused; one row per gate."""
    img, d = _canvas("Every claim meets a gate", work)
    rows = [("a number in a brief or letter", "it must be in the official record"),
            ("\"this dataset is the city's crashes\"", "real records near the city, recent dates, numeric injuries"),
            ("\"this fix works in this city\"", "the city's own past installs vs sites treated later, a placebo date, held-out sites"),
            ("\"the drawing shows the fix\"", "SAM 3.1 finds it, and no real car moved")]
    f, fs = font(40, work), font(34, work)
    y = 260
    for claim, test in rows:
        d.rounded_rectangle([140, y, 700, y + 130], 18, fill=(255, 255, 255), outline=INK, width=3)
        for k, line in enumerate(wrap(d, claim, f, 520)[:2]):
            d.text((165, y + 22 + 46 * k), line, font=f, fill=INK)
        d.line([710, y + 65, 790, y + 65], fill=INK, width=5)
        d.polygon([(790, y + 50), (815, y + 65), (790, y + 80)], fill=INK)
        d.rounded_rectangle([830, y, 1560, y + 130], 18, fill=(255, 248, 225), outline=ORANGE, width=3)
        for k, line in enumerate(wrap(d, test, fs, 690)[:3]):
            d.text((855, y + 18 + 40 * k), line, font=fs, fill=INK)
        d.text((1600, y + 28), "shown", font=f, fill=GREEN)
        d.text((1600, y + 74), "or refused", font=fs, fill=RED)
        y += 170
    img.save(out)
    return out


def forest(rows: list[dict], out: Path, work: Path, lo: float = -60, hi: float = 70) -> Path:
    """One row per program: the gate's estimate and 95% interval (green when it passed) and the naive estimate."""
    img, d = _canvas("What the gate found", work)
    x0, x1 = 1060, 1800

    def X(v):
        return x0 + (min(max(v, lo), hi) - lo) / (hi - lo) * (x1 - x0)
    top, step = 270, min(95, int((H - 420) / max(len(rows), 1)))
    f, fs = font(36, work), font(28, work)
    for v in range(int(lo), int(hi) + 1, 20):
        d.line([X(v), top - 20, X(v), top + step * len(rows)], fill=(225, 228, 230), width=2)
        d.text((X(v) - 30, top + step * len(rows) + 10), f"{v:+d}%", font=fs, fill=MUTED)
    d.line([X(0), top - 30, X(0), top + step * len(rows)], fill=INK, width=3)
    for k, r in enumerate(rows):
        y = top + k * step + step // 2
        d.text((140, y - 34), r["label"], font=f, fill=INK)
        d.text((140, y + 8), r["verdict"], font=fs, fill=GREEN if r["passed"] else MUTED)
        col = GREEN if r["passed"] else GREY
        if r.get("ci"):
            d.line([X(r["ci"][0]), y, X(r["ci"][1]), y], fill=col, width=7)
        if r.get("effect") is not None:
            d.ellipse([X(r["effect"]) - 13, y - 13, X(r["effect"]) + 13, y + 13], fill=col)
        if r.get("naive") is not None:
            d.ellipse([X(r["naive"]) - 11, y - 11, X(r["naive"]) + 11, y + 11], outline=ORANGE, width=5)
    ly = 190
    d.ellipse([1060, ly, 1086, ly + 26], fill=GREEN)
    d.text((1100, ly - 4), "gate estimate, 95% interval", font=fs, fill=INK)
    d.ellipse([1520, ly, 1544, ly + 24], outline=ORANGE, width=5)
    d.text((1560, ly - 4), "simple before/after", font=fs, fill=INK)
    img.save(out)
    return out


def analyst(ungated: tuple[int, int], gated: tuple[int, int], real: list[dict], out: Path, work: Path) -> Path:
    """Fake programs credited with a reduction, without and with the gate, and the real programs' claims."""
    img, d = _canvas("An AI analyst, with and without the gate", work)
    f, fs = font(40, work), font(32, work)
    d.text((140, 220), "Muse Spark Open writes and runs its own analysis code.", font=fs, fill=MUTED)
    for k, (name, (n, of)) in enumerate((("without the gate", ungated), ("with the gate", gated))):
        y = 320 + k * 120
        d.text((140, y), name, font=f, fill=INK)
        d.rectangle([620, y, 620 + 900, y + 60], outline=GREY, width=2)
        if of:
            d.rectangle([620, y, 620 + int(900 * n / of), y + 60], fill=RED)
        d.text((1550, y + 6), f"{n} of {of} fakes credited", font=fs, fill=INK)
    y = 600
    d.text((140, y), "Real programs", font=f, fill=INK)
    y += 70
    for r in real[:6]:
        d.text((140, y), r["label"], font=fs, fill=INK)
        d.text((900, y), f"without the gate: {r['ungated']}", font=fs, fill=MUTED)
        d.text((1400, y), f"with the gate: {r['gated']}", font=fs, fill=GREEN if r["gated"].startswith("reduced") else MUTED)
        y += 52
    img.save(out)
    return out
