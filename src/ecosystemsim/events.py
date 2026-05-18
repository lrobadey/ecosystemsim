"""Immutable event records and in-memory event log with JSONL export."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import msgspec


class EventRecord(msgspec.Struct, frozen=True):
    tick: int
    event_type: str
    actor_id: int | None = None
    x: int | None = None
    y: int | None = None
    layer: str | None = None
    payload: dict[str, Any] = {}  # noqa: RUF012


class EventLog:
    def __init__(self) -> None:
        self._records: list[EventRecord] = []

    def append(self, record: EventRecord) -> None:
        self._records.append(record)

    def emit(
        self,
        tick: int,
        event_type: str,
        *,
        actor_id: int | None = None,
        x: int | None = None,
        y: int | None = None,
        layer: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._records.append(
            EventRecord(
                tick=tick,
                event_type=event_type,
                actor_id=actor_id,
                x=x,
                y=y,
                layer=layer,
                payload=payload or {},
            )
        )

    def all_records(self) -> list[EventRecord]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def to_jsonl(self) -> str:
        buf = io.StringIO()
        for record in self._records:
            buf.write(msgspec.json.encode(record).decode())
            buf.write("\n")
        return buf.getvalue()

    def write_jsonl(self, path: Path | str) -> None:
        Path(path).write_text(self.to_jsonl(), encoding="utf-8")

    @staticmethod
    def from_jsonl(text: str) -> EventLog:
        log = EventLog()
        for line in text.splitlines():
            line = line.strip()
            if line:
                log.append(msgspec.json.decode(line.encode(), type=EventRecord))
        return log
