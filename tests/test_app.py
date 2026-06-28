from __future__ import annotations

import asyncio
from types import ModuleType

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.containers import HorizontalScroll
from textual.widgets import Static

from ma.agent_loader import LoadedAgent
from ma.app import (
    AssistantBlock,
    ComposerTextArea,
    MaApp,
    complete_command_text,
    render_command_hint,
    render_todo_items,
)
from ma.stores import TodoItem


def test_composer_enter_submits_and_ctrl_enter_inserts_newline():
    async def run() -> None:
        submitted: list[str] = []

        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app

            async def fake_submit() -> None:
                composer = app.query_one(ComposerTextArea)
                submitted.append(composer.text)
                composer.load_text("")

            app.submit_composer = fake_submit
            composer = app.query_one(ComposerTextArea)
            composer.disabled = False
            composer.add_class("ready")
            composer.focus()
            composer.load_text("hello")

            await pilot.press("enter")
            await pilot.pause()

            assert submitted == ["hello"]
            assert composer.text == ""

            composer.load_text("hello")
            await pilot.press("ctrl+enter")
            await pilot.pause()

            assert submitted == ["hello"]
            assert "\n" in composer.text

    asyncio.run(run())


def test_command_completion_helpers_complete_common_prefix_and_single_match():
    assert complete_command_text("/mo") == "/model"
    assert complete_command_text("/n") == "/notes "
    assert complete_command_text("/notes c") == "/notes clear"
    assert complete_command_text("hello") == "hello"

    hint = render_command_hint("/rea")
    assert "Tab:" in hint.plain
    assert "/reasoning" in hint.plain

    hint = render_command_hint("/mod")
    assert hint.plain == "/model"


def test_composer_tab_completes_command_and_updates_hint():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            composer = app.query_one(ComposerTextArea)
            composer.disabled = False
            composer.add_class("ready")
            composer.focus()
            composer.load_text("/mo")
            app.update_command_hint()

            await pilot.press("tab")
            await pilot.pause()

            hint = app.query_one("#completion-hint", Static)
            assert composer.text == "/model"
            assert hint.has_class("visible")
            assert "Press Enter" in hint.content.plain

    asyncio.run(run())


def test_startup_splash_is_mounted_before_background_startup_finishes():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            splash = pilot.app.query_one("#startup-splash", Static)
            composer = pilot.app.query_one(ComposerTextArea)
            assert "Dmitry Soshnikov" in splash.content.plain
            assert "SHWARSICO Vibe Coding Dept" in splash.content.plain
            assert "μA" in splash.content.plain
            assert not composer.has_class("ready")
            assert pilot.app.focused is not composer

    asyncio.run(run())


def test_assistant_block_streams_plain_text_then_finalizes_markdown():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            transcript = pilot.app.query_one("#transcript")
            block = AssistantBlock()
            await block.mount(transcript)

            block.append("| A")
            block.append(" |\n| - |\n| 1 |")

            assert block.text == "| A |\n| - |\n| 1 |"
            assert isinstance(block.widget.content, Text)

            block.finalize()

            assert block.finalized is True
            assert isinstance(block.widget.content, RichMarkdown)
            assert block.widget.content.markup == "| A |\n| - |\n| 1 |"

    asyncio.run(run())


def test_assistant_blocks_finalize_before_events_and_restart_after():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            transcript = pilot.app.query_one("#transcript")

            first = AssistantBlock()
            await first.mount(transcript)
            first.append("Before **tool**")
            first.finalize()
            pilot.app.add_event("Tool call: search")

            second = AssistantBlock()
            await second.mount(transcript)
            second.append("After | tool |")
            second.finalize()

            await pilot.pause()

            children = list(transcript.children)
            event_index = next(
                index for index, child in enumerate(children) if "Tool call: search" in str(child.content)
            )
            assert isinstance(children[event_index - 1], Static)
            assert isinstance(children[event_index - 1].content, RichMarkdown)
            assert isinstance(children[event_index], Static)
            assert isinstance(children[event_index + 1], Static)
            assert isinstance(children[event_index + 1].content, RichMarkdown)

    asyncio.run(run())


def test_render_todo_items_uses_no_wrap_unicode_and_done_style():
    renderable = render_todo_items(
        [
            TodoItem("Read one long source"),
            TodoItem("Write summary", done=True),
        ]
    )

    assert renderable.no_wrap is True
    assert renderable.plain == "☐ Read one long source\n☑ Write summary"
    assert any(str(span.style) == "light_green" for span in renderable.spans)


def test_todo_pane_uses_horizontal_scroll_and_formatted_block():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            app.active_agent = LoadedAgent(
                name="todo",
                module=ModuleType("todo"),
                agent=object(),
                props={"display_name": "Todo", "uses_todo": True},
            )
            app.todo_store.create_todo("A very long TODO item that should stay on one visual line")
            app.todo_store.create_todo("Done item")
            app.todo_store.mark_done(1)

            app.refresh_side()
            await pilot.pause()

            todo_pane = app.query_one("#todo-pane", HorizontalScroll)
            todo_block = todo_pane.query_one(".todo-list", Static)

            assert todo_pane.has_class("visible")
            assert isinstance(todo_block.content, Text)
            assert todo_block.content.no_wrap is True
            assert todo_block.content.plain == (
                "☐ A very long TODO item that should stay on one visual line\n"
                "☑ Done item"
            )

    asyncio.run(run())
