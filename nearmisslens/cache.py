from __future__ import annotations

import gzip
import hashlib
import json
from functools import lru_cache
from pathlib import Path


class ReplayMiss(KeyError):
    pass


def request_key(namespace: str, request: dict) -> str:
    blob = json.dumps({"ns": namespace, "req": request}, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def file_sha256(path: Path, block: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=64)
def _sha_cached(path: str, size: int, mtime_ns: int) -> str:
    return file_sha256(Path(path))


def source_sha(path: Path) -> str:
    """SHA-256 of a source file, memoised on path, size and modification time."""
    st = Path(path).stat()
    return _sha_cached(str(path), st.st_size, st.st_mtime_ns)


class Cache:
    def __init__(self, root: Path, replay: bool = False):
        self.root = Path(root)
        self.replay = replay

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / key[:2] / f"{key}.json.gz"

    def get(self, namespace: str, key: str):
        p = self._path(namespace, key)
        if p.exists():
            return json.loads(gzip.decompress(p.read_bytes()))
        if self.replay:
            raise ReplayMiss(f"{namespace}/{key}")
        return None

    def put(self, namespace: str, key: str, value) -> None:
        p = self._path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(json.dumps(value).encode()))
        tmp.replace(p)
