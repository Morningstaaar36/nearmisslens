from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: _path("NML_DATA", ROOT.parent / "data"))
    cache_dir: Path = field(default_factory=lambda: _path("NML_CACHE", ROOT / "cache"))
    runs_dir: Path = field(default_factory=lambda: _path("NML_RUNS", ROOT / "runs"))
    budget_usd: float = field(default_factory=lambda: float(os.environ.get("NML_BUDGET_USD", "60")))
    replay: bool = field(default_factory=lambda: os.environ.get("NML_REPLAY", "") == "1")
    api_base: str = "https://api.meta.ai/v1"

    @property
    def ledger(self) -> Path:
        return self.runs_dir / "ledger.jsonl"

    @staticmethod
    def api_key() -> str:
        key = os.environ.get("MODEL_API_KEY", "")
        if not key:
            raise RuntimeError("MODEL_API_KEY is not set")
        return key


SETTINGS = Settings()
