"""Typed scenario configuration using msgspec."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import msgspec

REQUIRED_LAYERS: Final[tuple[str, ...]] = (
    "ground",
    "understory",
    "trunk",
    "canopy",
    "cavity",
)


class MapConfig(msgspec.Struct, frozen=True):
    width: int
    height: int
    layers: tuple[str, ...]
    tile_scale_m: float = 2.0

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError(f"width must be positive, got {self.width}")
        if self.height <= 0:
            raise ValueError(f"height must be positive, got {self.height}")
        for layer in REQUIRED_LAYERS:
            if layer not in self.layers:
                raise ValueError(f"required layer '{layer}' missing from layers")
        if list(self.layers[: len(REQUIRED_LAYERS)]) != list(REQUIRED_LAYERS):
            raise ValueError(f"layers must begin with {list(REQUIRED_LAYERS)} in stable order")


class ClockConfig(msgspec.Struct, frozen=True):
    tick_seconds: float
    max_ticks: int

    def __post_init__(self) -> None:
        if self.tick_seconds <= 0:
            raise ValueError(f"tick_seconds must be positive, got {self.tick_seconds}")
        if self.max_ticks <= 0:
            raise ValueError(f"max_ticks must be positive, got {self.max_ticks}")


class RunConfig(msgspec.Struct, frozen=True):
    seed: int
    map: MapConfig
    clock: ClockConfig

    @staticmethod
    def from_file(path: Path | str) -> RunConfig:
        data = Path(path).read_bytes()
        return msgspec.json.decode(data, type=RunConfig)


def default_map_config() -> MapConfig:
    return MapConfig(
        width=50,
        height=50,
        layers=REQUIRED_LAYERS,
        tile_scale_m=2.0,
    )


def default_clock_config() -> ClockConfig:
    return ClockConfig(tick_seconds=10.0, max_ticks=8640)


def default_run_config() -> RunConfig:
    return RunConfig(
        seed=40217,
        map=default_map_config(),
        clock=default_clock_config(),
    )


def encode_config(cfg: RunConfig) -> bytes:
    return msgspec.json.encode(cfg)


def load_config_from_json(data: bytes | str) -> RunConfig:
    if isinstance(data, str):
        data = data.encode()
    return msgspec.json.decode(data, type=RunConfig)


def validate_config(cfg: RunConfig) -> None:
    """Re-validate a config by round-tripping through encode/decode."""
    raw = msgspec.json.encode(cfg)
    decoded = msgspec.json.decode(raw, type=RunConfig)
    # Re-trigger post_init validators
    decoded.map.__post_init__()
    decoded.clock.__post_init__()


def make_scenario_json(path: Path | str) -> None:
    """Write the default scenario to a JSON file."""
    cfg = default_run_config()
    Path(path).write_bytes(encode_config(cfg))
