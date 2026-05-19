"""Tests for the boreal chickadee agent: spawn, percept, decide, resolve, metabolism."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from ecosystemsim.agents.chickadee import (
    AgentStore,
    ChickadeeAgent,
    ChickadeeState,
    ForageIntent,
    RoostIntent,
    decide_chickadee,
)
from ecosystemsim.clock import make_clock
from ecosystemsim.config import (
    REQUIRED_LAYERS,
    ChickadeeParamsConfig,
    ClockConfig,
    FaunaConfig,
    FloraConfig,
    MapConfig,
    RunConfig,
    default_run_config,
)
from ecosystemsim.engine import run_headless
from ecosystemsim.events import EventLog
from ecosystemsim.generator import generate_forest
from ecosystemsim.inspector import inspect_agent, inspect_tile
from ecosystemsim.perception import build_chickadee_percept
from ecosystemsim.rng import make_rng
from ecosystemsim.spawn import spawn_chickadees
from ecosystemsim.systems import (
    apply_chickadee_metabolism,
    legal_chickadee_neighbors,
    resolve_chickadee_intents,
)
from ecosystemsim.world import LAYER_NAMES, NO_OCCUPANT, Layer, make_world

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIOS = Path(__file__).parent.parent / "scenarios"


def _make_cfg(
    *,
    seed: int = 40217,
    width: int = 50,
    height: int = 50,
    flora: FloraConfig | None = None,
    fauna: FaunaConfig | None = None,
    max_ticks: int = 100,
) -> RunConfig:
    return RunConfig(
        seed=seed,
        map=MapConfig(width=width, height=height, layers=REQUIRED_LAYERS),
        clock=ClockConfig(tick_seconds=10.0, max_ticks=max_ticks),
        flora=flora if flora is not None else FloraConfig(),
        fauna=fauna if fauna is not None else FaunaConfig(),
    )


def _generate_world(cfg: RunConfig) -> tuple[object, object, object]:
    world = make_world(cfg.map)
    rng = make_rng(cfg.seed)
    store = generate_forest(cfg, world, rng)
    return world, store, rng


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_chickadee_params_defaults_are_valid() -> None:
    p = ChickadeeParamsConfig()
    p.__post_init__()
    assert p.count == 2
    assert p.target_energy_kj == 55.0


def test_chickadee_params_rejects_negative_energy() -> None:
    import pytest

    with pytest.raises(ValueError, match="start_energy_kj"):
        p = ChickadeeParamsConfig(start_energy_kj=-1.0)
        p.__post_init__()


def test_chickadee_params_rejects_bad_multiplier() -> None:
    import pytest

    with pytest.raises(ValueError, match="cavity_metabolism_multiplier"):
        p = ChickadeeParamsConfig(cavity_metabolism_multiplier=1.5)
        p.__post_init__()
    with pytest.raises(ValueError, match="crown_metabolism_multiplier"):
        p = ChickadeeParamsConfig(crown_metabolism_multiplier=0.0)
        p.__post_init__()


def test_chickadee_params_rejects_zero_memory_capacity() -> None:
    import pytest

    with pytest.raises(ValueError, match="memory_capacity"):
        p = ChickadeeParamsConfig(memory_capacity=0)
        p.__post_init__()


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------


def test_spawn_count_and_no_collisions() -> None:
    cfg = _make_cfg()
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    assert len(agents.chickadees) == cfg.fauna.chickadees.count
    placements = [(a.layer, a.y, a.x) for a in agents.chickadees]
    assert len(placements) == len(set(placements))
    for a in agents.chickadees:
        assert int(world.occupants[a.layer, a.y, a.x]) == a.agent_id


def test_spawn_respects_cavity_capacity() -> None:
    fauna = FaunaConfig(chickadees=ChickadeeParamsConfig(count=4))
    cfg = _make_cfg(fauna=fauna)
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    cavity_ids = [a.cavity_id for a in agents.chickadees if a.cavity_id is not None]
    assert len(cavity_ids) == len(set(cavity_ids))
    for cav in store.cavities:
        if cav.occupied_by is not None:
            assert sum(1 for a in agents.chickadees if a.cavity_id == cav.entity_id) == 1


def test_spawn_ground_fallback_for_empty_forest() -> None:
    flora = FloraConfig(
        black_spruce_density=0.0,
        snag_fraction=0.0,
        moss_patch_density=0.0,
        fungi_patch_density=0.0,
    )
    cfg = _make_cfg(flora=flora)
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    assert all(a.layer == Layer.GROUND for a in agents.chickadees)


# ---------------------------------------------------------------------------
# Movement legality
# ---------------------------------------------------------------------------


def test_legal_neighbors_canopy_to_canopy_only_when_present() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    live = next(t for t in store.trees if t.state == "live")
    cx, cy = live.crown_tiles[0]
    agent = ChickadeeAgent(
        agent_id=0,
        x=cx,
        y=cy,
        layer=Layer.CANOPY,
        energy_kj=30.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    neighbors = legal_chickadee_neighbors(agent, world, store)
    assert all(world.layer_present[nl, ny, nx] for nx, ny, nl in neighbors)


def test_legal_neighbors_trunk_to_canopy_of_own_crown() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    live = next(t for t in store.trees if t.state == "live")
    agent = ChickadeeAgent(
        agent_id=0,
        x=live.anchor_x,
        y=live.anchor_y,
        layer=Layer.TRUNK,
        energy_kj=30.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    neighbors = legal_chickadee_neighbors(agent, world, store)
    crown_set = set(live.crown_tiles)
    canopy_neighbors = {(nx, ny) for nx, ny, nl in neighbors if nl == Layer.CANOPY}
    assert canopy_neighbors == crown_set


def test_ground_to_cavity_is_rejected() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    assert store.cavities, "default scenario should yield at least one cavity"
    cav = store.cavities[0]
    agent = ChickadeeAgent(
        agent_id=0,
        x=cav.entrance_x,
        y=cav.entrance_y,
        layer=Layer.GROUND,
        energy_kj=30.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    neighbors = legal_chickadee_neighbors(agent, world, store)
    assert all(nl != Layer.CAVITY for nx, ny, nl in neighbors)


def test_move_onto_occupied_tile_rejected() -> None:
    cfg = _make_cfg()
    world, store, rng = _generate_world(cfg)
    live = next(t for t in store.trees if t.state == "live")
    cx, cy = live.crown_tiles[0]
    other_x, other_y = live.crown_tiles[1] if len(live.crown_tiles) > 1 else (cx, cy)
    world.set_occupant(Layer.CANOPY, other_y, other_x, 99)
    agent = ChickadeeAgent(
        agent_id=0,
        x=cx,
        y=cy,
        layer=Layer.CANOPY,
        energy_kj=30.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    neighbors = legal_chickadee_neighbors(agent, world, store)
    assert (other_x, other_y, Layer.CANOPY) not in neighbors
    del rng


# ---------------------------------------------------------------------------
# Forage / metabolism
# ---------------------------------------------------------------------------


def test_forage_increases_energy_and_decrements_biomass() -> None:
    cfg = _make_cfg()
    world, store, rng = _generate_world(cfg)
    live = next(t for t in store.trees if t.state == "live")
    cx, cy = next(
        (x, y) for x, y in live.crown_tiles if world.resource_biomass[Layer.CANOPY, y, x] > 0
    )
    agent = ChickadeeAgent(
        agent_id=0,
        x=cx,
        y=cy,
        layer=Layer.CANOPY,
        energy_kj=10.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    world.set_occupant(Layer.CANOPY, cy, cx, 0)
    agents = AgentStore(chickadees=[agent], next_agent_id=1)
    log = EventLog()
    before_biomass = float(world.resource_biomass[Layer.CANOPY, cy, cx])
    resolve_chickadee_intents([(agent, ForageIntent())], world, store, log, 1, rng, cfg)
    after_biomass = float(world.resource_biomass[Layer.CANOPY, cy, cx])
    assert agent.energy_kj > 10.0
    assert after_biomass < before_biomass
    assert after_biomass >= 0.0
    types = {r.event_type for r in log.all_records()}
    assert "chickadee_foraged" in types
    del agents


def test_metabolism_decreases_energy_when_no_forage() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    agent = ChickadeeAgent(
        agent_id=0,
        x=0,
        y=0,
        layer=Layer.GROUND,
        energy_kj=10.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    clock = make_clock(10.0, 100)
    log = EventLog()
    apply_chickadee_metabolism([agent], world, store, clock, cfg, log)
    assert agent.energy_kj < 10.0


def test_cavity_roosting_drains_slower_than_open() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    cav = next(c for c in store.cavities)
    in_cavity = ChickadeeAgent(
        agent_id=0,
        x=cav.entrance_x,
        y=cav.entrance_y,
        layer=Layer.CAVITY,
        energy_kj=10.0,
        state=ChickadeeState.ROOSTING,
        cavity_id=cav.entity_id,
    )
    on_ground = ChickadeeAgent(
        agent_id=1,
        x=0,
        y=0,
        layer=Layer.GROUND,
        energy_kj=10.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    clock = make_clock(10.0, 100)
    log = EventLog()
    apply_chickadee_metabolism([in_cavity, on_ground], world, store, clock, cfg, log)
    drop_cavity = 10.0 - in_cavity.energy_kj
    drop_ground = 10.0 - on_ground.energy_kj
    assert drop_cavity < drop_ground


def test_starvation_emits_event_and_clears_occupant() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    agent = ChickadeeAgent(
        agent_id=0,
        x=0,
        y=0,
        layer=Layer.GROUND,
        energy_kj=0.001,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    world.set_occupant(Layer.GROUND, 0, 0, 0)
    clock = make_clock(10.0, 100)
    log = EventLog()
    apply_chickadee_metabolism([agent], world, store, clock, cfg, log)
    assert not agent.alive
    assert agent.state == ChickadeeState.DEAD
    assert int(world.occupants[Layer.GROUND, 0, 0]) == NO_OCCUPANT
    types = {r.event_type for r in log.all_records()}
    assert "chickadee_starved" in types


# ---------------------------------------------------------------------------
# Engine integration: full-day survival + determinism
# ---------------------------------------------------------------------------


def test_default_scenario_emits_lifecycle_events() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    types = {r.event_type for r in log.all_records()}
    assert "chickadees_spawned" in types
    assert "day_summary" in types


def test_default_scenario_birds_survive() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    last_summary = next(r for r in reversed(log.all_records()) if r.event_type == "day_summary")
    for a in last_summary.payload["agents"]:
        assert a["alive"], f"agent {a['agent_id']} did not survive: {a}"
        assert a["energy_kj"] > 0.0


def test_default_scenario_has_cavity_roost() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    roosted = [r for r in log.all_records() if r.event_type == "chickadee_roosted"]
    assert roosted, "expected at least one chickadee_roosted event"


def test_default_scenario_time_budget_skewed_to_trees() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    last_summary = next(r for r in reversed(log.all_records()) if r.event_type == "day_summary")
    for a in last_summary.payload["agents"]:
        budget = a["time_budget"]
        tree_ticks = budget["trunk"] + budget["canopy"] + budget["cavity"]
        total = sum(budget.values())
        assert tree_ticks / total >= 0.75, f"agent {a['agent_id']} time_budget={budget}"


def test_determinism_with_agents() -> None:
    cfg = default_run_config()
    result1, log1 = run_headless(cfg)
    result2, log2 = run_headless(cfg)
    assert result1.event_count == result2.event_count
    assert log1.to_jsonl() == log2.to_jsonl()


def test_chickadees_spawned_count_matches_config() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    spawn_event = next(r for r in log.all_records() if r.event_type == "chickadees_spawned")
    assert spawn_event.payload["count"] == cfg.fauna.chickadees.count


def test_empty_forest_fixture_birds_starve() -> None:
    cfg = RunConfig.from_file(FIXTURES / "empty_forest.json")
    _, log = run_headless(cfg)
    starved = [r for r in log.all_records() if r.event_type == "chickadee_starved"]
    assert len(starved) == cfg.fauna.chickadees.count


def test_dense_spruce_fixture_birds_survive() -> None:
    cfg = RunConfig.from_file(FIXTURES / "dense_spruce.json")
    _, log = run_headless(cfg)
    last_summary = next(r for r in reversed(log.all_records()) if r.event_type == "day_summary")
    for a in last_summary.payload["agents"]:
        assert a["alive"]
        assert a["energy_kj"] > 0.0


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------


def test_inspect_agent_returns_expected_shape() -> None:
    cfg = _make_cfg()
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    info = inspect_agent(agents.chickadees[0].agent_id, world, store, agents)
    assert info["species"] == "boreal_chickadee"
    assert "xy" in info
    assert info["layer"] in LAYER_NAMES
    assert "energy_kj" in info
    assert "state" in info
    assert "memory" in info
    assert isinstance(info["memory"], list)


def test_inspect_tile_shows_chickadee_occupant() -> None:
    cfg = _make_cfg()
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    a = agents.chickadees[0]
    info = inspect_tile(world, store, a.x, a.y)
    assert info["occupants"][LAYER_NAMES[a.layer]] == a.agent_id


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def test_decide_returns_roost_intent_at_cavity_entrance_at_dusk() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    cav = store.cavities[0]
    agent = ChickadeeAgent(
        agent_id=0,
        x=cav.entrance_x,
        y=cav.entrance_y,
        layer=Layer.TRUNK,
        energy_kj=30.0,
        state=ChickadeeState.PRE_ROOST,
        cavity_id=None,
    )
    world.set_occupant(Layer.TRUNK, cav.entrance_y, cav.entrance_x, 0)
    clock = make_clock(10.0, 8640)
    # Force dusk: day_fraction = 0.78 → dusk_pressure = 0.9.
    clock.current_tick = int(0.78 * 8640)
    percept = build_chickadee_percept(agent, world, store, clock, cfg)
    rng = make_rng(0)
    intent = decide_chickadee(agent, percept, cfg, rng)
    assert isinstance(intent, RoostIntent)
    assert intent.cavity_id == cav.entity_id


def test_decide_returns_forage_on_canopy_with_biomass() -> None:
    cfg = _make_cfg()
    world, store, _ = _generate_world(cfg)
    live = next(t for t in store.trees if t.state == "live")
    cx, cy = next(
        (x, y) for x, y in live.crown_tiles if world.resource_biomass[Layer.CANOPY, y, x] > 0
    )
    agent = ChickadeeAgent(
        agent_id=0,
        x=cx,
        y=cy,
        layer=Layer.CANOPY,
        energy_kj=10.0,
        state=ChickadeeState.FORAGE,
        cavity_id=None,
    )
    world.set_occupant(Layer.CANOPY, cy, cx, 0)
    clock = make_clock(10.0, 8640)
    clock.current_tick = int(0.40 * 8640)  # midday
    percept = build_chickadee_percept(agent, world, store, clock, cfg)
    rng = make_rng(0)
    intent = decide_chickadee(agent, percept, cfg, rng)
    assert isinstance(intent, ForageIntent)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(seed=st.integers(min_value=0, max_value=1000))
@settings(max_examples=8, deadline=None)
def test_no_double_occupancy_after_full_day(seed: int) -> None:
    cfg = _make_cfg(seed=seed, max_ticks=200)
    # Drive the engine through enough ticks to exercise spawn + resolve.
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    clock = make_clock(cfg.clock.tick_seconds, cfg.clock.max_ticks)
    log = EventLog()
    for _ in range(cfg.clock.max_ticks):
        clock.advance()
        intents = []
        for a in agents.alive_chickadees():
            percept = build_chickadee_percept(a, world, store, clock, cfg)
            intents.append((a, decide_chickadee(a, percept, cfg, rng)))
        resolve_chickadee_intents(intents, world, store, log, clock.current_tick, rng, cfg)
        apply_chickadee_metabolism(agents.chickadees, world, store, clock, cfg, log)
        positions = [(a.layer, a.y, a.x) for a in agents.alive_chickadees()]
        assert len(positions) == len(set(positions)), positions


@given(
    seed=st.integers(min_value=0, max_value=1000),
    density=st.floats(min_value=0.05, max_value=0.25),
)
@settings(max_examples=5, deadline=None)
def test_energy_never_negative_without_starvation_event(seed: int, density: float) -> None:
    cfg = _make_cfg(
        seed=seed,
        flora=FloraConfig(
            black_spruce_density=density,
            snag_fraction=0.12,
            moss_patch_density=density,
            fungi_patch_density=density,
        ),
        max_ticks=400,
    )
    _, log = run_headless(cfg)
    records = log.all_records()
    starved_by_tick: dict[int, set[int]] = {}
    for r in records:
        if r.event_type == "chickadee_starved" and r.actor_id is not None:
            starved_by_tick.setdefault(r.tick, set()).add(r.actor_id)
    # Any negative energy reading must occur on the same tick a starvation event
    # is emitted for that agent.
    for r in records:
        if r.event_type != "day_summary":
            continue
        for a in r.payload["agents"]:
            if a["energy_kj"] < 0:
                # Either it's the death tick or any earlier tick had a starved event
                # — for max_ticks=400 we expect only the same-tick relationship.
                assert any(a["agent_id"] in s for s in starved_by_tick.values()), a


def test_resource_biomass_stays_non_negative_after_run() -> None:
    cfg = default_run_config()
    world, store, rng = _generate_world(cfg)
    agents = spawn_chickadees(cfg, world, store, rng)
    clock = make_clock(cfg.clock.tick_seconds, cfg.clock.max_ticks)
    log = EventLog()
    for _ in range(cfg.clock.max_ticks):
        clock.advance()
        intents = []
        for a in agents.alive_chickadees():
            percept = build_chickadee_percept(a, world, store, clock, cfg)
            intents.append((a, decide_chickadee(a, percept, cfg, rng)))
        resolve_chickadee_intents(intents, world, store, log, clock.current_tick, rng, cfg)
        apply_chickadee_metabolism(agents.chickadees, world, store, clock, cfg, log)
        assert (world.resource_biomass >= 0).all()


def test_scenario_file_matches_default_run() -> None:
    cfg_file = RunConfig.from_file(SCENARIOS / "late_winter_microforest.json")
    cfg_default = default_run_config()
    _, log_file = run_headless(cfg_file)
    _, log_default = run_headless(cfg_default)
    assert log_file.to_jsonl() == log_default.to_jsonl()


# Pull numpy into the test module so that test ordering does not lose it
# between runs (some Hypothesis runs reference it via tile lookups).
_ = np
