from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static, TextArea
from openai.types.responses import ResponseTextDeltaEvent
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text

from .agent_loader import AgentLoader, LoadedAgent
from .config import AppConfig, ModelChoice, load_config
from .context import AgentContext
from .runtime import build_model
from .stores import Note, NotesStore, TodoItem, TodoStore
from .tools import build_notes_tools, build_todo_tools

REASONING_CHOICES: list[tuple[str, str]] = [
    ("agent_default", "Agent Default"),
    ("none", "None"),
    ("minimal", "Minimal"),
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra High"),
]


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


class ComposerTextArea(TextArea):
    async def _on_key(self, event) -> None:
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


def render_todo_items(items: list[TodoItem]) -> Text:
    todos = Text(no_wrap=True)
    for index, item in enumerate(items):
        if index:
            todos.append("\n")
        marker = "☑" if item.done else "☐"
        style = "light_green" if item.done else None
        todos.append(f"{marker} {item.title}", style=style)
    return todos


class MaApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
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
        height: 4;
        border: round $primary;
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

    .notes-list {
        height: 1fr;
    }

    .todo-list {
        width: auto;
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
        self.agent_names: list[str] = []
        self.active_agent: LoadedAgent | None = None
        self.selected_model: ModelChoice | None = self._initial_model_choice()
        self.selected_model_object: Any = None
        self.reasoning_by_model_id: dict[str, str | None] = {}
        self.side_refresh_index = 0
        self.history: list[Any] = []
        self.busy = False

    def _initial_model_choice(self) -> ModelChoice | None:
        return next(
            (model for model in self.config.models if not model.is_agent_default),
            self.config.models[0] if self.config.models else None,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield VerticalScroll(id="transcript")
            with Vertical(id="side"):
                yield VerticalScroll(id="notes-pane")
                yield HorizontalScroll(id="todo-pane")
        yield ComposerTextArea(
            "",
            placeholder="Message, or /agent /model /reasoning /reload /notes save /notes clear /exit",
            id="composer",
            show_line_numbers=False,
            soft_wrap=True,
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "ma"
        self.notes_tools = build_notes_tools(self.notes_store)
        self.todo_tools = build_todo_tools(self.todo_store)
        self.selected_model_object = build_model(self.config, self.selected_model)
        await self.reload_agents()
        self.refresh_side()
        self.query_one(ComposerTextArea).focus()

    async def submit_composer(self) -> None:
        composer = self.query_one("#composer", TextArea)
        text = composer.text.strip()
        composer.load_text("")
        if not text:
            return
        if text.startswith("/"):
            await self.handle_command(text)
            return
        self.run_chat(text)

    async def handle_command(self, text: str) -> None:
        command = text.lower()
        if command == "/agent":
            await self.choose_agent()
        elif command == "/model":
            await self.choose_model()
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
            return

        active_name = self.active_agent.name if self.active_agent else self.agent_names[0]
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

    def switch_model(self, model_id: str) -> None:
        self.selected_model = next((model for model in self.config.models if model.id == model_id), None)
        self.selected_model_object = build_model(self.config, self.selected_model)
        if self.selected_model:
            self.add_event(f"Active model: {self.selected_model.display_name}.")
        self.apply_context()

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
            notes_store=self.notes_store,
            todo_store=self.todo_store,
            notes_tools=self.notes_tools,
            todo_tools=self.todo_tools,
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

    def action_save_notes(self) -> None:
        self.save_notes()

    def action_clear_notes(self) -> None:
        self.clear_notes()

    def get_system_commands(self, screen) -> Iterable[SystemCommand]:
        yield SystemCommand("Agent", "Select the active agent", self.action_choose_agent)
        yield SystemCommand("Model", "Select the active model", self.action_choose_model)
        yield SystemCommand("Reasoning", "Set reasoning level for the current model", self.action_choose_reasoning)
        yield SystemCommand("Reload", "Reload agents from disk", self.action_reload_agents)
        yield SystemCommand("Notes Save", "Save session notes to markdown", self.action_save_notes)
        yield SystemCommand("Notes Clear", "Clear session notes", self.action_clear_notes)
        yield SystemCommand("Exit", "Exit the application", self.action_quit)
        for command in super().get_system_commands(screen):
            if command.title != "Quit":
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
            return
        if not self.active_agent:
            self.add_event("No active agent.")
            return
        use_agent_default = bool(self.selected_model and self.selected_model.is_agent_default)
        if not use_agent_default and self.selected_model_object is None:
            self.add_event("No model is ready. Configure folder_id/api_key and at least one model.")
            return

        self.busy = True
        user_widget = Static(text, classes="user-message")
        transcript = self.query_one("#transcript", VerticalScroll)
        await transcript.mount(user_widget)
        transcript.scroll_end(animate=False)

        try:
            if not use_agent_default:
                setattr(self.active_agent.agent, "model", self.selected_model_object)
            self.apply_reasoning_settings()
            run_input = self.history + [{"role": "user", "content": text}]
            assistant_text_parts: list[str] = []
            current_assistant_block: AssistantBlock | None = None

            from agents import Runner

            result = Runner.run_streamed(self.active_agent.agent, run_input)
            async for stream_event in result.stream_events():
                if stream_event.type == "raw_response_event" and isinstance(
                    stream_event.data, ResponseTextDeltaEvent
                ):
                    delta = getattr(stream_event.data, "delta", "")
                    if delta and (current_assistant_block is not None or delta.strip()):
                        if current_assistant_block is None:
                            current_assistant_block = AssistantBlock()
                            await current_assistant_block.mount(transcript)
                        current_assistant_block.append(delta)
                        assistant_text_parts.append(delta)
                        transcript.scroll_end(animate=False)
                elif stream_event.type == "run_item_stream_event":
                    if current_assistant_block is not None:
                        current_assistant_block.finalize()
                        current_assistant_block = None
                    self.add_event(self.describe_run_item(stream_event.item))
                    self.refresh_side()
                elif stream_event.type == "agent_updated_stream_event":
                    if current_assistant_block is not None:
                        current_assistant_block.finalize()
                        current_assistant_block = None
                    self.add_event(f"Agent: {stream_event.new_agent.name}")

            if current_assistant_block is not None:
                current_assistant_block.finalize()

            if hasattr(result, "to_input_list"):
                self.history = result.to_input_list()
            else:
                self.history = run_input + [{"role": "assistant", "content": "".join(assistant_text_parts)}]
            self.refresh_side()
        except Exception as exc:
            self.add_event(f"Run failed: {exc}")
        finally:
            self.busy = False

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

    def describe_run_item(self, item: Any) -> str:
        item_type = getattr(item, "type", "")
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
            return "Message complete."
        return f"Event: {item_type or item}"

    def add_event(self, text: str) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(Static(f"[dim]{text}[/dim]", classes="event"))
        transcript.scroll_end(animate=False)

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
