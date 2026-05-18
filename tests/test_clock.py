"""Tests for SimClock."""

from hypothesis import given, settings
from hypothesis import strategies as st

from ecosystemsim.clock import SimClock, make_clock


def test_initial_state() -> None:
    clock = make_clock(tick_seconds=10.0, max_ticks=8640)
    assert clock.current_tick == 0
    assert clock.elapsed_seconds == 0.0


def test_advance_increments_tick() -> None:
    clock = make_clock(10.0, 100)
    clock.advance()
    assert clock.current_tick == 1


def test_elapsed_seconds_is_deterministic() -> None:
    clock = make_clock(10.0, 100)
    for _ in range(50):
        clock.advance()
    assert clock.elapsed_seconds == 500.0


def test_elapsed_equals_tick_times_tick_seconds() -> None:
    clock = make_clock(15.0, 200)
    for _ in range(37):
        clock.advance()
    assert clock.elapsed_seconds == 37 * 15.0


def test_reset_returns_to_zero() -> None:
    clock = make_clock(10.0, 100)
    for _ in range(10):
        clock.advance()
    clock.reset()
    assert clock.current_tick == 0
    assert clock.elapsed_seconds == 0.0


def test_day_fraction_wraps() -> None:
    # After exactly 1 day the fraction should return to 0.
    clock = make_clock(1.0, 100_000)
    for _ in range(86400):
        clock.advance()
    assert abs(clock.day_fraction) < 1e-9


@given(st.integers(min_value=0, max_value=8640))
@settings(max_examples=200)
def test_elapsed_always_equals_tick_times_seconds(n_ticks: int) -> None:
    clock = SimClock(tick_seconds=10.0, max_ticks=8640)
    for _ in range(n_ticks):
        clock.advance()
    assert clock.elapsed_seconds == n_ticks * 10.0
