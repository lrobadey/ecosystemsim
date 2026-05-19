"""Headless simulation engine."""

from __future__ import annotations

from dataclasses import dataclass

from ecosystemsim.agents.chickadee import AgentStore, decide_chickadee
from ecosystemsim.clock import SimClock, make_clock
from ecosystemsim.config import RunConfig
from ecosystemsim.events import EventLog
from ecosystemsim.generator import generate_forest
from ecosystemsim.perception import build_chickadee_percept
from ecosystemsim.rng import make_rng
from ecosystemsim.spawn import spawn_chickadees
from ecosystemsim.systems import (
    age_chickadee_memories,
    apply_chickadee_metabolism,
    resolve_chickadee_intents,
    update_chickadee_behavioral_states,
)
from ecosystemsim.world import LAYER_NAMES, WorldGrid, make_world


@dataclass
class SimResult:
    ticks_run: int
    final_tick: int
    event_count: int
    terminated_reason: str


def run_headless(cfg: RunConfig) -> tuple[SimResult, EventLog]:
    """Run a deterministic simulation with chickadee agents for ``cfg.clock.max_ticks``."""
    rng = make_rng(cfg.seed)
    world: WorldGrid = make_world(cfg.map)
    clock: SimClock = make_clock(cfg.clock.tick_seconds, cfg.clock.max_ticks)
    log = EventLog()

    log.emit(0, "sim_started", payload={"seed": cfg.seed, "max_ticks": cfg.clock.max_ticks})

    store = generate_forest(cfg, world, rng)
    log.emit(
        0,
        "world_generated",
        payload={"trees": len(store.trees), "cavities": len(store.cavities)},
    )

    agents: AgentStore = spawn_chickadees(cfg, world, store, rng)
    log.emit(
        0,
        "chickadees_spawned",
        payload={
            "count": len(agents.chickadees),
            "starts": [
                {
                    "agent_id": a.agent_id,
                    "x": a.x,
                    "y": a.y,
                    "layer": LAYER_NAMES[a.layer],
                    "state": a.state.value,
                    "energy_kj": a.energy_kj,
                }
                for a in agents.chickadees
            ],
        },
    )

    ticks_per_day = round(86400.0 / cfg.clock.tick_seconds)
    if ticks_per_day <= 0:
        ticks_per_day = 1

    time_budget: dict[int, dict[str, int]] = {
        a.agent_id: {name: 0 for name in LAYER_NAMES} for a in agents.chickadees
    }
    daylight_time_budget: dict[int, dict[str, int]] = {
        a.agent_id: {name: 0 for name in LAYER_NAMES} for a in agents.chickadees
    }

    for _ in range(cfg.clock.max_ticks):
        clock.advance()
        intents = []
        for agent in agents.alive_chickadees():
            percept = build_chickadee_percept(agent, world, store, clock, cfg)
            intents.append((agent, decide_chickadee(agent, percept, cfg, rng)))
        resolve_chickadee_intents(intents, world, store, log, clock.current_tick, rng, cfg)
        apply_chickadee_metabolism(agents.chickadees, world, store, clock, cfg, log)
        update_chickadee_behavioral_states(agents.chickadees, clock)
        age_chickadee_memories(agents.chickadees, cfg)

        for agent in agents.alive_chickadees():
            time_budget[agent.agent_id][LAYER_NAMES[agent.layer]] += 1
            if clock.is_daytime:
                daylight_time_budget[agent.agent_id][LAYER_NAMES[agent.layer]] += 1

        if clock.current_tick % ticks_per_day == 0:
            log.emit(
                clock.current_tick,
                "day_summary",
                payload={
                    "agents": [
                        {
                            "agent_id": a.agent_id,
                            "alive": a.alive,
                            "energy_kj": a.energy_kj,
                            "state": a.state.value,
                            "total_time_budget": dict(time_budget[a.agent_id]),
                            "daylight_time_budget": dict(daylight_time_budget[a.agent_id]),
                        }
                        for a in agents.chickadees
                    ]
                },
            )
            for budget in time_budget.values():
                for key in budget:
                    budget[key] = 0
            for budget in daylight_time_budget.values():
                for key in budget:
                    budget[key] = 0

    log.emit(
        clock.current_tick,
        "sim_finished",
        payload={
            "ticks_run": clock.current_tick,
            "elapsed_seconds": clock.elapsed_seconds,
        },
    )

    return (
        SimResult(
            ticks_run=clock.current_tick,
            final_tick=clock.current_tick,
            event_count=len(log),
            terminated_reason="max_ticks_reached",
        ),
        log,
    )
