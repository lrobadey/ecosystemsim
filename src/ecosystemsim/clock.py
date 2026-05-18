"""Deterministic simulation clock."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimClock:
    tick_seconds: float
    max_ticks: int
    current_tick: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return self.current_tick * self.tick_seconds

    @property
    def day_fraction(self) -> float:
        """Fraction of a 24-hour day elapsed since sim start (wraps at midnight)."""
        seconds_per_day = 86400.0
        return (self.elapsed_seconds % seconds_per_day) / seconds_per_day

    @property
    def is_daytime(self) -> bool:
        """Simple stub: daytime when day_fraction in [0.25, 0.75]."""
        f = self.day_fraction
        return 0.25 <= f <= 0.75

    @property
    def dusk_pressure(self) -> float:
        """Rises from 0 to 1 as dusk approaches; 0 during daytime / night."""
        f = self.day_fraction
        if f < 0.6 or f > 0.8:
            return 0.0
        return (f - 0.6) / 0.2

    def advance(self) -> None:
        self.current_tick += 1

    def reset(self) -> None:
        self.current_tick = 0


def make_clock(tick_seconds: float, max_ticks: int) -> SimClock:
    return SimClock(tick_seconds=tick_seconds, max_ticks=max_ticks)
