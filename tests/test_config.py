"""Tests for typed scenario config."""

from pathlib import Path

import pytest

from ecosystemsim.config import (
    REQUIRED_LAYERS,
    ClockConfig,
    MapConfig,
    RunConfig,
    default_run_config,
    load_config_from_json,
)


def test_default_config_is_valid() -> None:
    cfg = default_run_config()
    assert cfg.seed == 40217
    assert cfg.map.width == 50
    assert cfg.map.height == 50
    assert cfg.clock.tick_seconds == 10.0
    assert cfg.clock.max_ticks == 8640


def test_scenario_file_loads(tmp_path: Path) -> None:
    scenario = Path(__file__).parent.parent / "scenarios" / "late_winter_microforest.json"
    cfg = RunConfig.from_file(scenario)
    assert cfg.seed == 40217
    assert cfg.map.width == 50


def test_layer_order_is_stable() -> None:
    cfg = default_run_config()
    assert tuple(cfg.map.layers[: len(REQUIRED_LAYERS)]) == REQUIRED_LAYERS


def test_invalid_width_fails() -> None:
    with pytest.raises(ValueError, match="width"):
        m = MapConfig(width=0, height=50, layers=REQUIRED_LAYERS)
        m.__post_init__()


def test_invalid_height_fails() -> None:
    with pytest.raises(ValueError, match="height"):
        m = MapConfig(width=50, height=-1, layers=REQUIRED_LAYERS)
        m.__post_init__()


def test_missing_layer_fails() -> None:
    bad_layers = ("ground", "understory", "trunk", "canopy")  # cavity missing
    with pytest.raises(ValueError, match="cavity"):
        m = MapConfig(width=50, height=50, layers=bad_layers)
        m.__post_init__()


def test_wrong_layer_order_fails() -> None:
    scrambled = ("canopy", "ground", "understory", "trunk", "cavity")
    with pytest.raises(ValueError):
        m = MapConfig(width=50, height=50, layers=scrambled)
        m.__post_init__()


def test_zero_tick_seconds_fails() -> None:
    with pytest.raises(ValueError, match="tick_seconds"):
        c = ClockConfig(tick_seconds=0.0, max_ticks=100)
        c.__post_init__()


def test_zero_max_ticks_fails() -> None:
    with pytest.raises(ValueError, match="max_ticks"):
        c = ClockConfig(tick_seconds=10.0, max_ticks=0)
        c.__post_init__()


def test_json_round_trip() -> None:
    import msgspec

    cfg = default_run_config()
    raw = msgspec.json.encode(cfg)
    restored = load_config_from_json(raw)
    assert restored.seed == cfg.seed
    assert restored.map.width == cfg.map.width
    assert restored.clock.max_ticks == cfg.clock.max_ticks
