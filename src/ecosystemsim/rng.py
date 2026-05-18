"""Seedable RNG wrapper — single point of randomness for the simulation."""

from __future__ import annotations

import numpy as np
from numpy.random import Generator


def make_rng(seed: int) -> Generator:
    """Return a seeded NumPy default_rng instance."""
    return np.random.default_rng(seed)
