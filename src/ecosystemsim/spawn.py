"""Initial agent placement on a freshly generated world."""

from __future__ import annotations

import numpy as np
from numpy.random import Generator

from ecosystemsim.agents.chickadee import AgentStore, ChickadeeAgent, ChickadeeState
from ecosystemsim.config import RunConfig
from ecosystemsim.entities import StaticEntityStore
from ecosystemsim.world import NO_OCCUPANT, Layer, WorldGrid


def _shuffled(items: list[tuple[int, ...]], rng: Generator) -> list[tuple[int, ...]]:
    if not items:
        return items
    perm = np.arange(len(items), dtype=np.int64)
    rng.shuffle(perm)
    return [items[int(i)] for i in perm.tolist()]


def _free_cavity_pool(store: StaticEntityStore) -> list[tuple[int, ...]]:
    out: list[tuple[int, ...]] = []
    for cav in store.cavities:
        if cav.occupied_by is None:
            out.append((cav.entrance_x, cav.entrance_y, cav.entity_id))
    return out


def _free_canopy_pool(world: WorldGrid, store: StaticEntityStore) -> list[tuple[int, ...]]:
    live_crowns: set[tuple[int, int]] = set()
    for tree in store.trees:
        if tree.state == "live":
            for cx, cy in tree.crown_tiles:
                live_crowns.add((cx, cy))
    out: list[tuple[int, ...]] = []
    for x, y in sorted(live_crowns):
        if not world.layer_present[Layer.CANOPY, y, x]:
            continue
        if int(world.occupants[Layer.CANOPY, y, x]) != NO_OCCUPANT:
            continue
        out.append((x, y))
    return out


def _free_ground_pool(world: WorldGrid) -> list[tuple[int, ...]]:
    out: list[tuple[int, ...]] = []
    for y in range(world.height):
        for x in range(world.width):
            if int(world.occupants[Layer.GROUND, y, x]) == NO_OCCUPANT:
                out.append((x, y))
    return out


def spawn_chickadees(
    cfg: RunConfig,
    world: WorldGrid,
    store: StaticEntityStore,
    rng: Generator,
) -> AgentStore:
    """Place ``cfg.fauna.chickadees.count`` chickadees on the world.

    Spawn rules:

    - Prefer empty cavities (state=ROOSTING). Each cavity holds at most one bird.
    - Otherwise place on a live black-spruce canopy tile (state=WARMUP).
    - Fall back to a random GROUND tile (state=FORAGE) when no canopy tile is
      available. Ground spawn lets the zero-density test fixture still run.
    """
    params = cfg.fauna.chickadees
    agents = AgentStore()

    cavity_pool = _shuffled(_free_cavity_pool(store), rng)
    canopy_pool = _shuffled(_free_canopy_pool(world, store), rng)
    ground_pool: list[tuple[int, ...]] | None = None

    for _ in range(params.count):
        placed = False

        while cavity_pool:
            cx, cy, cav_id = cavity_pool.pop()
            if int(world.occupants[Layer.CAVITY, cy, cx]) != NO_OCCUPANT:
                continue
            agent_id = agents.next_agent_id
            agent = ChickadeeAgent(
                agent_id=agent_id,
                x=cx,
                y=cy,
                layer=Layer.CAVITY,
                energy_kj=params.start_energy_kj,
                state=ChickadeeState.ROOSTING,
                cavity_id=cav_id,
            )
            world.set_occupant(Layer.CAVITY, cy, cx, agent_id)
            for cav in store.cavities:
                if cav.entity_id == cav_id:
                    cav.occupied_by = agent_id
                    break
            agents.add_chickadee(agent)
            placed = True
            break

        if placed:
            continue

        while canopy_pool:
            cx, cy = canopy_pool.pop()
            if int(world.occupants[Layer.CANOPY, cy, cx]) != NO_OCCUPANT:
                continue
            agent_id = agents.next_agent_id
            agent = ChickadeeAgent(
                agent_id=agent_id,
                x=cx,
                y=cy,
                layer=Layer.CANOPY,
                energy_kj=params.start_energy_kj,
                state=ChickadeeState.WARMUP,
                cavity_id=None,
            )
            world.set_occupant(Layer.CANOPY, cy, cx, agent_id)
            agents.add_chickadee(agent)
            placed = True
            break

        if placed:
            continue

        if ground_pool is None:
            ground_pool = _shuffled(_free_ground_pool(world), rng)
        while ground_pool:
            gx, gy = ground_pool.pop()
            if int(world.occupants[Layer.GROUND, gy, gx]) != NO_OCCUPANT:
                continue
            agent_id = agents.next_agent_id
            agent = ChickadeeAgent(
                agent_id=agent_id,
                x=gx,
                y=gy,
                layer=Layer.GROUND,
                energy_kj=params.start_energy_kj,
                state=ChickadeeState.FORAGE,
                cavity_id=None,
            )
            world.set_occupant(Layer.GROUND, gy, gx, agent_id)
            agents.add_chickadee(agent)
            placed = True
            break

        if not placed:
            raise ValueError(f"not enough spawn tiles for fauna.chickadees.count={params.count}")

    return agents
