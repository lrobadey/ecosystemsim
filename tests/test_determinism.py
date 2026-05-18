"""Determinism tests: same seed + config must produce identical results."""

from pathlib import Path

import msgspec

from ecosystemsim.config import RunConfig, default_run_config
from ecosystemsim.engine import run_headless


def test_same_seed_produces_same_result() -> None:
    cfg = default_run_config()
    result1, log1 = run_headless(cfg)
    result2, log2 = run_headless(cfg)

    assert result1.ticks_run == result2.ticks_run
    assert result1.final_tick == result2.final_tick
    assert result1.event_count == result2.event_count
    assert result1.terminated_reason == result2.terminated_reason
    assert log1.to_jsonl() == log2.to_jsonl()


def test_same_seed_from_scenario_file_matches_default() -> None:
    scenario = Path(__file__).parent.parent / "scenarios" / "late_winter_microforest.json"
    cfg_file = RunConfig.from_file(scenario)
    cfg_default = default_run_config()

    result_file, log_file = run_headless(cfg_file)
    result_default, log_default = run_headless(cfg_default)

    assert result_file.ticks_run == result_default.ticks_run
    assert log_file.to_jsonl() == log_default.to_jsonl()


def test_different_seed_is_accepted() -> None:
    cfg = default_run_config()
    raw = msgspec.json.encode(cfg)
    data = msgspec.json.decode(raw)
    data["seed"] = 99999
    cfg_alt = msgspec.json.decode(msgspec.json.encode(data), type=RunConfig)

    result, log = run_headless(cfg_alt)
    assert result.ticks_run == cfg.clock.max_ticks


def test_sim_runs_correct_tick_count() -> None:
    cfg = default_run_config()
    result, _ = run_headless(cfg)
    assert result.ticks_run == cfg.clock.max_ticks
    assert result.terminated_reason == "max_ticks_reached"


def test_event_log_contains_lifecycle_events() -> None:
    cfg = default_run_config()
    _, log = run_headless(cfg)
    types = {r.event_type for r in log.all_records()}
    assert "sim_started" in types
    assert "sim_finished" in types


def test_event_log_jsonl_round_trips() -> None:
    from ecosystemsim.events import EventLog

    cfg = default_run_config()
    _, log = run_headless(cfg)
    jsonl = log.to_jsonl()
    restored = EventLog.from_jsonl(jsonl)
    assert len(restored) == len(log)
    assert restored.to_jsonl() == jsonl
