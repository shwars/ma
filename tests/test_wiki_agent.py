from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agents import RunContextWrapper

from ma.agent_loader import AgentLoader
from ma.stores import NotesStore, TodoStore
from ma.tools import build_todo_tools


AGENTS_DIR = Path(__file__).parents[1] / "agents"


def make_context() -> SimpleNamespace:
    notes_store = NotesStore()
    todo_store = TodoStore()
    return SimpleNamespace(
        notes_store=notes_store,
        todo_store=todo_store,
        todo_tools=build_todo_tools(todo_store),
        clarification_tools=[],
        model=None,
        reasoning_level=None,
        log=lambda _message: None,
    )


def load_wiki(tmp_path: Path):
    loaded = AgentLoader(AGENTS_DIR).load("wiki-agent")
    module = loaded.module
    context = make_context()
    module._context = context
    module._root = tmp_path
    return loaded, module, context


def test_source_notes_are_deduplicated_and_limited(tmp_path):
    _loaded, module, _context = load_wiki(tmp_path)
    module.reset_wiki("Agent systems")

    first = module.save_source(
        "First",
        "HTTPS://EXAMPLE.COM/article/#fragment",
        "An extended summary.",
    )
    duplicate = module.save_source(
        "Duplicate",
        "https://example.com/article",
        "Another summary.",
    )
    for index in range(1, module.SOURCE_LIMIT):
        module.save_source(
            f"Source {index}",
            f"https://example.com/source-{index}",
            f"Extended summary {index}.",
        )
    over_limit = module.save_source(
        "Too many",
        "https://example.com/too-many",
        "This must not be stored.",
    )

    assert "1/30" in first
    assert "already recorded" in duplicate
    assert "Source limit reached" in over_limit
    assert module.source_count() == 30


def test_research_status_and_note_pagination(tmp_path):
    _loaded, module, context = load_wiki(tmp_path)
    module.reset_wiki("Knowledge graphs")
    context.todo_store.create_todo("Definitions")
    context.todo_store.create_todo("Applications")
    context.todo_store.mark_done(0)
    module.save_source("Source", "https://example.com/source", "Extended source summary.")

    status = module.research_status_text()
    first_page = module.source_notes_text(offset=0, limit=10)

    assert "0: [done] Definitions" in status
    assert "1: [pending] Applications" in status
    assert "Ready for conceptualization: no" in status
    assert "Source notes 1-1 of 1" in first_page
    assert "https://example.com/source" in first_page


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Machine Learning", "machine-learning"),
        (" Машинное обучение ", "машинное-обучение"),
        ("量子-計算", "量子-計算"),
    ],
)
def test_normalize_slug_accepts_short_semantic_unicode_slugs(tmp_path, value, expected):
    _loaded, module, _context = load_wiki(tmp_path)

    assert module.normalize_slug(value) == expected


@pytest.mark.parametrize(
    "value",
    ["README", "con", "bad/slug", "one-two-three-four-five-six", "x" * 49],
)
def test_normalize_slug_rejects_unsafe_or_excessive_values(tmp_path, value):
    _loaded, module, _context = load_wiki(tmp_path)

    with pytest.raises(ValueError):
        module.normalize_slug(value)


def test_graph_links_and_merging(tmp_path):
    _loaded, module, _context = load_wiki(tmp_path)
    module.reset_wiki("Publications")
    module.save_concept("paper", "Paper", "A paper with a source link.")
    module.save_concept("article", "Article", "An article with a source link.")
    module.save_concept("book", "Book", "A book with a source link.")
    module.save_link("paper", "book", "related-to", "Paper relation.")
    module.save_link("article", "book", "related-to", "Article relation.")

    with pytest.raises(ValueError, match="already belongs"):
        module.save_concept("paper", "Newspaper", "Different concept.")
    with pytest.raises(ValueError, match="both endpoint"):
        module.save_link("paper", "missing", "part-of", "Missing endpoint.")

    module.merge_graph_concepts(
        ["paper", "article"],
        "written-work",
        "Written Work",
        "A combined concept.",
    )
    payload = module.graph_data()

    assert {vertex["id"] for vertex in payload["vertices"]} == {"book", "written-work"}
    assert len(payload["links"]) == 1
    assert payload["links"][0]["source"] == "written-work"
    assert payload["links"][0]["target"] == "book"


def test_export_replaces_snapshot_and_writes_bidirectional_pages(tmp_path):
    _loaded, module, _context = load_wiki(tmp_path)
    old_wiki = tmp_path / "wiki"
    old_wiki.mkdir()
    (old_wiki / "stale.md").write_text("stale", encoding="utf-8")

    module.reset_wiki("Machine learning")
    module.save_source("Reference", "https://example.com/ml", "Extended research summary.")
    module.save_concept("machine-learning", "Machine Learning", "Learning from data.")
    module.save_concept("artificial-intelligence", "Artificial Intelligence", "A broader field.")
    module.save_link(
        "machine-learning",
        "artificial-intelligence",
        "a-kind-of",
        "Machine learning is a subfield of artificial intelligence.",
    )

    result = module.write_wiki()
    graph = json.loads((old_wiki / "graph.json").read_text(encoding="utf-8"))
    machine_learning = (old_wiki / "machine-learning.md").read_text(encoding="utf-8")
    artificial_intelligence = (old_wiki / "artificial-intelligence.md").read_text(encoding="utf-8")

    assert "1 sources: 2 concepts and 1 links" in result
    assert not (old_wiki / "stale.md").exists()
    assert graph["topic"] == "Machine learning"
    assert graph["links"][0]["source"] == "machine-learning"
    assert "[Artificial Intelligence](artificial-intelligence.md)" in machine_learning
    assert "[Machine Learning](machine-learning.md)" in artificial_intelligence


def test_empty_graph_does_not_replace_existing_wiki(tmp_path):
    _loaded, module, _context = load_wiki(tmp_path)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    existing = wiki / "existing.md"
    existing.write_text("keep me", encoding="utf-8")
    module.reset_wiki("Empty graph")

    with pytest.raises(ValueError, match="empty concept graph"):
        module.write_wiki()

    assert existing.read_text(encoding="utf-8") == "keep me"


def test_set_context_configures_subagents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loaded = AgentLoader(AGENTS_DIR).load("wiki-agent")
    context = make_context()
    context.reasoning_level = "medium"

    loaded.set_context(context)

    assert loaded.max_turns == 120
    assert len(loaded.agent.handoffs) == 1
    assert len(loaded.module.researcher.handoffs) == 1
    assert loaded.module.researcher.model_settings.reasoning.effort == "medium"
    assert loaded.module.conceptualizer.model_settings.reasoning.effort == "medium"
    assert {tool.name for tool in loaded.module.researcher.tools if hasattr(tool, "name")} >= {
        "record_source",
        "research_status",
        "create_todo",
        "mark_todo_done",
    }


def test_handoffs_reset_state_and_gate_conceptualization(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loaded = AgentLoader(AGENTS_DIR).load("wiki-agent")
    context = make_context()
    context.notes_store.create_note("old", "Old note", "Old state")
    context.todo_store.create_todo("Old TODO")
    loaded.set_context(context)
    run_context = RunContextWrapper(context=None)

    loaded.module.reset_wiki("Knowledge graphs")
    next_agent = asyncio.run(loaded.agent.handoffs[0].on_invoke_handoff(run_context, None))

    assert next_agent is loaded.module.researcher
    assert context.notes_store.notes == []
    assert context.todo_store.items == []
    assert loaded.module._topic == "Knowledge graphs"

    context.todo_store.create_todo("Pending research")
    loaded.module.save_source(
        "Reference",
        "https://example.com/reference",
        "Extended source summary.",
    )
    with pytest.raises(ValueError, match="unfinished TODOs"):
        asyncio.run(loaded.module.researcher.handoffs[0].on_invoke_handoff(run_context, None))

    context.todo_store.mark_done(0)
    next_agent = asyncio.run(
        loaded.module.researcher.handoffs[0].on_invoke_handoff(run_context, None)
    )
    assert next_agent is loaded.module.conceptualizer
