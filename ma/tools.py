from __future__ import annotations

from typing import Any

from .stores import NotesStore, TodoStore


def build_notes_tools(store: NotesStore) -> list[Any]:
    from agents import function_tool

    @function_tool
    def create_note(
        category: str,
        title: str,
        body: str,
        url: str | None = None,
        extra: str | None = None,
    ) -> str:
        """Create a note for the current chat session. Put optional extra metadata in extra as text."""
        extra_fields = {"extra": extra} if extra else None
        note = store.create_note(category=category, title=title, body=body, url=url, extra=extra_fields)
        return f"Created note '{note.title}' in category '{note.category}'."

    @function_tool
    def list_notes(category: str | None = None, title_search: str | None = None) -> str:
        """List notes, optionally filtered by category or title search."""
        notes = store.list_notes(category=category, title_search=title_search)
        if not notes:
            return "No notes found."
        lines: list[str] = []
        for index, note in enumerate(notes, 1):
            url = f" ({note.url})" if note.url else ""
            lines.append(f"{index}. [{note.category}] {note.title}{url}\n{note.body}")
        return "\n\n".join(lines)

    @function_tool
    def clear_notes() -> str:
        """Clear all notes for the current chat session."""
        count = store.clear()
        return f"Cleared {count} notes."

    return [create_note, list_notes, clear_notes]


def build_todo_tools(store: TodoStore) -> list[Any]:
    from agents import function_tool

    @function_tool
    def create_todo(title: str, position: int | None = None) -> str:
        """Create a TODO item at the given zero-based position, or append it."""
        item = store.create_todo(title=title, position=position)
        return f"Created TODO '{item.title}'."

    @function_tool
    def mark_todo_done(index: int) -> str:
        """Mark a zero-based TODO item index as done."""
        item = store.mark_done(index)
        return f"Marked TODO '{item.title}' as done."

    @function_tool
    def get_next_todo() -> str:
        """Return the next unfinished TODO item."""
        item = store.get_next()
        return item.title if item else "No unfinished TODO items."

    return [create_todo, mark_todo_done, get_next_todo]
