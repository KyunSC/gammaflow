"""Bootstrap helpers. block_idx is close_auction_study.block_idx verbatim (unchanged on the MFP branch)."""
from __future__ import annotations

import numpy as np


def block_idx(n: int, n_boot: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """n_boot x n indices of a moving-block bootstrap (blocks of `block` consecutive observations)."""
    starts = rng.integers(0, max(1, n - block + 1), size=(n_boot, -(-n // block)))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n_boot, -1)[:, :n]
    return np.minimum(idx, n - 1)
