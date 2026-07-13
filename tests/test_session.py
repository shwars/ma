from __future__ import annotations

import csv
import json

import pytest

from ma.session import SessionEvent, save_session


def sample_events() -> list[SessionEvent]:
    return [
        SessionEvent(1, "2026-07-13T10:00:00+03:00", "user", "Summarize this table."),
        SessionEvent(
            2,
            "2026-07-13T10:00:01+03:00",
            "tool_call",
            "web_search",
            {"query": "table summary"},
        ),
        SessionEvent(3, "2026-07-13T10:00:02+03:00", "assistant", "## Summary"),
    ]


@pytest.mark.parametrize("suffix", [".txt", ".md", ".json", ".csv"])
def test_save_session_supports_requested_formats(tmp_path, suffix):
    path = save_session(
        tmp_path / f"chat{suffix}",
        sample_events(),
        {"agent": "simple", "model": "model-1"},
    )

    assert path.exists()
    assert path.read_text(encoding="utf-8")


def test_save_session_json_and_csv_preserve_event_data(tmp_path):
    events = sample_events()
    json_path = save_session(tmp_path / "chat.json", events, {"agent": "simple"})
    csv_path = save_session(tmp_path / "chat.csv", events, {"agent": "simple"})

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["session"]["agent"] == "simple"
    assert payload["events"][1]["metadata"]["query"] == "table summary"

    with csv_path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[2]["type"] == "assistant"
    assert rows[2]["content"] == "## Summary"


def test_save_session_rejects_unknown_extension(tmp_path):
    with pytest.raises(ValueError, match="Unsupported session format"):
        save_session(tmp_path / "chat.html", [], {})
