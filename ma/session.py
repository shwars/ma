from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_SESSION_EXTENSIONS = {".txt", ".md", ".json", ".csv"}


@dataclass(frozen=True)
class SessionEvent:
    sequence: int
    timestamp: str
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def new_session_event(
    sequence: int,
    kind: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> SessionEvent:
    return SessionEvent(
        sequence=sequence,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        kind=kind,
        content=content,
        metadata=metadata or {},
    )


def save_session(
    path: Path,
    events: Iterable[SessionEvent],
    session_metadata: dict[str, Any],
) -> Path:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SESSION_EXTENSIONS:
        choices = ", ".join(sorted(SUPPORTED_SESSION_EXTENSIONS))
        raise ValueError(f"Unsupported session format '{path.suffix}'. Use: {choices}.")

    items = list(events)
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        payload = {
            "format_version": 1,
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "session": session_metadata,
            "events": [asdict(event) for event in items],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif suffix == ".csv":
        buffer = StringIO(newline="")
        writer = csv.DictWriter(
            buffer,
            fieldnames=["sequence", "timestamp", "type", "content", "metadata"],
        )
        writer.writeheader()
        for event in items:
            writer.writerow(
                {
                    "sequence": event.sequence,
                    "timestamp": event.timestamp,
                    "type": event.kind,
                    "content": event.content,
                    "metadata": json.dumps(event.metadata, ensure_ascii=False),
                }
            )
        path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    elif suffix == ".md":
        path.write_text(_render_markdown(items, session_metadata), encoding="utf-8")
    else:
        path.write_text(_render_text(items, session_metadata), encoding="utf-8")
    return path


def _render_text(events: list[SessionEvent], session_metadata: dict[str, Any]) -> str:
    lines = ["ma session", json.dumps(session_metadata, ensure_ascii=False), ""]
    for event in events:
        lines.extend(
            [
                f"[{event.sequence} {event.timestamp}] {event.kind}",
                event.content,
            ]
        )
        if event.metadata:
            lines.append(f"Metadata: {json.dumps(event.metadata, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def _render_markdown(events: list[SessionEvent], session_metadata: dict[str, Any]) -> str:
    lines = ["# ma session", "", f"`{json.dumps(session_metadata, ensure_ascii=False)}`", ""]
    for event in events:
        lines.extend([f"## {event.sequence}. {event.kind} ({event.timestamp})", "", event.content, ""])
        if event.metadata:
            lines.extend(["Metadata:", "", _fenced_json(event.metadata), ""])
    return "\n".join(lines)


def _fenced_json(value: dict[str, Any]) -> str:
    return f"```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```"
