from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.containers import HorizontalScroll
from textual.widgets import Collapsible, ListView, Static

from ma.agent_loader import LoadedAgent
from ma.app import (
    AssistantBlock,
    ClarificationScreen,
    ComposerTextArea,
    DownloadResult,
    HelpScreen,
    MaApp,
    ReasoningBlock,
    collect_output_files,
    complete_command_text,
    reasoning_delta_text,
    reasoning_item_text,
    render_command_hint,
    render_todo_items,
    result_file_sources,
    safe_download_path,
    same_file_content,
    should_skip_completed_reasoning,
    truncate_text,
    write_downloaded_file,
)
from ma.stores import TodoItem


def test_composer_enter_submits_and_ctrl_enter_inserts_newline():
    async def run() -> None:
        submitted: list[str] = []

        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            for _ in range(10):
                await pilot.pause()
                if not app.starting:
                    break

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


def test_composer_history_browses_entries_and_returns_to_cursor_navigation(tmp_path):
    async def run() -> None:
        async with MaApp(config_path="missing.json", settings_file=tmp_path / "ma.ini").run_test() as pilot:
            app = pilot.app
            composer = app.query_one(ComposerTextArea)
            composer.disabled = False
            composer.add_class("ready")
            composer.focus()
            app.prompt_history = ["/help", "first\nsecond", "latest"]

            composer.load_text("")
            await pilot.press("up")
            assert composer.text == "latest"

            await pilot.press("up")
            assert composer.text == "first\nsecond"

            await pilot.press("down")
            assert composer.text == "latest"

            await pilot.press("down")
            assert composer.text == ""

            await pilot.press("up")
            composer.insert("!")
            await pilot.pause()
            assert app.prompt_history_index is None

            await pilot.press("up")
            assert composer.text == "latest!"

    asyncio.run(run())


def test_submit_composer_records_commands_and_prompts(tmp_path):
    async def run() -> None:
        async with MaApp(config_path="missing.json", settings_file=tmp_path / "ma.ini").run_test() as pilot:
            app = pilot.app
            composer = app.query_one(ComposerTextArea)
            handled_commands: list[str] = []
            prompts: list[str] = []

            async def handle_command(text: str) -> None:
                handled_commands.append(text)

            app.handle_command = handle_command
            app.run_chat = lambda text: prompts.append(text)

            composer.load_text("/help")
            await app.submit_composer()
            composer.load_text("Explain\nthis")
            await app.submit_composer()
            await pilot.pause()

            assert handled_commands == ["/help"]
            assert prompts == ["Explain\nthis"]
            assert app.prompt_history[-2:] == ["/help", "Explain\nthis"]

    asyncio.run(run())


def test_command_completion_helpers_complete_common_prefix_and_single_match():
    assert complete_command_text("/mo") == "/model"
    assert complete_command_text("/n") == "/n"
    assert complete_command_text("/note") == "/notes "
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
            assert "/model" in hint.content.plain

    asyncio.run(run())


def test_dynamic_command_completion_includes_agent_and_model(tmp_path):
    async def run() -> None:
        agents_dir = tmp_path / "agents"
        agent_dir = agents_dir / "sample"
        agent_dir.mkdir(parents=True)
        (agent_dir / "main.py").write_text(
            "agent = object()\ndef get_props():\n    return {'display_name': 'Sample Agent'}\n",
            encoding="utf-8",
        )

        async with MaApp(config_path="missing.json", agents_dir=agents_dir).run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
                if pilot.app.active_agent is not None:
                    break

            completions = pilot.app.command_completions()

            assert "/agent sample" in completions
            assert "/agent Sample Agent" in completions
            assert "/model Agent Default" in completions
            assert "/theme textual-dark" in completions

    asyncio.run(run())


def test_direct_agent_and_model_commands_switch_selection(tmp_path):
    async def run() -> None:
        agents_dir = tmp_path / "agents"
        for name in ["one", "two"]:
            agent_dir = agents_dir / name
            agent_dir.mkdir(parents=True)
            (agent_dir / "main.py").write_text(
                f"agent = object()\ndef get_props():\n    return {{'display_name': '{name.title()} Agent'}}\n",
                encoding="utf-8",
            )

        async with MaApp(config_path="missing.json", agents_dir=agents_dir).run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
                if pilot.app.active_agent is not None:
                    break

            await pilot.app.handle_command("/agent Two Agent")
            await pilot.app.handle_command("/model Agent Default")

            assert pilot.app.active_agent is not None
            assert pilot.app.active_agent.name == "two"
            assert pilot.app.selected_model is not None
            assert pilot.app.selected_model.display_name == "Agent Default"

    asyncio.run(run())


def test_download_command_updates_mode():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app

            await app.handle_command("/download auto")
            assert app.download_mode == "auto"

            await app.handle_command("/download skip")
            assert app.download_mode == "skip"

            await app.handle_command("/download ask")
            assert app.download_mode == "ask"

    asyncio.run(run())


def test_theme_command_switches_theme_and_opens_picker():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app

            await app.handle_command("/theme nord")
            assert app.theme == "nord"

            await app.handle_command("/theme")
            await pilot.pause()
            assert getattr(app.screen, "title", "") == "Select theme"

    asyncio.run(run())


def test_download_command_without_argument_opens_picker():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            await pilot.app.handle_command("/download")
            await pilot.pause()

            assert getattr(pilot.app.screen, "title", "") == "Select download mode"

    asyncio.run(run())


def test_palette_has_single_download_command():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            titles = [command.title for command in pilot.app.get_system_commands(pilot.app.screen)]

            assert "Download" in titles
            assert "Download Auto" not in titles
            assert "Download Ask" not in titles
            assert "Download Skip" not in titles

    asyncio.run(run())


def test_palette_has_single_theme_command():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            titles = [command.title for command in pilot.app.get_system_commands(pilot.app.screen)]

            assert titles.count("Theme") == 1
            assert "Change Theme" not in titles

    asyncio.run(run())


def test_first_escape_during_run_shows_interrupt_hint():
    class FakeWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            worker = FakeWorker()
            app.busy = True
            app.active_run_worker = worker

            assert app.handle_escape_interrupt(now=10.0) is True
            await pilot.pause()

            assert worker.cancelled is False
            assert app.interrupt_requested is False
            transcript = app.query_one("#transcript")
            assert any(
                "Press Esc again to interrupt the current run." in str(child.content)
                for child in transcript.children
            )

    asyncio.run(run())


def test_second_escape_within_timeout_cancels_active_worker():
    class FakeWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            worker = FakeWorker()
            app.busy = True
            app.active_run_worker = worker

            assert app.handle_escape_interrupt(now=10.0) is True
            assert app.handle_escape_interrupt(now=11.0) is True
            await pilot.pause()

            assert worker.cancelled is True
            assert app.interrupt_requested is True
            transcript = app.query_one("#transcript")
            assert any("Interrupt requested." in str(child.content) for child in transcript.children)

    asyncio.run(run())


def test_escape_after_timeout_starts_new_interrupt_window():
    class FakeWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            worker = FakeWorker()
            app.busy = True
            app.active_run_worker = worker

            assert app.handle_escape_interrupt(now=10.0) is True
            assert app.handle_escape_interrupt(now=13.0) is True
            assert worker.cancelled is False

            assert app.handle_escape_interrupt(now=14.0) is True
            assert worker.cancelled is True

    asyncio.run(run())


def test_new_command_resets_current_session_state():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            app.history.append({"role": "user", "content": "hello"})
            app.notes_store.create_note("cat", "title", "body")
            app.todo_store.create_todo("todo")
            app.downloaded_file_ids.add("file-1")
            transcript = app.query_one("#transcript")
            await transcript.mount(Static("old"))

            await app.handle_command("/new")
            await pilot.pause()

            assert app.history == []
            assert app.notes_store.notes == []
            assert app.todo_store.items == []
            assert app.downloaded_file_ids == set()
            assert any("Started a new chat session." in str(child.content) for child in transcript.children)

    asyncio.run(run())


def test_help_command_opens_help_screen():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            await pilot.app.handle_command("/help")
            await pilot.pause()

            assert isinstance(pilot.app.screen, HelpScreen)
            assert "/agent [name]" in str(pilot.app.screen.query_one("#help-body", Static).content)

    asyncio.run(run())


def test_modal_screens_are_centered():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            await pilot.app.handle_command("/help")
            await pilot.pause()

            styles = pilot.app.screen.styles

            assert styles.align_horizontal == "center"
            assert styles.align_vertical == "middle"

    asyncio.run(run())


def test_startup_splash_is_mounted_before_background_startup_finishes():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            splash = pilot.app.query_one("#startup-splash", Static)
            composer = pilot.app.query_one(ComposerTextArea)
            assert "Dmitry Soshnikov" in splash.content.plain
            assert "SHWARSICO Vibe Coding Dept" in splash.content.plain
            assert "/::\\____\\" in splash.content.plain
            assert "\\/____/" in splash.content.plain
            assert not composer.has_class("ready")
            assert pilot.app.focused is not composer

    asyncio.run(run())


def test_startup_prefers_simple_agent_when_available(tmp_path):
    async def run() -> None:
        agents_dir = tmp_path / "agents"
        for name in ["data_analyst", "simple"]:
            agent_dir = agents_dir / name
            agent_dir.mkdir(parents=True)
            (agent_dir / "main.py").write_text("agent = object()\n", encoding="utf-8")

        async with MaApp(config_path="missing.json", agents_dir=agents_dir).run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
                if pilot.app.active_agent is not None:
                    break

            assert pilot.app.active_agent is not None
            assert pilot.app.active_agent.name == "simple"

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


def test_reasoning_block_streams_text_as_it_arrives():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            transcript = pilot.app.query_one("#transcript")
            block = ReasoningBlock()
            await block.mount(transcript)

            block.append("First ")
            block.append("thought")

            assert isinstance(block.widget.content, Text)
            assert block.widget.content.plain == "First thought"
            assert str(block.widget.content.style) == "dim"

            block.finalize()

            assert isinstance(block.widget.content, RichMarkdown)
            assert block.widget.content.markup == "First thought"

    asyncio.run(run())


def test_reasoning_delta_text_detects_reasoning_delta_events():
    event = SimpleNamespace(type="response.reasoning_summary_text.delta", delta="thinking")
    other = SimpleNamespace(type="response.output_text.delta", delta="answer")

    assert reasoning_delta_text(event) == "thinking"
    assert reasoning_delta_text(other) == ""


def test_agent_log_renders_light_green_message():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            transcript = pilot.app.query_one("#transcript")

            pilot.app.log_agent_message("Checking source quality")
            await pilot.pause()

            log_widget = transcript.query_one(".agent-log", Static)
            assert isinstance(log_widget.content, Text)
            assert log_widget.content.plain == "Checking source quality"
            assert str(log_widget.content.style) == "light_green"

    asyncio.run(run())


def test_code_interpreter_item_renders_collapsed_code_and_dark_green_logs():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            raw = SimpleNamespace(
                type="code_interpreter_call",
                code="print('hello')",
                outputs=[SimpleNamespace(type="logs", logs="hello\n")],
            )

            assert pilot.app.render_code_interpreter_item(SimpleNamespace(raw_item=raw)) is True
            await pilot.pause()

            transcript = pilot.app.query_one("#transcript")
            code = transcript.query_one(Collapsible)
            output = transcript.query_one(".code-output", Static)

            assert code.collapsed is True
            assert "Code Interpreter code" in code.title
            assert isinstance(output.content, Text)
            assert output.content.plain == "hello\n"
            assert str(output.content.style) == "dark_green"

    asyncio.run(run())


def test_safe_download_path_avoids_collisions_and_strips_directories(tmp_path):
    (tmp_path / "chart.png").write_text("old", encoding="utf-8")

    path = safe_download_path(tmp_path, "../chart.png")

    assert path == tmp_path / "chart-1.png"


def test_collect_output_files_deduplicates_nested_annotations():
    item = {
        "content": [
            {"annotations": [{"file_id": "file-1", "filename": "a.csv"}]},
            {"annotations": [{"file_id": "file-1", "filename": "a.csv"}]},
            {"annotations": [{"file_id": "file-2", "filename": "b.png"}]},
        ]
    }

    assert collect_output_files(item) == [
        {"file_id": "file-1", "filename": "a.csv"},
        {"file_id": "file-2", "filename": "b.png"},
    ]


def test_result_file_sources_cover_all_final_result_surfaces():
    input_items = [{"annotations": [{"file_id": "file-input", "filename": "input.csv"}]}]
    result = SimpleNamespace(
        new_items=[{"annotations": [{"file_id": "file-new", "filename": "new.csv"}]}],
        raw_responses=[{"output": [{"annotations": [{"file_id": "file-raw", "filename": "raw.csv"}]}]}],
        final_output={"annotations": [{"file_id": "file-final", "filename": "final.csv"}]},
    )

    files = collect_output_files(result_file_sources(result, input_items))

    assert files == [
        {"file_id": "file-new", "filename": "new.csv"},
        {"file_id": "file-raw", "filename": "raw.csv"},
        {"file_id": "file-final", "filename": "final.csv"},
        {"file_id": "file-input", "filename": "input.csv"},
    ]


def test_download_policy_auto_skip_and_duplicate_tracking(tmp_path):
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            downloaded: list[tuple[str, str]] = []

            def fake_download(file_id: str, filename: str) -> DownloadResult:
                downloaded.append((file_id, filename))
                return DownloadResult(tmp_path / filename, saved=True)

            app.download_code_interpreter_file = fake_download
            app.download_mode = "auto"
            item = {"content": [{"annotations": [{"file_id": "file-1", "filename": "chart.png"}]}]}

            await app.handle_code_interpreter_files([item])
            await app.handle_code_interpreter_files([item])

            assert downloaded == [("file-1", "chart.png")]
            assert app.downloaded_file_ids == {"file-1"}

            app.download_mode = "skip"
            item2 = {"content": [{"annotations": [{"file_id": "file-2", "filename": "other.png"}]}]}
            await app.handle_code_interpreter_files([item2])

            assert downloaded == [("file-1", "chart.png")]
            assert app.downloaded_file_ids == {"file-1"}

    asyncio.run(run())


def test_download_all_requires_active_container():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            app.client = object()
            app.active_agent = LoadedAgent(
                name="plain",
                module=ModuleType("plain"),
                agent=object(),
                props={"display_name": "Plain"},
            )

            await app.handle_command("/download all")
            await pilot.pause()

            transcript = app.query_one("#transcript")
            assert any(
                "does not expose a Code Interpreter container" in str(child.content)
                for child in transcript.children
            )

    asyncio.run(run())


def test_download_all_downloads_container_files_and_skips_identical(tmp_path):
    async def run() -> None:
        class BinaryContent:
            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self) -> bytes:
                return self.data

        class ContentResource:
            @staticmethod
            def retrieve(file_id, container_id):
                assert container_id == "container-1"
                return BinaryContent({"file-1": b"same", "file-2": b"new"}[file_id])

        class FilesResource:
            content = ContentResource()

            @staticmethod
            def list(container_id, limit):
                assert container_id == "container-1"
                assert limit == 100
                return [
                    SimpleNamespace(id="file-1", path="/mnt/data/chart.png"),
                    SimpleNamespace(id="file-2", path="/mnt/data/report.txt"),
                ]

        class ContainersResource:
            files = FilesResource()

        cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_path)
            (tmp_path / "chart.png").write_bytes(b"same")

            async with MaApp(config_path="missing.json").run_test() as pilot:
                app = pilot.app
                app.client = SimpleNamespace(containers=ContainersResource())
                app.active_agent = LoadedAgent(
                    name="container",
                    module=ModuleType("container"),
                    agent=object(),
                    props={"display_name": "Container", "container_id": "container-1"},
                )

                await app.handle_command("/download all")
                await pilot.pause()

                assert (tmp_path / "chart.png").read_bytes() == b"same"
                assert (tmp_path / "report.txt").read_bytes() == b"new"
                assert app.downloaded_file_ids == {"file-1", "file-2"}
        finally:
            os.chdir(cwd)

    asyncio.run(run())


def test_write_downloaded_file_skips_same_name_size_and_checksum(tmp_path):
    existing = tmp_path / "chart.png"
    existing.write_bytes(b"same")

    skipped = write_downloaded_file(tmp_path, "../chart.png", b"same")
    changed = write_downloaded_file(tmp_path, "../chart.png", b"different")

    assert same_file_content(existing, b"same") is True
    assert skipped == DownloadResult(existing, saved=False)
    assert changed == DownloadResult(tmp_path / "chart-1.png", saved=True)
    assert (tmp_path / "chart-1.png").read_bytes() == b"different"


def test_download_ask_modal_returns_choice():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            task = asyncio.create_task(
                pilot.app.ask_download_files([{"file_id": "file-1", "filename": "chart.png"}])
            )
            await pilot.pause()

            await pilot.press("enter")

            assert await task is True

    asyncio.run(run())


def test_message_output_items_are_not_rendered_as_events():
    app = MaApp(config_path="missing.json")

    assert app.describe_run_item(SimpleNamespace(type="message_output_item")) is None


def test_tool_output_event_preserves_upload_container_path_without_markup():
    async def run() -> None:
        output = (
            '{"files": [{"name": "job_market_salary_trends.csv", "id": "file-1", '
            '"container_id": "container-1", "container_path": "/mnt/data/job_market_salary_trends.csv"}]}'
        )

        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            description = app.describe_run_item(SimpleNamespace(type="tool_call_output_item", output=output))

            assert description is not None
            assert "/mnt/data/job_market_salary_trends.csv" in description
            app.add_event(description)
            await pilot.pause()

            event = app.query_one(".event", Static)
            assert isinstance(event.content, Text)
            assert "[/dim]" not in event.content.plain
            assert "/mnt/data/job_market_salary_trends.csv" in event.content.plain

    asyncio.run(run())


def test_truncate_text_adds_ellipsis_only_when_needed():
    assert truncate_text("short", 10) == "short"
    assert truncate_text("abcdefghijklmnopqrstuvwxyz", 10) == "abcdefg..."


def test_reasoning_items_render_summary_text():
    item = SimpleNamespace(
        type="reasoning_item",
        raw_item=SimpleNamespace(
            type="reasoning",
            summary=[SimpleNamespace(text="Need to compare the uploaded tables.")],
        ),
    )
    app = MaApp(config_path="missing.json")

    assert reasoning_item_text(item) == "Need to compare the uploaded tables."
    assert app.describe_run_item(item) == "Reasoning: Need to compare the uploaded tables."
    assert should_skip_completed_reasoning(item, "Need to compare the uploaded tables.") is True
    assert should_skip_completed_reasoning(item, "") is False


def test_status_header_displays_agent_status_and_metadata():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            for _ in range(10):
                await pilot.pause()
                if not app.starting:
                    break
            app.active_agent = LoadedAgent(
                name="sample",
                module=ModuleType("sample"),
                agent=object(),
                props={"display_name": "Sample"},
            )
            app.set_agent_status("Working")
            await pilot.pause()

            status = app.query_one("#status-header", Static).content

            assert isinstance(status, Text)
            assert "● Working" in status.plain
            assert "Agent: Sample" in status.plain
            assert "Reasoning: Agent Default" in status.plain
            assert any(str(span.style) == "light_green" for span in status.spans)

    asyncio.run(run())


def test_apply_context_includes_log_and_clarification_tools():
    async def run() -> None:
        captured_context = None

        class Module:
            @staticmethod
            def set_context(context):
                nonlocal captured_context
                captured_context = context

        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            app.clarification_tools = ["clarify"]
            app.client = "sync-client"
            app.aclient = "async-client"
            app.dotenv_values = {"AGENT_SETTING": "from-dotenv"}
            app.active_agent = LoadedAgent(
                name="context",
                module=Module(),
                agent=object(),
                props={"display_name": "Context"},
            )

            app.apply_context()

            assert captured_context is not None
            assert captured_context.log == app.log_agent_message
            assert captured_context.clarification_tools == ["clarify"]
            assert captured_context.client == "sync-client"
            assert captured_context.aclient == "async-client"
            assert captured_context.env == {"AGENT_SETTING": "from-dotenv"}

    asyncio.run(run())


def test_app_loads_current_directory_dotenv_into_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OVERRIDDEN_SETTING", "inherited")
    (tmp_path / ".env").write_text(
        'OVERRIDDEN_SETTING=from-dotenv\nQUOTED_SETTING="quoted value"\n',
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text('{"models": []}', encoding="utf-8")

    app = MaApp(config_path=config_path, settings_file=tmp_path / "ma.ini")

    assert app.dotenv_values == {
        "OVERRIDDEN_SETTING": "from-dotenv",
        "QUOTED_SETTING": "quoted value",
    }
    assert os.environ["OVERRIDDEN_SETTING"] == "from-dotenv"
    assert os.environ["QUOTED_SETTING"] == "quoted value"

    captured_context = None

    class Module:
        @staticmethod
        def set_context(context):
            nonlocal captured_context
            captured_context = context

    app.active_agent = LoadedAgent(
        name="dotenv",
        module=Module(),
        agent=object(),
        props={"display_name": "Dotenv"},
    )
    app.apply_context()

    assert captured_context is not None
    assert captured_context.env == app.dotenv_values


def test_app_uses_empty_dotenv_mapping_when_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text('{"models": []}', encoding="utf-8")

    app = MaApp(config_path=config_path, settings_file=tmp_path / "ma.ini")

    assert app.dotenv_values == {}


def test_save_session_command_writes_session_and_palette_action_prefills_composer(tmp_path):
    async def run() -> None:
        path = tmp_path / "session.json"
        async with MaApp(config_path="missing.json").run_test() as pilot:
            app = pilot.app
            app.record_session_event("user", "Hello")
            app.record_session_event("tool_output", "Full tool output")
            await app.handle_command(f"/save {path}")

            assert path.exists()
            assert '"tool_output"' in path.read_text(encoding="utf-8")

            app.action_save_session_output()
            composer = app.query_one(ComposerTextArea)
            assert composer.text == "/save "

    asyncio.run(run())


def test_clarification_modal_returns_selected_option():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            task = asyncio.create_task(
                pilot.app.ask_user_clarification(
                    "Pick one",
                    [{"title": "A", "detail": "First"}, {"title": "B", "detail": "Second"}],
                )
            )
            await pilot.pause()

            screen = pilot.app.screen
            assert isinstance(screen, ClarificationScreen)
            assert screen.question == "Pick one"
            assert len(screen.query_one("#clarification-options", ListView).children) == 2

            await pilot.press("enter")
            result = await task

            assert result == {"title": "A", "detail": "First"}

    asyncio.run(run())


def test_clarification_modal_returns_custom_answer():
    async def run() -> None:
        async with MaApp(config_path="missing.json").run_test() as pilot:
            task = asyncio.create_task(
                pilot.app.ask_user_clarification(
                    "Pick one",
                    [{"title": "A", "detail": "First"}],
                    allow_custom_answer=True,
                )
            )
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            screen = pilot.app.screen
            assert isinstance(screen, ClarificationScreen)
            custom_answer = screen.query_one("#custom-answer")
            custom_answer.value = "Something else"
            screen.submit_custom_answer()

            result = await task

            assert result == {"title": "Own answer", "detail": "Something else"}

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
            for _ in range(5):
                await pilot.pause()
                if not app.starting:
                    break
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
