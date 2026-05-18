"""Headless simulation engine."""

from __future__ import annotations

from dataclasses import dataclass

from ecosystemsim.clock import SimClock, make_clock
from ecosystemsim.config import RunConfig
from ecosystemsim.events import EventLog
from ecosystemsim.generator import generate_forest
from ecosystemsim.rng import make_rng
from ecosystemsim.world import WorldGrid, make_world


@dataclass
class SimResult:
    ticks_run: int
    final_tick: int
    event_count: int
    terminated_reason: str


def run_headless(cfg: RunConfig) -> tuple[SimResult, EventLog]:
    """Run a no-agent deterministic simulation for cfg.clock.max_ticks."""
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

    for _ in range(cfg.clock.max_ticks):
        clock.advance()

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
