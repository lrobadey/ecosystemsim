"""Movement legality, intent resolution, and metabolism for chickadee agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from numpy.random import Generator

from ecosystemsim.agents.chickadee import (
    ChickadeeAgent,
    ChickadeeIntent,
    ChickadeeState,
    ForageIntent,
    MemoryRecord,
    MoveIntent,
    RoostIntent,
    StayIntent,
)
from ecosystemsim.clock import SimClock
from ecosystemsim.entities import CavityEntity, StaticEntityStore
from ecosystemsim.events import EventLog
from ecosystemsim.world import LAYER_NAMES, NO_OCCUPANT, Layer, WorldGrid

if TYPE_CHECKING:
    from ecosystemsim.config import RunConfig


# ---------------------------------------------------------------------------
# Legal movement neighbors
# ---------------------------------------------------------------------------


def _cavity_at(store: StaticEntityStore, x: int, y: int) -> int | None:
    cav = store.cavity_at(x, y)
    if cav is None:
        return None
    if cav.occupied_by is not None:
        return None
    return cav.entity_id


def _tree_at_anchor(store: StaticEntityStore, world: WorldGrid, x: int, y: int) -> int | None:
    if not (0 <= x < world.width and 0 <= y < world.height):
        return None
    tid = int(world.tree_id[y, x])
    return tid if tid >= 0 else None


def _is_dest_empty(world: WorldGrid, x: int, y: int, layer: Layer, agent_id: int) -> bool:
    occ = int(world.occupants[layer, y, x])
    return occ in (NO_OCCUPANT, agent_id)


def _add_if_legal(
    out: list[tuple[int, int, Layer]],
    world: WorldGrid,
    x: int,
    y: int,
    layer: Layer,
    agent_id: int,
) -> None:
    if not (0 <= x < world.width and 0 <= y < world.height):
        return
    if not world.layer_present[layer, y, x]:
        return
    if not _is_dest_empty(world, x, y, layer, agent_id):
        return
    out.append((x, y, layer))


def legal_chickadee_neighbors(
    agent: ChickadeeAgent,
    world: WorldGrid,
    store: StaticEntityStore,
) -> list[tuple[int, int, Layer]]:
    """Return the legal single-step destinations available to ``agent``."""
    out: list[tuple[int, int, Layer]] = []
    ax, ay, al = agent.x, agent.y, agent.layer

    if al == Layer.GROUND:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                _add_if_legal(out, world, ax + dx, ay + dy, Layer.GROUND, agent.agent_id)
        # Ground → trunk allowed only at the tree's anchor tile.
        if _tree_at_anchor(store, world, ax, ay) is not None:
            _add_if_legal(out, world, ax, ay, Layer.TRUNK, agent.agent_id)
        # Ground → understory at same tile when understory is present.
        _add_if_legal(out, world, ax, ay, Layer.UNDERSTORY, agent.agent_id)
        # Ground → cavity is explicitly forbidden (handled by not adding it).

    elif al == Layer.UNDERSTORY:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                _add_if_legal(out, world, ax + dx, ay + dy, Layer.UNDERSTORY, agent.agent_id)
        _add_if_legal(out, world, ax, ay, Layer.GROUND, agent.agent_id)
        _add_if_legal(out, world, ax, ay, Layer.CANOPY, agent.agent_id)

    elif al == Layer.TRUNK:
        tid = _tree_at_anchor(store, world, ax, ay)
        if tid is not None:
            tree = store.get_tree(tid)
            if tree is not None:
                for cx, cy in tree.crown_tiles:
                    _add_if_legal(out, world, cx, cy, Layer.CANOPY, agent.agent_id)
        _add_if_legal(out, world, ax, ay, Layer.GROUND, agent.agent_id)
        # Trunk ↔ cavity if a cavity entrance exists here AND is empty.
        if _cavity_at(store, ax, ay) is not None:
            _add_if_legal(out, world, ax, ay, Layer.CAVITY, agent.agent_id)

    elif al == Layer.CANOPY:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                _add_if_legal(out, world, ax + dx, ay + dy, Layer.CANOPY, agent.agent_id)
        # Drop down to trunk if this tile is a tree anchor.
        if _tree_at_anchor(store, world, ax, ay) is not None:
            _add_if_legal(out, world, ax, ay, Layer.TRUNK, agent.agent_id)
        # Down into understory at same tile when present.
        _add_if_legal(out, world, ax, ay, Layer.UNDERSTORY, agent.agent_id)

    elif al == Layer.CAVITY:
        _add_if_legal(out, world, ax, ay, Layer.TRUNK, agent.agent_id)

    return out


# ---------------------------------------------------------------------------
# Intent resolver
# ---------------------------------------------------------------------------


def _clear_cavity(store: StaticEntityStore, cavity_id: int) -> None:
    for cav in store.cavities:
        if cav.entity_id == cavity_id:
            cav.occupied_by = None
            return


def _emit_move(
    log: EventLog,
    tick: int,
    agent: ChickadeeAgent,
    from_xy: tuple[int, int],
    from_layer: Layer,
    delta_energy: float,
) -> None:
    log.emit(
        tick,
        "chickadee_moved",
        actor_id=agent.agent_id,
        x=agent.x,
        y=agent.y,
        layer=LAYER_NAMES[agent.layer],
        payload={
            "from": [from_xy[0], from_xy[1], LAYER_NAMES[from_layer]],
            "delta_energy": delta_energy,
            "energy_kj": agent.energy_kj,
        },
    )


def _resolve_move(
    agent: ChickadeeAgent,
    intent: MoveIntent,
    world: WorldGrid,
    store: StaticEntityStore,
    log: EventLog,
    tick: int,
    cfg: RunConfig,
) -> None:
    dest = (intent.to_x, intent.to_y, intent.to_layer)
    if dest not in legal_chickadee_neighbors(agent, world, store):
        return
    from_xy = (agent.x, agent.y)
    from_layer = agent.layer

    # If we were inside a cavity, vacate it and clear the ROOSTING state.
    if from_layer == Layer.CAVITY and agent.cavity_id is not None:
        _clear_cavity(store, agent.cavity_id)
        agent.cavity_id = None
        if agent.state == ChickadeeState.ROOSTING:
            agent.state = ChickadeeState.WARMUP
        log.emit(
            tick,
            "chickadee_left_cavity",
            actor_id=agent.agent_id,
            x=from_xy[0],
            y=from_xy[1],
            layer=LAYER_NAMES[from_layer],
            payload={"energy_kj": agent.energy_kj},
        )

    world.clear_occupant(from_layer, from_xy[1], from_xy[0])
    world.set_occupant(intent.to_layer, intent.to_y, intent.to_x, agent.agent_id)
    agent.x = intent.to_x
    agent.y = intent.to_y
    agent.layer = intent.to_layer

    move_cost = cfg.fauna.chickadees.move_cost_kj
    agent.energy_kj -= move_cost
    if agent.state not in (ChickadeeState.ROOSTING, ChickadeeState.PRE_ROOST, ChickadeeState.DEAD):
        agent.state = ChickadeeState.FORAGE

    _emit_move(log, tick, agent, from_xy, from_layer, -move_cost)


def _resolve_forage(
    agent: ChickadeeAgent,
    world: WorldGrid,
    log: EventLog,
    tick: int,
    cfg: RunConfig,
) -> None:
    params = cfg.fauna.chickadees
    biomass = float(world.resource_biomass[agent.layer, agent.y, agent.x])
    if biomass <= 0.0:
        return
    bite = min(params.forage_bite_max_biomass, biomass)
    gain = bite * params.forage_yield_kj_per_biomass
    before = agent.energy_kj
    agent.energy_kj = min(agent.energy_kj + gain, params.max_energy_kj)
    actual_gain = agent.energy_kj - before
    new_biomass = max(0.0, biomass - bite)
    world.resource_biomass[agent.layer, agent.y, agent.x] = new_biomass
    if agent.state not in (ChickadeeState.ROOSTING, ChickadeeState.PRE_ROOST, ChickadeeState.DEAD):
        agent.state = ChickadeeState.FORAGE
    _update_forage_memory(agent, actual_gain, cfg)
    log.emit(
        tick,
        "chickadee_foraged",
        actor_id=agent.agent_id,
        x=agent.x,
        y=agent.y,
        layer=LAYER_NAMES[agent.layer],
        payload={
            "before": before,
            "after": agent.energy_kj,
            "delta_energy": actual_gain,
            "biomass_consumed": bite,
        },
    )


def _resolve_roost(
    agent: ChickadeeAgent,
    intent: RoostIntent,
    world: WorldGrid,
    store: StaticEntityStore,
    log: EventLog,
    tick: int,
    cfg: RunConfig,
) -> None:
    cav = None
    for c in store.cavities:
        if c.entity_id == intent.cavity_id:
            cav = c
            break
    if cav is None:
        return
    if cav.occupied_by is not None and cav.occupied_by != agent.agent_id:
        return
    if agent.layer != Layer.TRUNK or agent.x != cav.entrance_x or agent.y != cav.entrance_y:
        return
    if not world.layer_present[Layer.CAVITY, cav.entrance_y, cav.entrance_x]:
        return
    if int(world.occupants[Layer.CAVITY, cav.entrance_y, cav.entrance_x]) not in (
        NO_OCCUPANT,
        agent.agent_id,
    ):
        return

    world.clear_occupant(Layer.TRUNK, agent.y, agent.x)
    world.set_occupant(Layer.CAVITY, cav.entrance_y, cav.entrance_x, agent.agent_id)
    agent.layer = Layer.CAVITY
    cav.occupied_by = agent.agent_id
    agent.cavity_id = cav.entity_id
    agent.state = ChickadeeState.ROOSTING
    _update_roost_memory(agent, cav, cfg)

    log.emit(
        tick,
        "chickadee_roosted",
        actor_id=agent.agent_id,
        x=agent.x,
        y=agent.y,
        layer=LAYER_NAMES[Layer.CAVITY],
        payload={
            "cavity_id": cav.entity_id,
            "insulation_score": cav.insulation_score,
            "energy_kj": agent.energy_kj,
        },
    )


def resolve_chickadee_intents(
    intents: list[tuple[ChickadeeAgent, ChickadeeIntent]],
    world: WorldGrid,
    store: StaticEntityStore,
    log: EventLog,
    tick: int,
    rng: Generator,
    cfg: RunConfig,
) -> None:
    """Apply ``intents`` to the world in deterministic ``agent_id`` order."""
    del rng  # reserved for future stochastic conflict resolution
    ordered = sorted(intents, key=lambda pair: pair[0].agent_id)
    for agent, intent in ordered:
        if not agent.alive:
            continue
        if isinstance(intent, StayIntent):
            continue
        if isinstance(intent, MoveIntent):
            _resolve_move(agent, intent, world, store, log, tick, cfg)
        elif isinstance(intent, ForageIntent):
            _resolve_forage(agent, world, log, tick, cfg)
        elif isinstance(intent, RoostIntent):
            _resolve_roost(agent, intent, world, store, log, tick, cfg)


# ---------------------------------------------------------------------------
# Metabolism
# ---------------------------------------------------------------------------


def _on_live_tree(store: StaticEntityStore, world: WorldGrid, x: int, y: int) -> bool:
    tid = int(world.tree_id[y, x])
    if tid >= 0:
        tree = store.get_tree(tid)
        if tree is not None and tree.state == "live":
            return True
    return any(tree.state == "live" and (x, y) in tree.crown_tiles for tree in store.trees)


def apply_chickadee_metabolism(
    agents: list[ChickadeeAgent],
    world: WorldGrid,
    store: StaticEntityStore,
    clock: SimClock,
    cfg: RunConfig,
    log: EventLog,
) -> None:
    """Drain energy for each alive agent and starve those that hit the threshold."""
    params = cfg.fauna.chickadees
    base = params.daytime_metabolism_kj_per_tick
    for agent in agents:
        if not agent.alive:
            continue
        if agent.layer == Layer.CAVITY:
            drain = base * params.cavity_metabolism_multiplier
        elif agent.layer in (Layer.CANOPY, Layer.UNDERSTORY) and _on_live_tree(
            store, world, agent.x, agent.y
        ):
            drain = base * params.crown_metabolism_multiplier
        else:
            drain = base
        before = agent.energy_kj
        agent.energy_kj -= drain
        if agent.energy_kj <= params.starvation_threshold_kj:
            after = agent.energy_kj
            agent.alive = False
            agent.state = ChickadeeState.DEAD
            world.clear_occupant(agent.layer, agent.y, agent.x)
            if agent.cavity_id is not None:
                _clear_cavity(store, agent.cavity_id)
                agent.cavity_id = None
            log.emit(
                clock.current_tick,
                "chickadee_starved",
                actor_id=agent.agent_id,
                x=agent.x,
                y=agent.y,
                layer=LAYER_NAMES[agent.layer],
                payload={"before": before, "after": after},
            )


# ---------------------------------------------------------------------------
# Memory updates (called from resolver helpers above)
# ---------------------------------------------------------------------------


def _update_forage_memory(agent: ChickadeeAgent, actual_gain: float, cfg: RunConfig) -> None:
    if actual_gain <= 0.0:
        return
    capacity = cfg.fauna.chickadees.memory_capacity
    for rec in agent.memory:
        if (
            rec.kind == "profitable"
            and rec.x == agent.x
            and rec.y == agent.y
            and rec.layer == agent.layer
        ):
            rec.value = max(rec.value, actual_gain)
            rec.age_ticks = 0
            return
    agent.memory.append(
        MemoryRecord(
            kind="profitable",
            x=agent.x,
            y=agent.y,
            layer=agent.layer,
            value=actual_gain,
            age_ticks=0,
        )
    )
    if len(agent.memory) > capacity:
        agent.memory.sort(key=lambda r: r.age_ticks, reverse=True)
        del agent.memory[capacity:]


def _update_roost_memory(agent: ChickadeeAgent, cav: CavityEntity, cfg: RunConfig) -> None:
    capacity = cfg.fauna.chickadees.memory_capacity
    for rec in agent.memory:
        if rec.kind == "roost" and rec.x == cav.entrance_x and rec.y == cav.entrance_y:
            rec.value = cav.insulation_score
            rec.age_ticks = 0
            return
    agent.memory.append(
        MemoryRecord(
            kind="roost",
            x=cav.entrance_x,
            y=cav.entrance_y,
            layer=Layer.CAVITY,
            value=cav.insulation_score,
            age_ticks=0,
        )
    )
    if len(agent.memory) > capacity:
        agent.memory.sort(key=lambda r: r.age_ticks, reverse=True)
        del agent.memory[capacity:]


# ---------------------------------------------------------------------------
# Post-resolve behavioral state sync
# ---------------------------------------------------------------------------


def update_chickadee_behavioral_states(
    agents: list[ChickadeeAgent],
    clock: SimClock,
) -> None:
    """Sync agent.state with structural position after each tick's resolution.

    Keeps the decide/resolve boundary clean: decide returns intents only;
    state transitions are inferred here from position and clock phase.
    """
    for agent in agents:
        if not agent.alive:
            continue
        if agent.layer == Layer.CAVITY:
            agent.state = ChickadeeState.ROOSTING
        elif clock.dusk_pressure > 0.7:
            agent.state = ChickadeeState.PRE_ROOST
        # FORAGE and WARMUP are set by the resolver and remain until next transition.


# ---------------------------------------------------------------------------
# Per-tick memory aging and capacity cap
# ---------------------------------------------------------------------------


def age_chickadee_memories(agents: list[ChickadeeAgent], cfg: RunConfig) -> None:
    """Increment age_ticks on all memory records and evict oldest above capacity."""
    capacity = cfg.fauna.chickadees.memory_capacity
    for agent in agents:
        for rec in agent.memory:
            rec.age_ticks += 1
        if len(agent.memory) > capacity:
            agent.memory.sort(key=lambda r: r.age_ticks, reverse=True)
            del agent.memory[capacity:]


__all__ = [
    "age_chickadee_memories",
    "apply_chickadee_metabolism",
    "legal_chickadee_neighbors",
    "resolve_chickadee_intents",
    "update_chickadee_behavioral_states",
]
