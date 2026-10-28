from __future__ import annotations

from collections.abc import Hashable

import numpy as np
from scipy.optimize import linear_sum_assignment


def one_to_one(votes: dict[tuple[Hashable, Hashable], int], need: int) -> dict[Hashable, Hashable]:
    """Maximum-vote one-to-one assignment between left and right ids; returns right -> left for pairs with >= need votes."""
    if not votes:
        return {}
    left = sorted({a for a, _ in votes}, key=str)
    right = sorted({b for _, b in votes}, key=str)
    li = {a: k for k, a in enumerate(left)}
    ri = {b: k for k, b in enumerate(right)}
    V = np.zeros((len(left), len(right)))
    for (a, b), n in votes.items():
        V[li[a], ri[b]] = n
    rows, cols = linear_sum_assignment(-V)
    return {right[c]: left[r] for r, c in zip(rows, cols) if V[r, c] >= need}


def nearest_pairs(a: np.ndarray, b: np.ndarray, radius: float) -> list[tuple[int, int]]:
    """Hungarian matching of two point sets; pairs closer than radius."""
    if len(a) == 0 or len(b) == 0:
        return []
    D = np.linalg.norm(a[:, None] - b[None], axis=2)
    i, j = linear_sum_assignment(D)
    ok = D[i, j] < radius
    return list(zip(i[ok].tolist(), j[ok].tolist()))
