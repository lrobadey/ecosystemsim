"""Percept builders for chickadee agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ecosystemsim.entities import StaticEntityStore
from ecosystemsim.systems import legal_chickadee_neighbors
from ecosystemsim.world import NO_OCCUPANT, Layer, WorldGrid

if TYPE_CHECKING:
    from ecosystemsim.agents.chickadee import ChickadeeAgent
    from ecosystemsim.clock import SimClock
    from ecosystemsim.config import RunConfig


_MAX_FORAGE_CANDIDATES = 6


@dataclass(frozen=True)
class ForageCandidate:
    x: int
    y: int
    layer: Layer
    expected_biomass: float
    travel_cost: float
    leads_to_black_spruce: bool


@dataclass(frozen=True)
class RoostCandidate:
    x: int
    y: int
    cavity_id: int | None  # None → dense-crown fallback
    insulation_score: float
    is_known: bool


@dataclass(frozen=True)
class ChickadeePercept:
    agent_id: int
    here: ForageCandidate
    forage: tuple[ForageCandidate, ...]
    cavity_roost: RoostCandidate | None
    crown_roost: RoostCandidate | None
    dusk_pressure: float
    is_daytime: bool
    neighbors: tuple[tuple[int, int, Layer], ...]
    # Nearest tree anchor whose crown contains the agent's tile — gives the
    # chickadee a descent path (canopy → anchor → trunk → ground) when the
    # local biomass is depleted.
    descent_anchor: tuple[int, int] | None
    # Global beacon: the nearest tree-layer tile with biomass on the entire
    # map. Lets a stranded bird walk toward food even when the perception
    # radius is empty.
    food_beacon: tuple[int, int, Layer] | None


def _tile_leads_to_black_spruce(store: StaticEntityStore, x: int, y: int) -> bool:
    """True when the tile sits on a live black-spruce trunk or crown."""
    return (x, y) in store.black_spruce_tiles


def _here_candidate(
    agent: ChickadeeAgent,
    world: WorldGrid,
    store: StaticEntityStore,
) -> ForageCandidate:
    biomass = float(world.resource_biomass[agent.layer, agent.y, agent.x])
    return ForageCandidate(
        x=agent.x,
        y=agent.y,
        layer=agent.layer,
        expected_biomass=biomass,
        travel_cost=0.0,
        leads_to_black_spruce=_tile_leads_to_black_spruce(store, agent.x, agent.y),
    )


def build_chickadee_percept(
    agent: ChickadeeAgent,
    world: WorldGrid,
    store: StaticEntityStore,
    clock: SimClock,
    cfg: RunConfig,
) -> ChickadeePercept:
    """Build a percept for ``agent`` based on the current world state."""
    radius = cfg.fauna.chickadees.perception_radius
    here = _here_candidate(agent, world, store)
    neighbors = tuple(legal_chickadee_neighbors(agent, world, store))

    # Scan a Chebyshev neighborhood for forage candidates.
    forage: list[ForageCandidate] = []
    x0 = max(0, agent.x - radius)
    x1 = min(world.width, agent.x + radius + 1)
    y0 = max(0, agent.y - radius)
    y1 = min(world.height, agent.y + radius + 1)
    for y in range(y0, y1):
        for x in range(x0, x1):
            for layer in (Layer.UNDERSTORY, Layer.TRUNK, Layer.CANOPY):
                if not world.layer_present[layer, y, x]:
                    continue
                biomass = float(world.resource_biomass[layer, y, x])
                if biomass <= 0.0:
                    continue
                if x == agent.x and y == agent.y and layer == agent.layer:
                    continue
                travel = float(max(abs(x - agent.x), abs(y - agent.y)))
                forage.append(
                    ForageCandidate(
                        x=x,
                        y=y,
                        layer=layer,
                        expected_biomass=biomass,
                        travel_cost=travel,
                        leads_to_black_spruce=_tile_leads_to_black_spruce(store, x, y),
                    )
                )

    forage.sort(key=lambda c: (-c.expected_biomass, c.travel_cost, int(c.layer), c.y, c.x))
    top_forage = tuple(forage[:_MAX_FORAGE_CANDIDATES])

    # Cavity search uses 2× the perception radius.
    cavity_roost: RoostCandidate | None = _best_cavity(agent, store, world, radius * 2)
    crown_roost: RoostCandidate | None = _best_crown_roost(agent, world, store, radius)
    descent_anchor = _descent_anchor_for(agent, store)
    has_memory_food = any(r.kind == "profitable" for r in agent.memory)
    food_beacon = (
        _global_food_beacon(agent, world, cfg.fauna.chickadees.food_beacon_radius)
        if not top_forage and not has_memory_food
        else None
    )

    return ChickadeePercept(
        agent_id=agent.agent_id,
        here=here,
        forage=top_forage,
        cavity_roost=cavity_roost,
        crown_roost=crown_roost,
        dusk_pressure=clock.dusk_pressure,
        is_daytime=clock.is_daytime,
        neighbors=neighbors,
        descent_anchor=descent_anchor,
        food_beacon=food_beacon,
    )


def _global_food_beacon(
    agent: ChickadeeAgent, world: WorldGrid, max_range: int
) -> tuple[int, int, Layer] | None:
    """Closest tree-layer tile with positive biomass within ``max_range`` tiles.

    Scaffold: stand-in for long-range visual canopy perception. Fires only when
    the local perception radius is empty and the agent has no profitable memory —
    once memory populates, birds navigate by remembered sites instead.
    """
    best: tuple[int, int, Layer] | None = None
    best_key: tuple[int, int, int, int] | None = None
    for layer in (Layer.CANOPY, Layer.TRUNK, Layer.UNDERSTORY):
        nonzero = world.resource_biomass[layer] > 0.0
        if not nonzero.any():
            continue
        ys, xs = nonzero.nonzero()
        for y, x in zip(ys.tolist(), xs.tolist(), strict=False):
            xi, yi = int(x), int(y)
            dist = max(abs(xi - agent.x), abs(yi - agent.y))
            if dist > max_range:
                continue
            key = (dist, int(layer), yi, xi)
            if best_key is None or key < best_key:
                best_key = key
                best = (xi, yi, layer)
    return best


def _descent_anchor_for(agent: ChickadeeAgent, store: StaticEntityStore) -> tuple[int, int] | None:
    """Return the anchor of a tree whose crown contains the agent's tile."""
    if agent.layer not in (Layer.CANOPY, Layer.UNDERSTORY):
        return None
    for tree in store.trees:
        if (agent.x, agent.y) in tree.crown_tiles:
            return (tree.anchor_x, tree.anchor_y)
    return None


def _best_cavity(
    agent: ChickadeeAgent,
    store: StaticEntityStore,
    world: WorldGrid,
    search_radius: int,
) -> RoostCandidate | None:
    best: RoostCandidate | None = None
    best_key: tuple[float, float, int, int] | None = None
    for cav in store.cavities:
        if cav.occupied_by is not None and cav.occupied_by != agent.agent_id:
            continue
        if not world.layer_present[Layer.CAVITY, cav.entrance_y, cav.entrance_x]:
            continue
        dist = max(abs(cav.entrance_x - agent.x), abs(cav.entrance_y - agent.y))
        if dist > search_radius:
            continue
        key = (-cav.insulation_score, float(dist), cav.entrance_y, cav.entrance_x)
        if best_key is None or key < best_key:
            best_key = key
            best = RoostCandidate(
                x=cav.entrance_x,
                y=cav.entrance_y,
                cavity_id=cav.entity_id,
                insulation_score=cav.insulation_score,
                is_known=False,
            )
    return best


def _best_crown_roost(
    agent: ChickadeeAgent,
    world: WorldGrid,
    store: StaticEntityStore,
    search_radius: int,
) -> RoostCandidate | None:
    """Dense crown fallback: a live black-spruce canopy tile that is empty."""
    best: RoostCandidate | None = None
    best_key: tuple[float, int, int] | None = None
    x0 = max(0, agent.x - search_radius)
    x1 = min(world.width, agent.x + search_radius + 1)
    y0 = max(0, agent.y - search_radius)
    y1 = min(world.height, agent.y + search_radius + 1)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not world.layer_present[Layer.CANOPY, y, x]:
                continue
            if not _tile_leads_to_black_spruce(store, x, y):
                continue
            if int(world.occupants[Layer.CANOPY, y, x]) not in (NO_OCCUPANT, agent.agent_id):
                continue
            biomass = float(world.resource_biomass[Layer.CANOPY, y, x])
            key = (-biomass, y, x)
            if best_key is None or key < best_key:
                best_key = key
                best = RoostCandidate(
                    x=x,
                    y=y,
                    cavity_id=None,
                    insulation_score=0.4,
                    is_known=False,
                )
    return best


__all__ = [
    "ChickadeePercept",
    "ForageCandidate",
    "RoostCandidate",
    "build_chickadee_percept",
]
