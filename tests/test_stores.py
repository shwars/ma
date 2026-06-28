from __future__ import annotations

from ma.stores import NotesStore, TodoStore


def test_notes_store_filters_and_saves_markdown(tmp_path):
    store = NotesStore()
    store.create_note("source", "Alpha", "First body", url="https://example.com")
    store.create_note("idea", "Beta", "Second body")

    assert [note.title for note in store.list_notes(category="source")] == ["Alpha"]
    assert [note.title for note in store.list_notes(title_search="bet")] == ["Beta"]

    path = store.save_markdown(tmp_path / "notes.md")
    text = path.read_text(encoding="utf-8")
    assert "# Notes" in text
    assert "Alpha" in text
    assert "https://example.com" in text


def test_todo_store_tracks_next_item():
    store = TodoStore()
    store.create_todo("second")
    store.create_todo("first", position=0)

    assert store.get_next().title == "first"
    store.mark_done(0)
    assert store.get_next().title == "second"
