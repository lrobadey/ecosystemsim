"""Chickadee agent state, intents, and decision logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from numpy.random import Generator

from ecosystemsim.world import Layer

if TYPE_CHECKING:
    from ecosystemsim.config import RunConfig
    from ecosystemsim.perception import ChickadeePercept


class ChickadeeState(StrEnum):
    ROOSTING = "roosting"
    WARMUP = "warmup"
    FORAGE = "forage"
    PRE_ROOST = "pre_roost"
    DEAD = "dead"


@dataclass
class MemoryRecord:
    kind: str  # "profitable" | "roost"
    x: int
    y: int
    layer: Layer
    value: float
    age_ticks: int


@dataclass
class ChickadeeAgent:
    agent_id: int
    x: int
    y: int
    layer: Layer
    energy_kj: float
    state: ChickadeeState
    cavity_id: int | None
    alive: bool = True
    memory: list[MemoryRecord] = field(default_factory=list)


@dataclass
class AgentStore:
    chickadees: list[ChickadeeAgent] = field(default_factory=list)
    next_agent_id: int = 0

    def add_chickadee(self, agent: ChickadeeAgent) -> None:
        self.chickadees.append(agent)
        if agent.agent_id >= self.next_agent_id:
            self.next_agent_id = agent.agent_id + 1

    def alive_chickadees(self) -> list[ChickadeeAgent]:
        return [a for a in self.chickadees if a.alive]


@dataclass(frozen=True)
class StayIntent:
    pass


@dataclass(frozen=True)
class MoveIntent:
    to_x: int
    to_y: int
    to_layer: Layer


@dataclass(frozen=True)
class ForageIntent:
    pass


@dataclass(frozen=True)
class RoostIntent:
    cavity_id: int


ChickadeeIntent = StayIntent | MoveIntent | ForageIntent | RoostIntent


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

# Utility weights from the design doc (chickadee).
_FOOD_WEIGHT = 1.8
_TRAVEL_WEIGHT = 0.4
_MEMORY_WEIGHT = 0.7
_SPRUCE_BONUS = 0.6


def _memory_value_for(agent: ChickadeeAgent, x: int, y: int, layer: Layer) -> float:
    for record in agent.memory:
        if record.x == x and record.y == y and record.layer == layer:
            return record.value
    return 0.0


def _neighbor_score(
    agent: ChickadeeAgent,
    nx: int,
    ny: int,
    nl: Layer,
    percept: ChickadeePercept,
    cfg: RunConfig,
) -> float:
    """Utility of moving to a legal neighbor tile.

    Models the next-tick gain after a one-tile move: we expect to take a single
    bite next tick, capped at ``forage_bite_max_biomass``. That bounded gain is
    what makes "move to a richer tile then forage" comparable to "forage here
    now" — otherwise a tile with biomass ≥ ~0.5 always wins over staying put.
    """
    params = cfg.fauna.chickadees
    biomass = 0.0
    leads_to_spruce = False
    for cand in percept.forage:
        if cand.x == nx and cand.y == ny and cand.layer == nl:
            biomass = cand.expected_biomass
            leads_to_spruce = cand.leads_to_black_spruce
            break
    if not leads_to_spruce:
        leads_to_spruce = percept.here.leads_to_black_spruce
    bite = min(params.forage_bite_max_biomass, biomass)
    expected_kj = bite * params.forage_yield_kj_per_biomass
    score = _FOOD_WEIGHT * expected_kj
    score -= _TRAVEL_WEIGHT * 1.0
    score += _MEMORY_WEIGHT * _memory_value_for(agent, nx, ny, nl)
    if leads_to_spruce:
        score += _SPRUCE_BONUS
    if nl in (Layer.CANOPY, Layer.TRUNK):
        score += 0.2
    elif nl == Layer.GROUND:
        score -= 0.3
    return score


def decide_chickadee(
    agent: ChickadeeAgent,
    percept: ChickadeePercept,
    cfg: RunConfig,
    rng: Generator,
) -> ChickadeeIntent:
    """Return an intent for ``agent`` given the current ``percept``."""
    del rng  # decision is fully deterministic from the percept
    params = cfg.fauna.chickadees
    dusk_pressure = percept.dusk_pressure

    # 1. Pre-roost takes priority when dusk is salient and a roost is reachable.
    if dusk_pressure > 0.7:
        if agent.layer == Layer.CAVITY:
            return StayIntent()
        if percept.cavity_roost is not None:
            cav = percept.cavity_roost
            if (
                agent.layer == Layer.TRUNK
                and agent.x == cav.x
                and agent.y == cav.y
                and cav.cavity_id is not None
            ):
                return RoostIntent(cavity_id=cav.cavity_id)
            return _pick_closest(percept.neighbors, cav.x, cav.y, Layer.TRUNK, agent)
        if percept.crown_roost is not None:
            crown = percept.crown_roost
            # Already at the crown roost → stay put for the night.
            if agent.layer == Layer.CANOPY and agent.x == crown.x and agent.y == crown.y:
                return StayIntent()
            return _pick_closest(percept.neighbors, crown.x, crown.y, Layer.CANOPY, agent)
        # No reachable roost — settle on a stable canopy tile.
        if agent.layer == Layer.CANOPY:
            return StayIntent()

    # 2. Roosting at night → stay put inside cavity.
    if agent.layer == Layer.CAVITY and not percept.is_daytime:
        return StayIntent()

    # 3. Warmup: still inside a cavity at daytime → exit to trunk.
    if agent.layer == Layer.CAVITY and percept.is_daytime:
        return MoveIntent(to_x=agent.x, to_y=agent.y, to_layer=Layer.TRUNK)

    # 4. Sated chickadees rest in place on a tree to avoid grinding food to
    #    zero while already near full energy.
    if agent.energy_kj >= params.target_energy_kj and agent.layer in (
        Layer.TRUNK,
        Layer.CANOPY,
        Layer.UNDERSTORY,
    ):
        return StayIntent()

    # 5. Forage in place if there's biomass here and we're on a tree layer.
    if (
        agent.layer in (Layer.TRUNK, Layer.CANOPY, Layer.UNDERSTORY)
        and percept.here.expected_biomass > 0.0
        and agent.energy_kj < params.target_energy_kj
    ):
        return ForageIntent()

    # 6. Pick the best neighbor with non-zero biomass.
    forage_biomass: dict[tuple[int, int, int], float] = {
        (c.x, c.y, int(c.layer)): c.expected_biomass for c in percept.forage
    }
    best_action: ChickadeeIntent = StayIntent()
    best_key: tuple[float, int, int, int] | None = None
    for nx, ny, nl in percept.neighbors:
        if forage_biomass.get((nx, ny, int(nl)), 0.0) <= 0.0:
            continue
        score = _neighbor_score(agent, nx, ny, nl, percept, cfg)
        key = (score, -int(nl), -ny, -nx)
        if best_key is None or key > best_key:
            best_key = key
            best_action = MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
    if best_key is not None:
        return best_action

    # 7. Stranded — no immediate food. Step toward the most attractive distant
    #    forage candidate. Use a layer-aware escape route (canopy → trunk →
    #    ground → trunk → canopy) so the bird can leave a depleted tree.
    if percept.forage:
        target = percept.forage[0]
        return _escape_step(agent, target.x, target.y, target.layer, percept)

    # 8. No food in perception. Walk toward the global food beacon — the
    #    nearest tile on the map with biomass — so the bird doesn't starve on
    #    a locally depleted patch.
    if percept.food_beacon is not None:
        bx, by, blayer = percept.food_beacon
        return _escape_step(agent, bx, by, blayer, percept)

    return StayIntent()


def _escape_step(
    agent: ChickadeeAgent,
    tx: int,
    ty: int,
    target_layer: Layer,
    percept: ChickadeePercept,
) -> ChickadeeIntent:
    """Layer-aware one-step move toward a distant target tile.

    Path planning: from canopy/understory we first descend to ground via the
    current tree's anchor (canopy → trunk → ground); ground hops Chebyshev
    toward the target tile; arriving on a tile with a trunk lets us climb
    back up to canopy at the destination.
    """
    if not percept.neighbors:
        return StayIntent()

    # Canopy / understory: descend toward ground first via the tree anchor.
    if agent.layer == Layer.CANOPY:
        if percept.descent_anchor is not None:
            ax, ay = percept.descent_anchor
            if agent.x == ax and agent.y == ay:
                for nx, ny, nl in percept.neighbors:
                    if nl == Layer.TRUNK and nx == ax and ny == ay:
                        return MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
            # Walk in canopy toward the anchor.
            return _pick_closest(percept.neighbors, ax, ay, Layer.CANOPY, agent)
    elif agent.layer == Layer.UNDERSTORY:
        for nx, ny, nl in percept.neighbors:
            if nl == Layer.GROUND and nx == agent.x and ny == agent.y:
                return MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
    elif agent.layer == Layer.TRUNK:
        # On trunk → drop to ground at the anchor.
        for nx, ny, nl in percept.neighbors:
            if nl == Layer.GROUND and nx == agent.x and ny == agent.y:
                return MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
    elif agent.layer == Layer.GROUND:
        # If we're on the target tile, climb the trunk if available.
        if agent.x == tx and agent.y == ty:
            for nx, ny, nl in percept.neighbors:
                if nl == Layer.TRUNK and nx == tx and ny == ty:
                    return MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
                if nl == Layer.UNDERSTORY:
                    return MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
        # Step toward target on ground; climb if we cross a tree anchor.
        current_dist = max(abs(agent.x - tx), abs(agent.y - ty))
        closer: list[tuple[int, int, Layer]] = [
            (nx, ny, nl)
            for nx, ny, nl in percept.neighbors
            if nl == Layer.GROUND and max(abs(nx - tx), abs(ny - ty)) < current_dist
        ]
        if closer:
            return _pick_closest(closer, tx, ty, target_layer, agent)
    return _pick_closest(percept.neighbors, tx, ty, target_layer, agent)


def _pick_closest(
    candidates: list[tuple[int, int, Layer]] | tuple[tuple[int, int, Layer], ...],
    tx: int,
    ty: int,
    target_layer: Layer,
    agent: ChickadeeAgent,
) -> ChickadeeIntent:
    best: tuple[int, int, Layer] | None = None
    best_key: tuple[int, int, int, int] | None = None
    for nx, ny, nl in candidates:
        layer_match = 0 if nl == target_layer else 1
        dist = max(abs(nx - tx), abs(ny - ty))
        key = (dist, layer_match, int(nl), ny * 10_000 + nx)
        if best_key is None or key < best_key:
            best_key = key
            best = (nx, ny, nl)
    if best is None:
        return StayIntent()
    nx, ny, nl = best
    if nx == agent.x and ny == agent.y and nl == agent.layer:
        return StayIntent()
    return MoveIntent(to_x=nx, to_y=ny, to_layer=nl)
