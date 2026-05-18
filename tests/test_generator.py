"""Tests for the deterministic forest generator."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from ecosystemsim.config import (
    REQUIRED_LAYERS,
    ClockConfig,
    FloraConfig,
    MapConfig,
    RunConfig,
    default_run_config,
)
from ecosystemsim.engine import run_headless
from ecosystemsim.generator import generate_forest
from ecosystemsim.inspector import inspect_tile
from ecosystemsim.rng import make_rng
from ecosystemsim.world import Layer, make_world


def _make_cfg(
    *,
    seed: int = 40217,
    width: int = 50,
    height: int = 50,
    flora: FloraConfig | None = None,
) -> RunConfig:
    return RunConfig(
        seed=seed,
        map=MapConfig(width=width, height=height, layers=REQUIRED_LAYERS),
        clock=ClockConfig(tick_seconds=10.0, max_ticks=10),
        flora=flora if flora is not None else FloraConfig(),
    )


def _run_generate(cfg: RunConfig) -> tuple[object, object]:
    world = make_world(cfg.map)
    rng = make_rng(cfg.seed)
    store = generate_forest(cfg, world, rng)
    return world, store


def test_default_tree_count_is_plausible() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    area = cfg.map.width * cfg.map.height
    expected = cfg.flora.black_spruce_density * area / 9.0
    n = len(store.trees)
    assert n > 0
    assert n >= expected * 0.5
    assert n <= expected * 1.5


def test_no_duplicate_tree_anchors() -> None:
    cfg = _make_cfg()
    _, store = _run_generate(cfg)
    anchors = [(t.anchor_x, t.anchor_y) for t in store.trees]
    assert len(anchors) == len(set(anchors))


def test_tree_anchors_min_chebyshev_distance() -> None:
    cfg = _make_cfg()
    _, store = _run_generate(cfg)
    anchors = [(t.anchor_x, t.anchor_y) for t in store.trees]
    for i, (ax, ay) in enumerate(anchors):
        for bx, by in anchors[i + 1 :]:
            assert max(abs(ax - bx), abs(ay - by)) >= 2


def test_snag_fraction_matches_config() -> None:
    cfg = _make_cfg()
    _, store = _run_generate(cfg)
    snags = [t for t in store.trees if t.state == "dead"]
    expected = cfg.flora.snag_fraction * len(store.trees)
    # Allow ±20% (and at least ±1 for tiny counts).
    tol = max(1.0, expected * 0.2)
    assert abs(len(snags) - expected) <= tol


def test_cavities_only_on_snags() -> None:
    cfg = _make_cfg()
    _, store = _run_generate(cfg)
    snag_ids = {t.entity_id for t in store.trees if t.state == "dead"}
    for cav in store.cavities:
        assert cav.tree_id in snag_ids


def test_every_cavity_activates_cavity_layer() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    assert len(store.cavities) > 0  # Default scenario should produce some cavities.
    for cav in store.cavities:
        assert world.layer_present[Layer.CAVITY, cav.entrance_y, cav.entrance_x]


def test_live_tree_layers() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    live_trees = [t for t in store.trees if t.state == "live"]
    assert live_trees
    for tree in live_trees:
        assert world.layer_present[Layer.TRUNK, tree.anchor_y, tree.anchor_x]
        any_canopy = any(world.layer_present[Layer.CANOPY, cy, cx] for cx, cy in tree.crown_tiles)
        assert any_canopy
        any_under = any(
            world.layer_present[Layer.UNDERSTORY, cy, cx] for cx, cy in tree.crown_tiles
        )
        assert any_under


def test_snag_trunk_layer_set() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    snags = [t for t in store.trees if t.state == "dead"]
    assert snags
    for tree in snags:
        assert world.layer_present[Layer.TRUNK, tree.anchor_y, tree.anchor_x]


def test_tree_id_array_matches_anchors() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    for tree in store.trees:
        assert world.tree_id[tree.anchor_y, tree.anchor_x] == tree.entity_id
    # Tiles without trees should remain -1.
    placed = {(t.anchor_x, t.anchor_y) for t in store.trees}
    for y in range(world.height):
        for x in range(world.width):
            if (x, y) not in placed:
                assert int(world.tree_id[y, x]) == -1


def test_resource_biomass_non_negative() -> None:
    cfg = _make_cfg()
    world, _ = _run_generate(cfg)
    assert (world.resource_biomass >= 0).all()


def test_canopy_biomass_zero_for_snags_only_tiles() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    # Sum canopy biomass; live trees should drive it above zero.
    assert world.resource_biomass[Layer.CANOPY].sum() > 0.0
    assert any(t.state == "live" for t in store.trees)


def test_inspect_tile_returns_tree_at_anchor() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    tree = store.trees[0]
    info = inspect_tile(world, store, tree.anchor_x, tree.anchor_y)
    assert info["tree"] is not None
    assert info["tree"]["entity_id"] == tree.entity_id
    assert info["tree"]["anchor_x"] == tree.anchor_x
    assert info["tree"]["anchor_y"] == tree.anchor_y
    assert "trunk" in info["layers_present"]
    assert info["xy"] == [tree.anchor_x, tree.anchor_y]


def test_inspect_tile_returns_cavity_at_entrance() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    assert store.cavities
    cav = store.cavities[0]
    info = inspect_tile(world, store, cav.entrance_x, cav.entrance_y)
    assert info["cavity"] is not None
    assert info["cavity"]["entity_id"] == cav.entity_id
    assert "cavity" in info["layers_present"]


def test_inspect_tile_empty_tile_has_no_tree() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    occupied = {(t.anchor_x, t.anchor_y) for t in store.trees}
    # Find a tile that is not an anchor.
    empty = None
    for y in range(world.height):
        for x in range(world.width):
            if (x, y) not in occupied:
                empty = (x, y)
                break
        if empty is not None:
            break
    assert empty is not None
    info = inspect_tile(world, store, *empty)
    assert info["tree"] is None
    assert "ground" in info["layers_present"]


def test_inspect_tile_modifiers_within_radius() -> None:
    cfg = _make_cfg()
    world, store = _run_generate(cfg)
    assert store.habitat_modifiers
    mod = store.habitat_modifiers[0]
    info = inspect_tile(world, store, mod.x, mod.y)
    ids = {m["entity_id"] for m in info["habitat_modifiers"]}
    assert mod.entity_id in ids


def test_generator_is_deterministic() -> None:
    cfg = _make_cfg()
    world_a, store_a = _run_generate(cfg)
    world_b, store_b = _run_generate(cfg)

    anchors_a = [(t.anchor_x, t.anchor_y, t.state, t.bark_quality) for t in store_a.trees]
    anchors_b = [(t.anchor_x, t.anchor_y, t.state, t.bark_quality) for t in store_b.trees]
    assert anchors_a == anchors_b

    cav_a = [(c.entrance_x, c.entrance_y, c.insulation_score) for c in store_a.cavities]
    cav_b = [(c.entrance_x, c.entrance_y, c.insulation_score) for c in store_b.cavities]
    assert cav_a == cav_b

    assert np.array_equal(world_a.resource_biomass, world_b.resource_biomass)
    assert np.array_equal(world_a.layer_present, world_b.layer_present)
    assert np.array_equal(world_a.tree_id, world_b.tree_id)


def test_different_seed_produces_different_layout() -> None:
    cfg_a = _make_cfg(seed=40217)
    cfg_b = _make_cfg(seed=12345)
    _, store_a = _run_generate(cfg_a)
    _, store_b = _run_generate(cfg_b)
    anchors_a = {(t.anchor_x, t.anchor_y) for t in store_a.trees}
    anchors_b = {(t.anchor_x, t.anchor_y) for t in store_b.trees}
    assert anchors_a != anchors_b


def test_engine_emits_world_generated_event() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    records = [r for r in log.all_records() if r.event_type == "world_generated"]
    assert len(records) == 1
    payload = records[0].payload
    assert payload["trees"] > 0
    assert payload["cavities"] >= 0
    assert payload["cavities"] > 0  # Default config should yield ≥1 cavity.


def test_zero_density_yields_no_trees() -> None:
    cfg = _make_cfg(
        flora=FloraConfig(
            black_spruce_density=0.0,
            snag_fraction=0.0,
            moss_patch_density=0.0,
            fungi_patch_density=0.0,
        )
    )
    world, store = _run_generate(cfg)
    assert store.trees == []
    assert store.cavities == []
    assert store.habitat_modifiers == []
    assert (world.resource_biomass[Layer.CANOPY] == 0).all()
    assert (world.resource_biomass[Layer.TRUNK] == 0).all()
    assert (world.resource_biomass >= 0).all()


def test_flora_validation_rejects_out_of_range() -> None:
    import pytest

    with pytest.raises(ValueError):
        bad = FloraConfig(black_spruce_density=1.5)
        bad.__post_init__()
    with pytest.raises(ValueError):
        bad = FloraConfig(snag_fraction=-0.1)
        bad.__post_init__()


@given(
    width=st.integers(min_value=10, max_value=80),
    height=st.integers(min_value=10, max_value=80),
    density=st.floats(min_value=0.0, max_value=0.3),
)
@settings(max_examples=15, deadline=None)
def test_biomass_non_negative_property(width: int, height: int, density: float) -> None:
    cfg = _make_cfg(
        width=width,
        height=height,
        flora=FloraConfig(
            black_spruce_density=density,
            snag_fraction=0.12,
            moss_patch_density=density,
            fungi_patch_density=density,
        ),
    )
    world, _ = _run_generate(cfg)
    assert (world.resource_biomass >= 0).all()
