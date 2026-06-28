from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Note:
    category: str
    title: str
    body: str
    url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class NotesStore:
    def __init__(self) -> None:
        self.notes: list[Note] = []

    def create_note(
        self,
        category: str,
        title: str,
        body: str,
        url: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Note:
        note = Note(category=category, title=title, body=body, url=url, extra=extra or {})
        self.notes.append(note)
        return note

    def list_notes(self, category: str | None = None, title_search: str | None = None) -> list[Note]:
        result = self.notes
        if category:
            result = [note for note in result if note.category.lower() == category.lower()]
        if title_search:
            query = title_search.lower()
            result = [note for note in result if query in note.title.lower()]
        return result

    def clear(self) -> int:
        count = len(self.notes)
        self.notes.clear()
        return count

    def to_markdown(self) -> str:
        if not self.notes:
            return "# Notes\n\nNo notes yet.\n"

        lines = ["# Notes", ""]
        for index, note in enumerate(self.notes, 1):
            lines.append(f"## {index}. {note.title}")
            lines.append("")
            lines.append(f"- Category: {note.category}")
            if note.url:
                lines.append(f"- URL: {note.url}")
            for key, value in note.extra.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
            lines.append(note.body)
            lines.append("")
        return "\n".join(lines)

    def save_markdown(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")
        return path


@dataclass
class TodoItem:
    title: str
    done: bool = False


class TodoStore:
    def __init__(self) -> None:
        self.items: list[TodoItem] = []

    def create_todo(self, title: str, position: int | None = None) -> TodoItem:
        item = TodoItem(title=title)
        if position is None or position < 0 or position >= len(self.items):
            self.items.append(item)
        else:
            self.items.insert(position, item)
        return item

    def mark_done(self, index: int) -> TodoItem:
        item = self.items[index]
        item.done = True
        return item

    def get_next(self) -> TodoItem | None:
        for item in self.items:
            if not item.done:
                return item
        return None

    def clear(self) -> int:
        count = len(self.items)
        self.items.clear()
        return count
