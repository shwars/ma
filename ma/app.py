from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import time
from os.path import commonprefix
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Footer, Input, Label, ListItem, ListView, Static, TextArea
from openai.types.responses import ResponseTextDeltaEvent
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text

from .agent_loader import AgentLoader, LoadedAgent
from .config import AppConfig, ModelChoice, load_config
from .context import AgentContext
from .runtime import build_clients, build_model
from .stores import Note, NotesStore, TodoItem, TodoStore
from .tools import build_clarification_tools, build_notes_tools, build_todo_tools

REASONING_CHOICES: list[tuple[str, str]] = [
    ("agent_default", "Agent Default"),
    ("none", "None"),
    ("minimal", "Minimal"),
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra High"),
]

COMMAND_COMPLETIONS = [
    "/agent",
    "/download",
    "/download auto",
    "/download ask",
    "/download skip",
    "/help",
    "/model",
    "/new",
    "/reasoning",
    "/reasoning agent_default",
    "/reasoning none",
    "/reasoning minimal",
    "/reasoning low",
    "/reasoning medium",
    "/reasoning high",
    "/reasoning xhigh",
    "/reload",
    "/theme",
    "/notes save",
    "/notes clear",
    "/exit",
]

DOWNLOAD_MODES = {"auto", "ask", "skip"}
AGENT_STATUS_STYLES = {
    "Ready": "white",
    "Working": "light_green",
    "Needs input": "dodger_blue1",
    "Executing code": "yellow",
}


@dataclasses.dataclass(frozen=True)
class DownloadResult:
    path: Path
    saved: bool


def safe_download_path(directory: Path, filename: str) -> Path:
    clean_name = Path(filename).name or "downloaded-file"
    candidate = directory / clean_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem or "downloaded-file"
    suffix = candidate.suffix
    index = 1
    while True:
        next_candidate = directory / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def same_file_content(path: Path, data: bytes) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size != len(data):
        return False
    return hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()


def write_downloaded_file(directory: Path, filename: str, data: bytes) -> DownloadResult:
    clean_name = Path(filename).name or "downloaded-file"
    direct_path = directory / clean_name
    if same_file_content(direct_path, data):
        return DownloadResult(direct_path, saved=False)

    path = safe_download_path(directory, filename)
    path.write_bytes(data)
    return DownloadResult(path, saved=True)


def _file_annotation_from_object(value: Any) -> dict[str, str] | None:
    file_id = getattr(value, "file_id", None)
    filename = getattr(value, "filename", None)
    if file_id and filename:
        return {"file_id": str(file_id), "filename": str(filename)}
    if isinstance(value, dict) and value.get("file_id") and value.get("filename"):
        return {"file_id": str(value["file_id"]), "filename": str(value["filename"])}
    return None


def collect_output_files(value: Any) -> list[dict[str, str]]:
    seen: set[str] = set()
    found: list[dict[str, str]] = []

    def visit(node: Any) -> None:
        annotation = _file_annotation_from_object(node)
        if annotation and annotation["file_id"] not in seen:
            seen.add(annotation["file_id"])
            found.append(annotation)
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                visit(child)
            return
        for attr in ("raw_item", "content", "annotations", "outputs", "output"):
            child = getattr(node, attr, None)
            if child is not None:
                visit(child)

    visit(value)
    return found


def is_code_interpreter_raw(raw: Any) -> bool:
    raw_type = str(getattr(raw, "type", "")).lower()
    return raw_type == "code_interpreter_call"


def code_interpreter_logs(raw: Any) -> str:
    lines: list[str] = []
    for output in getattr(raw, "outputs", None) or []:
        logs = getattr(output, "logs", None)
        if logs:
            lines.append(str(logs))
    return "\n".join(lines)


def reasoning_delta_text(event: Any) -> str:
    event_type = str(getattr(event, "type", "")).lower()
    if "reasoning" not in event_type or not event_type.endswith(".delta"):
        return ""
    return str(getattr(event, "delta", ""))


def is_reasoning_item(item: Any) -> bool:
    item_type = str(getattr(item, "type", "")).lower()
    raw_type = str(getattr(getattr(item, "raw_item", None), "type", "")).lower()
    return "reasoning" in item_type or "reasoning" in raw_type


def reasoning_item_text(item: Any) -> str:
    pieces: list[str] = []
    seen: set[int] = set()

    def visit(value: Any) -> None:
        if value is None:
            return
        value_id = id(value)
        if value_id in seen:
            return
        seen.add(value_id)
        if isinstance(value, str):
            text = value.strip()
            if text:
                pieces.append(text)
            return
        if isinstance(value, dict):
            for key in ("text", "content", "summary", "reasoning"):
                visit(value.get(key))
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
            return
        for attr in ("text", "content", "summary", "reasoning"):
            visit(getattr(value, attr, None))

    visit(item)
    visit(getattr(item, "raw_item", None))
    unique = list(dict.fromkeys(piece for piece in pieces if piece))
    return "\n".join(unique)


def _normalized_reasoning(text: str) -> str:
    return " ".join(text.split())


def should_skip_completed_reasoning(item: Any, streamed_reasoning_text: str) -> bool:
    if not is_reasoning_item(item):
        return False
    streamed = _normalized_reasoning(streamed_reasoning_text)
    if not streamed:
        return False
    completed = _normalized_reasoning(reasoning_item_text(item))
    return not completed or completed in streamed or streamed in completed


class PickerScreen(ModalScreen[str | None]):
    def __init__(self, title: str, choices: list[tuple[str, str]]) -> None:
        super().__init__()
        self.title = title
        self.choices = choices
        self.choice_values = {f"choice-{index}": value for index, (value, _) in enumerate(choices)}

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(self.title, id="picker-title")
            items = [ListItem(Label(label), id=f"choice-{index}") for index, (_, label) in enumerate(self.choices)]
            yield ListView(*items, id="picker-list")

    def on_mount(self) -> None:
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(self.choice_values.get(event.item.id or ""))

    def key_escape(self) -> None:
        self.dismiss(None)


class NoteDetailScreen(ModalScreen[None]):
    def __init__(self, note: Note) -> None:
        super().__init__()
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(id="note-detail"):
            yield Label(f"{self.note.category} - {self.note.title}", id="note-detail-title")
            lines = []
            if self.note.url:
                lines.append(f"URL: {self.note.url}")
                lines.append("")
            lines.append(self.note.body)
            if self.note.extra:
                lines.append("")
                for key, value in self.note.extra.items():
                    lines.append(f"{key}: {value}")
            yield VerticalScroll(Static("\n".join(lines)), id="note-detail-body")

    def key_escape(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    def compose(self) -> ComposeResult:
        help_text = "\n".join(
            [
                "Commands",
                "",
                "/agent [name]       Select the active agent.",
                "/model [model]      Select the active model.",
                "/reasoning [level]  Set reasoning level for the current model.",
                "/theme [name]       Select the Textual UI theme.",
                "/download [mode]    Set Code Interpreter file downloads: auto, ask, skip.",
                "/new                Start a new chat session and clear session state.",
                "/reload             Reload agents from disk.",
                "/notes save         Save current notes to a markdown file.",
                "/notes clear        Clear current notes.",
                "/help               Show this help.",
                "/exit               Exit the app.",
                "",
                "Enter sends a message. Ctrl+Enter inserts a newline. Tab completes slash commands.",
            ]
        )
        with Vertical(id="help"):
            yield Label("Help", id="help-title")
            yield Static(help_text, id="help-body")

    def key_escape(self) -> None:
        self.dismiss(None)


class ClarificationScreen(ModalScreen[dict[str, str]]):
    def __init__(
        self,
        question: str,
        options: list[dict[str, str]],
        allow_custom_answer: bool = False,
    ) -> None:
        super().__init__()
        self.question = question
        self.options = options
        self.allow_custom_answer = allow_custom_answer
        self.option_by_id = {f"clarification-option-{index}": option for index, option in enumerate(options)}

    def compose(self) -> ComposeResult:
        with Vertical(id="clarification"):
            yield Label(self.question, id="clarification-question")
            items: list[ListItem] = []
            for index, option in enumerate(self.options):
                items.append(
                    ListItem(
                        Label(f"{option['title']}\n{option['detail']}"),
                        id=f"clarification-option-{index}",
                    )
                )
            if self.allow_custom_answer:
                items.append(ListItem(Label("Own answer\nType a custom response."), id="clarification-custom"))
            yield ListView(*items, id="clarification-options")
            if self.allow_custom_answer:
                yield Input(placeholder="Type your answer", id="custom-answer")
                yield Button("Use own answer", id="custom-submit")

    def on_mount(self) -> None:
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        widget_id = event.item.id or ""
        if widget_id == "clarification-custom":
            answer = self.query_one("#custom-answer", Input)
            submit = self.query_one("#custom-submit", Button)
            answer.add_class("visible")
            submit.add_class("visible")
            answer.focus()
            return
        option = self.option_by_id.get(widget_id)
        if option is not None:
            self.dismiss(option)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "custom-answer":
            self.submit_custom_answer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "custom-submit":
            self.submit_custom_answer()

    def submit_custom_answer(self) -> None:
        answer = self.query_one("#custom-answer", Input).value.strip()
        if answer:
            self.dismiss({"title": "Own answer", "detail": answer})

    def key_escape(self) -> None:
        self.dismiss({"title": "Cancelled", "detail": "User cancelled clarification."})


class DownloadFilesScreen(ModalScreen[bool]):
    def __init__(self, files: list[dict[str, str]]) -> None:
        super().__init__()
        self.files = files

    def compose(self) -> ComposeResult:
        with Vertical(id="download-files"):
            yield Label("Download Code Interpreter files?", id="download-files-title")
            lines = [f"- {file['filename']}" for file in self.files]
            yield Static("\n".join(lines), id="download-files-list")
            with Horizontal(id="download-files-actions"):
                yield Button("Download", id="download-yes", variant="success")
                yield Button("Skip", id="download-no")

    def on_mount(self) -> None:
        self.query_one("#download-yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-yes":
            self.dismiss(True)
        elif event.button.id == "download-no":
            self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)


class ComposerTextArea(TextArea):
    async def _on_key(self, event) -> None:
        if event.key == "escape" and self.app.handle_escape_interrupt():
            event.stop()
            event.prevent_default()
            return
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self.app.complete_command()
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.app.run_worker(self.app.submit_composer())
            return
        if event.key == "ctrl+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


class AssistantBlock:
    def __init__(self) -> None:
        self.widget = Static("", classes="assistant-message")
        self.parts: list[str] = []
        self.finalized = False

    @property
    def text(self) -> str:
        return "".join(self.parts)

    async def mount(self, parent: VerticalScroll) -> None:
        await parent.mount(self.widget)

    def append(self, delta: str) -> None:
        if self.finalized:
            return
        self.parts.append(delta)
        self.widget.update(Text(self.text))

    def finalize(self) -> None:
        if self.finalized:
            return
        self.finalized = True
        if self.text.strip():
            self.widget.update(RichMarkdown(self.text))


class ReasoningBlock:
    def __init__(self) -> None:
        self.widget = Static("", classes="reasoning-message")
        self.parts: list[str] = []
        self.finalized = False

    @property
    def text(self) -> str:
        return "".join(self.parts)

    async def mount(self, parent: VerticalScroll) -> None:
        await parent.mount(self.widget)

    def append(self, delta: str) -> None:
        if self.finalized:
            return
        self.parts.append(delta)
        text = Text(style="dim")
        text.append(self.text)
        self.widget.update(text)

    def finalize(self) -> None:
        if self.finalized:
            return
        self.finalized = True
        if self.text.strip():
            self.widget.update(RichMarkdown(self.text, style="dim"))


def render_todo_items(items: list[TodoItem]) -> Text:
    todos = Text(no_wrap=True)
    for index, item in enumerate(items):
        if index:
            todos.append("\n")
        marker = "☑" if item.done else "☐"
        style = "light_green" if item.done else None
        todos.append(f"{marker} {item.title}", style=style)
    return todos


def command_completion_matches(text: str, commands: list[str] | None = None) -> list[str]:
    if "\n" in text or not text.startswith("/"):
        return []
    command_list = commands or COMMAND_COMPLETIONS
    query = text.lower()
    return [command for command in command_list if command.lower().startswith(query)]


def complete_command_text(text: str, commands: list[str] | None = None) -> str:
    matches = command_completion_matches(text, commands)
    if not matches:
        return text
    if len(matches) == 1:
        return matches[0]
    completion = commonprefix(matches)
    return completion if len(completion) > len(text) else text


def render_command_hint(text: str, commands: list[str] | None = None) -> Text:
    hint = Text(style="dim")
    matches = command_completion_matches(text, commands)
    if not matches:
        return hint
    if len(matches) == 1:
        command = matches[0]
        if command == text:
            hint.append("Press Enter to run command")
        else:
            hint.append(text)
            hint.append(command[len(text) :], style="dim italic")
        return hint
    hint.append("Tab: ")
    hint.append("  ".join(matches[:5]))
    if len(matches) > 5:
        hint.append(f"  +{len(matches) - 5} more")
    return hint


def startup_splash() -> Text:
    art = r"""
              _   _              ___
             μ μ μ μ            / _ \
            μ   μ   μ          / /_\ \
           μ    μ    μ        /  _  \
          μ     μ     μ      /_/   \_\

                 μA

        (C) 2026 Dmitry Soshnikov
        (C) 2026 SHWARSICO Vibe Coding Dept
    """
    return Text(art.strip("\n"), style="bold cyan")


class MaApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    PickerScreen, NoteDetailScreen, HelpScreen, ClarificationScreen, DownloadFilesScreen {
        align: center middle;
    }

    #status-header {
        height: 1;
        background: $boost;
        padding-left: 1;
    }

    #body {
        height: 1fr;
    }

    #main {
        width: 1fr;
    }

    #transcript {
        height: 1fr;
        border: round $primary;
        padding: 1;
    }

    #side {
        width: 38;
        display: none;
    }

    #side.visible {
        display: block;
    }

    #notes-pane, #todo-pane {
        display: none;
        border: round $accent;
        padding: 1;
        height: 1fr;
    }

    #notes-pane.visible, #todo-pane.visible {
        display: block;
    }

    #composer {
        display: none;
        height: 4;
        border: round $primary;
    }

    #composer.ready {
        display: block;
    }

    #completion-hint {
        display: none;
        height: 1;
        padding-left: 1;
        color: $text-muted;
    }

    #completion-hint.visible {
        display: block;
    }

    .startup-splash {
        content-align: center middle;
        height: 1fr;
    }

    .message {
        margin-bottom: 1;
    }

    .user-message {
        color: yellow;
        margin-bottom: 1;
    }

    .assistant-message {
        color: white;
        margin-bottom: 1;
    }

    .reasoning-message {
        color: $text-muted;
        margin-bottom: 1;
    }

    .event {
        color: $text-muted;
    }

    #picker {
        width: 60;
        height: auto;
        max-height: 24;
        border: round $primary;
        background: $surface;
        padding: 1;
    }

    #picker-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #note-detail {
        width: 72;
        height: 24;
        border: round $primary;
        background: $surface;
        padding: 1;
    }

    #note-detail-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #note-detail-body {
        height: 1fr;
    }

    #help {
        width: 76;
        height: auto;
        max-height: 28;
        border: round $primary;
        background: $surface;
        padding: 1;
    }

    #help-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #clarification {
        width: 72;
        height: auto;
        max-height: 28;
        border: round $primary;
        background: $surface;
        padding: 1;
    }

    #clarification-question {
        text-style: bold;
        margin-bottom: 1;
    }

    #clarification-options {
        height: auto;
        max-height: 14;
        margin-bottom: 1;
    }

    #download-files {
        width: 64;
        height: auto;
        max-height: 24;
        border: round $primary;
        background: $surface;
        padding: 1;
    }

    #download-files-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #download-files-list {
        margin-bottom: 1;
    }

    #download-files-actions {
        height: auto;
    }

    #custom-answer, #custom-submit {
        display: none;
    }

    #custom-answer.visible, #custom-submit.visible {
        display: block;
    }

    .notes-list {
        height: 1fr;
    }

    .todo-list {
        width: auto;
    }

    .agent-log {
        color: lightgreen;
        margin-bottom: 1;
    }

    .code-output {
        color: darkgreen;
        margin-bottom: 1;
    }

    .code-block {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+r", "reload_agents", "Reload"),
    ]

    def __init__(self, config_path: Path | None = None, agents_dir: Path | str = "agents") -> None:
        super().__init__()
        self.config: AppConfig = load_config(config_path)
        self.loader = AgentLoader(agents_dir)
        self.notes_store = NotesStore()
        self.todo_store = TodoStore()
        self.notes_tools: list[Any] = []
        self.todo_tools: list[Any] = []
        self.clarification_tools: list[Any] = []
        self.agent_names: list[str] = []
        self.active_agent: LoadedAgent | None = None
        self.selected_model: ModelChoice | None = self._initial_model_choice()
        self.selected_model_object: Any = None
        self.client: Any = None
        self.aclient: Any = None
        self.reasoning_by_model_id: dict[str, str | None] = {}
        self.side_refresh_index = 0
        self.history: list[Any] = []
        self.busy = False
        self.starting = True
        self.download_mode = "ask"
        self.downloaded_file_ids: set[str] = set()
        self.agent_status = "Ready"
        self.active_run_worker: Any = None
        self.last_escape_at = 0.0
        self.interrupt_requested = False

    def _initial_model_choice(self) -> ModelChoice | None:
        return next(
            (model for model in self.config.models if not model.is_agent_default),
            self.config.models[0] if self.config.models else None,
        )

    def compose(self) -> ComposeResult:
        yield Static("", id="status-header")
        with Horizontal(id="body"):
            with Vertical(id="main"):
                with VerticalScroll(id="transcript"):
                    yield Static(startup_splash(), id="startup-splash", classes="startup-splash")
            with Vertical(id="side"):
                yield VerticalScroll(id="notes-pane")
                yield HorizontalScroll(id="todo-pane")
        yield Static("", id="completion-hint")
        yield ComposerTextArea(
            "",
            placeholder="Message, or /agent /model /theme /download /reasoning /new /help /exit",
            id="composer",
            show_line_numbers=False,
            soft_wrap=True,
            disabled=True,
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "ma"
        self.update_status_header()
        self.call_after_refresh(self.start_background_startup)

    def start_background_startup(self) -> None:
        self.run_worker(self.finish_startup(), exclusive=True)

    async def finish_startup(self) -> None:
        self.notes_tools = build_notes_tools(self.notes_store)
        self.todo_tools = build_todo_tools(self.todo_store)
        self.clarification_tools = build_clarification_tools(self.ask_user_clarification)
        self.client, self.aclient = build_clients(self.config)
        self.selected_model_object = build_model(self.config, self.selected_model)
        await self.reload_agents()
        self.refresh_side()
        self.starting = False
        splash = self.query("#startup-splash")
        if splash:
            splash.first().remove()
        composer = self.query_one(ComposerTextArea)
        composer.disabled = False
        composer.add_class("ready")
        composer.focus()
        self.set_agent_status("Ready")

    def set_agent_status(self, status: str) -> None:
        self.agent_status = status
        self.update_status_header()

    def update_status_header(self) -> None:
        header = self.query("#status-header")
        if not header:
            return
        style = AGENT_STATUS_STYLES.get(self.agent_status, "white")
        agent = self.active_agent.display_name if self.active_agent else "No agent"
        model = self.selected_model.display_name if self.selected_model else "No model"
        reasoning = self.reasoning_display_name()
        status = Text()
        status.append(f"● {self.agent_status}", style=style)
        status.append(
            f"  ma  Agent: {agent}  Model: {model}  Reasoning: {reasoning}  Download: {self.download_mode}",
            style="white",
        )
        header.first().update(status)

    def reasoning_display_name(self) -> str:
        if not self.selected_model:
            return "Agent Default"
        level = self.reasoning_by_model_id.get(self.selected_model.id)
        value = "agent_default" if level is None else level
        return next(label for choice, label in REASONING_CHOICES if choice == value)

    def complete_command(self) -> None:
        composer = self.query_one("#composer", ComposerTextArea)
        completed = complete_command_text(composer.text, self.command_completions())
        if completed != composer.text:
            composer.load_text(completed)
            composer.move_cursor((0, len(completed)))
        self.update_command_hint()

    def update_command_hint(self) -> None:
        composer = self.query_one("#composer", ComposerTextArea)
        hint_widget = self.query_one("#completion-hint", Static)
        hint = render_command_hint(composer.text, self.command_completions())
        hint_widget.update(hint)
        hint_widget.set_class(bool(hint.plain), "visible")

    def command_completions(self) -> list[str]:
        commands = list(COMMAND_COMPLETIONS)
        for name in self.agent_names:
            commands.append(f"/agent {name}")
            try:
                display_name = self.loader.load(name).display_name
            except Exception:
                display_name = ""
            if display_name and display_name.lower() != name.lower():
                commands.append(f"/agent {display_name}")
        for model in self.config.models:
            commands.append(f"/model {model.id}")
            if model.display_name and model.display_name.lower() != model.id.lower():
                commands.append(f"/model {model.display_name}")
        for theme_name in self.theme_names():
            commands.append(f"/theme {theme_name}")
        return sorted(dict.fromkeys(commands), key=str.lower)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "composer":
            self.update_command_hint()

    async def submit_composer(self) -> None:
        composer = self.query_one("#composer", TextArea)
        text = composer.text.strip()
        composer.load_text("")
        if not text:
            return
        if text.startswith("/"):
            await self.handle_command(text)
            return
        self.active_run_worker = self.run_chat(text)

    def key_escape(self) -> None:
        self.handle_escape_interrupt()

    def handle_escape_interrupt(self, now: float | None = None) -> bool:
        if not self.busy or self.active_run_worker is None:
            return False

        current_time = time.monotonic() if now is None else now
        if current_time - self.last_escape_at <= 2.0:
            self.interrupt_requested = True
            self.last_escape_at = 0.0
            self.add_event("Interrupt requested.")
            self.active_run_worker.cancel()
            return True

        self.last_escape_at = current_time
        self.add_event("Press Esc again to interrupt the current run.")
        return True

    async def handle_command(self, text: str) -> None:
        stripped = text.strip()
        command = stripped.lower()
        if command == "/agent":
            await self.choose_agent()
        elif command.startswith("/agent "):
            await self.switch_agent_by_query(stripped.split(maxsplit=1)[1])
        elif command == "/model":
            await self.choose_model()
        elif command.startswith("/model "):
            self.switch_model_by_query(stripped.split(maxsplit=1)[1])
        elif command == "/download":
            await self.choose_download_mode()
        elif command.startswith("/download "):
            self.switch_download_mode(command.split(maxsplit=1)[1])
        elif command == "/theme":
            await self.choose_theme()
        elif command.startswith("/theme "):
            self.switch_theme(stripped.split(maxsplit=1)[1])
        elif command == "/help":
            await self.show_help()
        elif command == "/new":
            self.new_session()
        elif command == "/reasoning":
            await self.choose_reasoning()
        elif command.startswith("/reasoning "):
            self.switch_reasoning(command.split(maxsplit=1)[1])
        elif command == "/reload":
            await self.reload_agents()
        elif command in {"/exit", "/quit"}:
            self.exit()
        elif command == "/notes clear":
            self.clear_notes()
        elif command == "/notes save":
            self.save_notes()
        else:
            self.add_event(f"Unknown command: {text}")

    async def choose_agent(self) -> None:
        if not self.agent_names:
            self.add_event("No agents found under agents/.")
            return
        choices = [(name, self.loader.load(name).display_name) for name in self.agent_names]
        await self._push_picker("Select agent", choices, self.switch_agent)

    async def choose_model(self) -> None:
        if not self.config.models:
            self.add_event("No models configured. Add config.json or set Yandex env vars.")
            return
        choices = [(model.id, model.display_name) for model in self.config.models]
        await self._push_picker("Select model", choices, self.switch_model)

    async def choose_reasoning(self) -> None:
        await self._push_picker("Select reasoning", REASONING_CHOICES, self.switch_reasoning)

    async def choose_download_mode(self) -> None:
        await self._push_picker(
            "Select download mode",
            [
                ("ask", "Ask before downloading"),
                ("auto", "Download automatically"),
                ("skip", "Skip downloads"),
            ],
            self.switch_download_mode,
        )

    async def choose_theme(self) -> None:
        choices = [(name, name) for name in self.theme_names()]
        await self._push_picker("Select theme", choices, self.switch_theme)

    def theme_names(self) -> list[str]:
        return sorted(self.available_themes.keys(), key=str.lower)

    async def show_help(self) -> None:
        await self.push_screen(HelpScreen())

    async def _push_picker(
        self,
        title: str,
        choices: list[tuple[str, str]],
        callback: Callable[[str], Any],
    ) -> None:
        def done(value: str | None) -> None:
            if value is not None:
                result = callback(value)
                if asyncio.iscoroutine(result):
                    self.run_worker(result)

        self.push_screen(PickerScreen(title, choices), done)

    async def reload_agents(self) -> None:
        self.agent_names = self.loader.discover()
        if not self.agent_names:
            self.active_agent = None
            self.add_event("No agents found under agents/.")
            self.update_status_header()
            return

        active_name = self.active_agent.name if self.active_agent else (
            "simple" if "simple" in self.agent_names else self.agent_names[0]
        )
        if active_name not in self.agent_names:
            active_name = self.agent_names[0]
        await self.switch_agent(active_name, announce=False)
        self.add_event(f"Loaded agents: {', '.join(self.agent_names)}.")

    async def switch_agent(self, name: str, announce: bool = True) -> None:
        self.active_agent = self.loader.load(name)
        self.apply_context()
        self.history.clear()
        if announce:
            self.add_event(f"Active agent: {self.active_agent.display_name}.")
        self.refresh_side()
        self.update_status_header()

    async def switch_agent_by_query(self, query: str) -> None:
        normalized = query.strip().lower()
        for name in self.agent_names:
            loaded = self.loader.load(name)
            if normalized in {name.lower(), loaded.display_name.lower()}:
                await self.switch_agent(name)
                return
        self.add_event(f"Unknown agent: {query}")

    def switch_model(self, model_id: str) -> None:
        self.selected_model = next((model for model in self.config.models if model.id == model_id), None)
        self.selected_model_object = build_model(self.config, self.selected_model)
        if self.selected_model:
            self.add_event(f"Active model: {self.selected_model.display_name}.")
        self.apply_context()
        self.update_status_header()

    def switch_model_by_query(self, query: str) -> None:
        normalized = query.strip().lower()
        for model in self.config.models:
            if normalized in {model.id.lower(), model.display_name.lower()}:
                self.switch_model(model.id)
                return
        self.add_event(f"Unknown model: {query}")

    def switch_reasoning(self, reasoning_level: str) -> None:
        normalized = reasoning_level.strip().lower().replace("-", "_").replace(" ", "_")
        valid_levels = {value for value, _ in REASONING_CHOICES}
        if normalized not in valid_levels:
            self.add_event(f"Unknown reasoning level: {reasoning_level}")
            return
        if not self.selected_model:
            self.add_event("No active model.")
            return

        level = None if normalized == "agent_default" else normalized
        self.reasoning_by_model_id[self.selected_model.id] = level
        label = next(label for value, label in REASONING_CHOICES if value == normalized)
        self.add_event(f"Reasoning for {self.selected_model.display_name}: {label}.")
        self.apply_context()
        self.update_status_header()

    def switch_download_mode(self, mode: str) -> None:
        normalized = mode.strip().lower()
        if normalized not in DOWNLOAD_MODES:
            self.add_event(f"Unknown download mode: {mode}")
            return
        self.download_mode = normalized
        self.add_event(f"Download mode: {normalized}.")
        self.update_status_header()

    def switch_theme(self, theme_name: str) -> None:
        normalized = theme_name.strip()
        match = next((name for name in self.theme_names() if name.lower() == normalized.lower()), None)
        if match is None:
            self.add_event(f"Unknown theme: {theme_name}")
            return
        self.theme = match
        self.add_event(f"Theme: {match}.")

    def new_session(self) -> None:
        if self.busy:
            self.add_event("Cannot start a new session while a run is active.")
            return
        self.history.clear()
        self.notes_store.clear()
        self.todo_store.clear()
        self.downloaded_file_ids.clear()
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.remove_children()
        self.refresh_side()
        self.add_event("Started a new chat session.")
        self.set_agent_status("Ready")

    @property
    def selected_reasoning_level(self) -> str | None:
        if not self.selected_model:
            return None
        return self.reasoning_by_model_id.get(self.selected_model.id)

    def apply_context(self) -> None:
        if not self.active_agent:
            return
        context = AgentContext(
            config=self.config,
            selected_model=self.selected_model,
            model=self.selected_model_object,
            reasoning_level=self.selected_reasoning_level,
            folder_id=self.config.folder_id,
            api_key=self.config.api_key,
            client=self.client,
            aclient=self.aclient,
            notes_store=self.notes_store,
            todo_store=self.todo_store,
            notes_tools=self.notes_tools,
            todo_tools=self.todo_tools,
            clarification_tools=self.clarification_tools,
            log=self.log_agent_message,
        )
        self.active_agent.set_context(context)

    def action_reload_agents(self) -> None:
        self.run_worker(self.reload_agents())

    def action_choose_agent(self) -> None:
        self.run_worker(self.choose_agent())

    def action_choose_model(self) -> None:
        self.run_worker(self.choose_model())

    def action_choose_reasoning(self) -> None:
        self.run_worker(self.choose_reasoning())

    def action_choose_download_mode(self) -> None:
        self.run_worker(self.choose_download_mode())

    def action_choose_theme(self) -> None:
        self.run_worker(self.choose_theme())

    def action_show_help(self) -> None:
        self.run_worker(self.show_help())

    def action_new_session(self) -> None:
        self.new_session()

    def action_save_notes(self) -> None:
        self.save_notes()

    def action_clear_notes(self) -> None:
        self.clear_notes()

    def get_system_commands(self, screen) -> Iterable[SystemCommand]:
        yield SystemCommand("Agent", "Select the active agent", self.action_choose_agent)
        yield SystemCommand("Model", "Select the active model", self.action_choose_model)
        yield SystemCommand("Reasoning", "Set reasoning level for the current model", self.action_choose_reasoning)
        yield SystemCommand("Theme", "Select the UI theme", self.action_choose_theme)
        yield SystemCommand("Download", "Set Code Interpreter file download mode", self.action_choose_download_mode)
        yield SystemCommand("New", "Start a new chat session", self.action_new_session)
        yield SystemCommand("Help", "Show available commands", self.action_show_help)
        yield SystemCommand("Reload", "Reload agents from disk", self.action_reload_agents)
        yield SystemCommand("Notes Save", "Save session notes to markdown", self.action_save_notes)
        yield SystemCommand("Notes Clear", "Clear session notes", self.action_clear_notes)
        yield SystemCommand("Exit", "Exit the application", self.action_quit)
        for command in super().get_system_commands(screen):
            if command.title not in {"Quit", "Theme", "Change Theme"}:
                yield command

    def save_notes(self) -> None:
        path = Path.cwd() / f"notes-{datetime.now():%Y%m%d-%H%M%S}.md"
        self.notes_store.save_markdown(path)
        self.add_event(f"Saved notes to {path}.")

    def clear_notes(self) -> None:
        count = self.notes_store.clear()
        self.add_event(f"Cleared {count} notes.")
        self.refresh_side()

    @work(exclusive=True)
    async def run_chat(self, text: str) -> None:
        if self.busy:
            self.add_event("A run is already active.")
            self.active_run_worker = None
            return
        if not self.active_agent:
            self.add_event("No active agent.")
            self.active_run_worker = None
            return
        use_agent_default = bool(self.selected_model and self.selected_model.is_agent_default)
        if not use_agent_default and self.selected_model_object is None:
            self.add_event("No model is ready. Configure folder_id/api_key and at least one model.")
            self.active_run_worker = None
            return

        self.busy = True
        self.set_agent_status("Working")
        user_widget = Static(text, classes="user-message")
        transcript = self.query_one("#transcript", VerticalScroll)
        await transcript.mount(user_widget)
        transcript.scroll_end(animate=False)

        current_assistant_block: AssistantBlock | None = None
        current_reasoning_block: ReasoningBlock | None = None

        try:
            if not use_agent_default:
                setattr(self.active_agent.agent, "model", self.selected_model_object)
            self.apply_reasoning_settings()
            run_input = self.history + [{"role": "user", "content": text}]
            assistant_text_parts: list[str] = []
            streamed_reasoning_parts: list[str] = []

            from agents import Runner

            result = Runner.run_streamed(self.active_agent.agent, run_input)
            async for stream_event in result.stream_events():
                if stream_event.type == "raw_response_event" and isinstance(
                    stream_event.data, ResponseTextDeltaEvent
                ):
                    if current_reasoning_block is not None:
                        current_reasoning_block.finalize()
                        current_reasoning_block = None
                    delta = getattr(stream_event.data, "delta", "")
                    if delta and (current_assistant_block is not None or delta.strip()):
                        if current_assistant_block is None:
                            current_assistant_block = AssistantBlock()
                            await current_assistant_block.mount(transcript)
                        current_assistant_block.append(delta)
                        assistant_text_parts.append(delta)
                        transcript.scroll_end(animate=False)
                elif stream_event.type == "raw_response_event":
                    delta = reasoning_delta_text(stream_event.data)
                    if delta and (current_reasoning_block is not None or delta.strip()):
                        if current_assistant_block is not None:
                            current_assistant_block.finalize()
                            current_assistant_block = None
                        if current_reasoning_block is None:
                            current_reasoning_block = ReasoningBlock()
                            await current_reasoning_block.mount(transcript)
                        current_reasoning_block.append(delta)
                        streamed_reasoning_parts.append(delta)
                        transcript.scroll_end(animate=False)
                elif stream_event.type == "run_item_stream_event":
                    if current_assistant_block is not None:
                        current_assistant_block.finalize()
                        current_assistant_block = None
                    if current_reasoning_block is not None:
                        current_reasoning_block.finalize()
                        current_reasoning_block = None
                    if self.render_code_interpreter_item(stream_event.item):
                        await self.handle_code_interpreter_files([stream_event.item])
                    else:
                        description = None
                        if not should_skip_completed_reasoning(
                            stream_event.item,
                            "".join(streamed_reasoning_parts),
                        ):
                            description = self.describe_run_item(stream_event.item)
                        if description:
                            self.add_event(description)
                    self.refresh_side()
                elif stream_event.type == "agent_updated_stream_event":
                    if current_assistant_block is not None:
                        current_assistant_block.finalize()
                        current_assistant_block = None
                    if current_reasoning_block is not None:
                        current_reasoning_block.finalize()
                        current_reasoning_block = None
                    self.add_event(f"Agent: {stream_event.new_agent.name}")

            if current_assistant_block is not None:
                current_assistant_block.finalize()
            if current_reasoning_block is not None:
                current_reasoning_block.finalize()

            if hasattr(result, "to_input_list"):
                self.history = result.to_input_list()
            else:
                self.history = run_input + [{"role": "assistant", "content": "".join(assistant_text_parts)}]
            await self.handle_code_interpreter_files(getattr(result, "new_items", []))
            self.refresh_side()
        except asyncio.CancelledError:
            if current_assistant_block is not None:
                current_assistant_block.finalize()
            if current_reasoning_block is not None:
                current_reasoning_block.finalize()
            self.add_event("Run interrupted.")
            raise
        except Exception as exc:
            self.add_event(f"Run failed: {exc}")
        finally:
            self.busy = False
            self.active_run_worker = None
            self.last_escape_at = 0.0
            self.interrupt_requested = False
            self.set_agent_status("Ready")

    def apply_reasoning_settings(self) -> None:
        if not self.active_agent or not self.selected_model:
            return
        if self.selected_model.id not in self.reasoning_by_model_id:
            return

        from agents import ModelSettings

        level = self.reasoning_by_model_id[self.selected_model.id]
        current_settings = getattr(self.active_agent.agent, "model_settings", None) or ModelSettings()
        new_settings = dataclasses.replace(
            current_settings,
            reasoning=None if level is None else {"effort": level},
        )
        setattr(self.active_agent.agent, "model_settings", new_settings)

    def describe_run_item(self, item: Any) -> str | None:
        item_type = getattr(item, "type", "")
        if is_reasoning_item(item):
            text = reasoning_item_text(item)
            return f"Reasoning: {text[:2000]}" if text else "Reasoning item."
        if item_type == "tool_call_item":
            raw = getattr(item, "raw_item", None)
            action = getattr(raw, "action", None)
            query = getattr(action, "query", None)
            name = getattr(raw, "name", None)
            return f"Tool call: {name or query or getattr(raw, 'type', 'unknown')}"
        if item_type == "tool_call_output_item":
            output = str(getattr(item, "output", ""))
            return f"Tool output: {output[:160]}"
        if item_type == "message_output_item":
            return None
        return f"Event: {item_type or item}"

    def render_code_interpreter_item(self, item: Any) -> bool:
        raw = getattr(item, "raw_item", None)
        if not is_code_interpreter_raw(raw):
            return False

        self.set_agent_status("Executing code")
        code = getattr(raw, "code", None)
        logs = code_interpreter_logs(raw)
        if code:
            self.add_code_block(str(code))
        else:
            status = getattr(raw, "status", "running")
            self.add_event(f"Code Interpreter: {status}")
        if logs:
            self.add_code_output(logs)
        return True

    def add_code_block(self, code: str) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        collapsible = Collapsible(
            Static(Text(code, style="white")),
            title="Code Interpreter code",
            collapsed=True,
            classes="code-block",
        )
        transcript.mount(collapsible)
        transcript.scroll_end(animate=False)

    def add_code_output(self, output: str) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(Static(Text(output, style="dark_green"), classes="code-output"))
        transcript.scroll_end(animate=False)

    async def handle_code_interpreter_files(self, items: Iterable[Any]) -> None:
        files: list[dict[str, str]] = []
        for item in items:
            files.extend(collect_output_files(item))
        new_files = [file for file in files if file["file_id"] not in self.downloaded_file_ids]
        if not new_files:
            return

        names = ", ".join(file["filename"] for file in new_files)
        if self.download_mode == "skip":
            self.add_event(f"Code Interpreter files available but skipped: {names}")
            return

        should_download = self.download_mode == "auto"
        if self.download_mode == "ask":
            should_download = await self.ask_download_files(new_files)
        if not should_download:
            self.add_event(f"Code Interpreter files available: {names}")
            return

        for file in new_files:
            download = self.download_code_interpreter_file(file["file_id"], file["filename"])
            self.downloaded_file_ids.add(file["file_id"])
            if download.saved:
                self.add_event(f"Downloaded {file['filename']} to {download.path}.")
            else:
                self.add_event(f"Skipped {file['filename']}: identical file already exists at {download.path}.")

    async def ask_download_files(self, files: list[dict[str, str]]) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        previous_status = self.agent_status
        self.set_agent_status("Needs input")

        def done(result: bool) -> None:
            def resolve_after_dismiss() -> None:
                self.set_agent_status(previous_status)
                if not future.done():
                    future.set_result(result)

            self.call_after_refresh(resolve_after_dismiss)

        await self.push_screen(DownloadFilesScreen(files), done)
        return await future

    def download_code_interpreter_file(self, file_id: str, filename: str) -> DownloadResult:
        if self.client is None:
            raise RuntimeError("No OpenAI client is configured.")
        content = self.client.files.content(file_id)
        return write_downloaded_file(Path.cwd(), filename, content.read())

    def add_event(self, text: str) -> None:
        if not text:
            return
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(Static(f"[dim]{text}[/dim]", classes="event"))
        transcript.scroll_end(animate=False)

    def log_agent_message(self, message: str) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(Static(Text(str(message), style="light_green"), classes="agent-log"))
        transcript.scroll_end(animate=False)

    async def ask_user_clarification(
        self,
        question: str,
        options: list[dict[str, str]],
        allow_custom_answer: bool = False,
    ) -> dict[str, str]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, str]] = loop.create_future()
        previous_status = self.agent_status
        self.set_agent_status("Needs input")

        def done(result: dict[str, str]) -> None:
            self.set_agent_status(previous_status)
            if not future.done():
                future.set_result(result)

        await self.push_screen(ClarificationScreen(question, options, allow_custom_answer), done)
        return await future

    def refresh_side(self) -> None:
        self.side_refresh_index += 1
        side = self.query_one("#side", Vertical)
        notes_pane = self.query_one("#notes-pane", VerticalScroll)
        todo_pane = self.query_one("#todo-pane", HorizontalScroll)
        notes_pane.remove_children()
        todo_pane.remove_children()

        show_notes = bool(self.active_agent and self.active_agent.uses_notes)
        show_todo = bool(self.active_agent and self.active_agent.uses_todo)
        side.set_class(show_notes or show_todo, "visible")
        notes_pane.set_class(show_notes, "visible")
        todo_pane.set_class(show_todo, "visible")

        if show_notes:
            if self.notes_store.notes:
                note_items: list[ListItem] = []
                for index, note in enumerate(self.notes_store.notes):
                    note_items.append(
                        ListItem(
                            Label(f"{note.category} - {note.title}"),
                            id=f"note-{self.side_refresh_index}-{index}",
                        )
                    )
                notes_pane.mount(ListView(*note_items, classes="notes-list"))
            else:
                notes_pane.mount(Static("No notes yet."))

        if show_todo:
            if self.todo_store.items:
                todo_pane.mount(Static(render_todo_items(self.todo_store.items), classes="todo-list"))
            else:
                todo_pane.mount(Static("No TODOs yet."))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        widget_id = event.item.id or ""
        if not widget_id.startswith("note-"):
            return
        try:
            note_index = int(widget_id.rsplit("-", 1)[1])
            note = self.notes_store.notes[note_index]
        except (ValueError, IndexError):
            return
        self.push_screen(NoteDetailScreen(note))
