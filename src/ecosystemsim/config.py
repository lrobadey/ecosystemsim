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


class FloraConfig(msgspec.Struct, frozen=True):
    black_spruce_density: float = 0.14
    snag_fraction: float = 0.12
    moss_patch_density: float = 0.10
    fungi_patch_density: float = 0.06

    def __post_init__(self) -> None:
        for name, value in (
            ("black_spruce_density", self.black_spruce_density),
            ("snag_fraction", self.snag_fraction),
            ("moss_patch_density", self.moss_patch_density),
            ("fungi_patch_density", self.fungi_patch_density),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0.0, 1.0], got {value}")


def default_flora_config() -> FloraConfig:
    return FloraConfig()


class ChickadeeParamsConfig(msgspec.Struct, frozen=True):
    count: int = 2
    start_energy_kj: float = 38.0
    target_energy_kj: float = 55.0
    max_energy_kj: float = 70.0
    starvation_threshold_kj: float = 0.0
    daytime_metabolism_kj_per_tick: float = 0.0058
    cavity_metabolism_multiplier: float = 0.70
    crown_metabolism_multiplier: float = 0.85
    forage_yield_kj_per_biomass: float = 1.8
    forage_bite_max_biomass: float = 0.4
    move_cost_kj: float = 0.05
    perception_radius: int = 6
    memory_capacity: int = 8
    food_beacon_radius: int = 40  # tiles; 40 × 2 m = 80 m, plausible stand-scale visibility

    def __post_init__(self) -> None:
        non_negative = (
            ("start_energy_kj", self.start_energy_kj),
            ("target_energy_kj", self.target_energy_kj),
            ("max_energy_kj", self.max_energy_kj),
            ("starvation_threshold_kj", self.starvation_threshold_kj),
            ("daytime_metabolism_kj_per_tick", self.daytime_metabolism_kj_per_tick),
            ("forage_yield_kj_per_biomass", self.forage_yield_kj_per_biomass),
            ("forage_bite_max_biomass", self.forage_bite_max_biomass),
            ("move_cost_kj", self.move_cost_kj),
        )
        for name, value in non_negative:
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        for name, value in (
            ("cavity_metabolism_multiplier", self.cavity_metabolism_multiplier),
            ("crown_metabolism_multiplier", self.crown_metabolism_multiplier),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {value}")
        if self.count < 0:
            raise ValueError(f"count must be >= 0, got {self.count}")
        if self.perception_radius < 0:
            raise ValueError(f"perception_radius must be >= 0, got {self.perception_radius}")
        if self.memory_capacity < 1:
            raise ValueError(f"memory_capacity must be >= 1, got {self.memory_capacity}")
        if self.food_beacon_radius < 0:
            raise ValueError(f"food_beacon_radius must be >= 0, got {self.food_beacon_radius}")


class FaunaConfig(msgspec.Struct, frozen=True):
    chickadees: ChickadeeParamsConfig = msgspec.field(default_factory=ChickadeeParamsConfig)


def default_fauna_config() -> FaunaConfig:
    return FaunaConfig()


class RunConfig(msgspec.Struct, frozen=True):
    seed: int
    map: MapConfig
    clock: ClockConfig
    flora: FloraConfig = msgspec.field(default_factory=FloraConfig)
    fauna: FaunaConfig = msgspec.field(default_factory=FaunaConfig)

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
        flora=default_flora_config(),
        fauna=default_fauna_config(),
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
    decoded.flora.__post_init__()
    decoded.fauna.chickadees.__post_init__()


def make_scenario_json(path: Path | str) -> None:
    """Write the default scenario to a JSON file."""
    cfg = default_run_config()
    Path(path).write_bytes(encode_config(cfg))
