"""Layered WorldGrid backed by NumPy arrays."""

from __future__ import annotations

from enum import IntEnum
from typing import Final

import numpy as np
from numpy.typing import NDArray

from ecosystemsim.config import REQUIRED_LAYERS, MapConfig

# ---------------------------------------------------------------------------
# Layer constants
# ---------------------------------------------------------------------------

LAYER_NAMES: Final[tuple[str, ...]] = REQUIRED_LAYERS
NUM_LAYERS: Final[int] = len(LAYER_NAMES)

NO_OCCUPANT: Final[int] = -1


class Layer(IntEnum):
    GROUND = 0
    UNDERSTORY = 1
    TRUNK = 2
    CANOPY = 3
    CAVITY = 4


# ---------------------------------------------------------------------------
# WorldGrid
# ---------------------------------------------------------------------------


class WorldGrid:
    """50×50×5-capable world grid with typed per-layer arrays."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

        shape2 = (height, width)
        shape3 = (NUM_LAYERS, height, width)

        # Layer presence: True means the layer exists at that tile.
        # Ground is present everywhere; others are absent by default.
        self.layer_present: NDArray[np.bool_] = np.zeros(shape3, dtype=np.bool_)
        self.layer_present[Layer.GROUND] = True

        # Occupant id per layer, -1 means empty.
        self.occupants: NDArray[np.int32] = np.full(shape3, NO_OCCUPANT, dtype=np.int32)

        # Terrain / cover / opacity placeholders (float32, 0–1 range).
        self.cover: NDArray[np.float32] = np.zeros(shape3, dtype=np.float32)
        self.opacity: NDArray[np.float32] = np.zeros(shape3, dtype=np.float32)
        self.terrain: NDArray[np.float32] = np.zeros(shape2, dtype=np.float32)

        # Resource biomass per layer (arbitrary units).
        self.resource_biomass: NDArray[np.float32] = np.zeros(shape3, dtype=np.float32)

        # Scent fields per layer (0–1 intensity).
        self.scent: NDArray[np.float32] = np.zeros(shape3, dtype=np.float32)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def is_layer_present(self, layer: Layer, y: int, x: int) -> bool:
        return bool(self.layer_present[layer, y, x])

    def get_occupant(self, layer: Layer, y: int, x: int) -> int:
        return int(self.occupants[layer, y, x])

    def set_occupant(self, layer: Layer, y: int, x: int, agent_id: int) -> None:
        self.occupants[layer, y, x] = agent_id

    def clear_occupant(self, layer: Layer, y: int, x: int) -> None:
        self.occupants[layer, y, x] = NO_OCCUPANT

    def is_empty(self, layer: Layer, y: int, x: int) -> bool:
        return bool(self.occupants[layer, y, x] == NO_OCCUPANT)

    def present_layers(self, y: int, x: int) -> list[str]:
        return [LAYER_NAMES[li] for li in range(NUM_LAYERS) if self.layer_present[li, y, x]]


def make_world(cfg: MapConfig) -> WorldGrid:
    return WorldGrid(cfg.width, cfg.height)
