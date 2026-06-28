from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .agent_loader import AgentLoader, LoadedAgent
from .config import AppConfig, ModelChoice, load_config
from .context import AgentContext
from .runtime import build_model
from .stores import NotesStore, TodoStore
from .tools import build_notes_tools, build_todo_tools


class PickerScreen(ModalScreen[str | None]):
    def __init__(self, title: str, choices: list[tuple[str, str]]) -> None:
        super().__init__()
        self.title = title
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(self.title, id="picker-title")
            items = [ListItem(Label(label), id=value) for value, label in self.choices]
            yield ListView(*items, id="picker-list")

    def on_mount(self) -> None:
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.id)

    def key_escape(self) -> None:
        self.dismiss(None)


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
        border: round $accent;
        padding: 1;
    }

    #side.visible {
        display: block;
    }

    #composer {
        height: 3;
    }

    .message {
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
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
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
                yield Input(placeholder="Message, or /agent /model /reload /notes save /notes clear", id="composer")
            yield VerticalScroll(id="side")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "ma"
        self.notes_tools = build_notes_tools(self.notes_store)
        self.todo_tools = build_todo_tools(self.todo_store)
        self.selected_model_object = build_model(self.config, self.selected_model)
        await self.reload_agents()
        self.refresh_side()
        self.query_one(Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
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
        elif command == "/reload":
            await self.reload_agents()
        elif command == "/notes clear":
            count = self.notes_store.clear()
            self.add_event(f"Cleared {count} notes.")
            self.refresh_side()
        elif command == "/notes save":
            path = Path.cwd() / f"notes-{datetime.now():%Y%m%d-%H%M%S}.md"
            self.notes_store.save_markdown(path)
            self.add_event(f"Saved notes to {path}.")
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

    def apply_context(self) -> None:
        if not self.active_agent:
            return
        context = AgentContext(
            config=self.config,
            selected_model=self.selected_model,
            model=self.selected_model_object,
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
        user_widget = Static(f"[b]You[/b]\n{text}", classes="message")
        assistant_widget = Static("[b]Assistant[/b]\n", classes="message")
        transcript = self.query_one("#transcript", VerticalScroll)
        await transcript.mount(user_widget)
        await transcript.mount(assistant_widget)
        transcript.scroll_end(animate=False)

        try:
            if not use_agent_default:
                setattr(self.active_agent.agent, "model", self.selected_model_object)
            run_input = self.history + [{"role": "user", "content": text}]
            assistant_text = ""

            from agents import Runner

            result = Runner.run_streamed(self.active_agent.agent, run_input)
            async for stream_event in result.stream_events():
                if stream_event.type == "raw_response_event":
                    delta = getattr(stream_event.data, "delta", "")
                    if delta:
                        assistant_text += delta
                        assistant_widget.update(f"[b]Assistant[/b]\n{assistant_text}")
                        transcript.scroll_end(animate=False)
                elif stream_event.type == "run_item_stream_event":
                    self.add_event(self.describe_run_item(stream_event.item))
                    self.refresh_side()
                elif stream_event.type == "agent_updated_stream_event":
                    self.add_event(f"Agent: {stream_event.new_agent.name}")

            if hasattr(result, "to_input_list"):
                self.history = result.to_input_list()
            else:
                self.history = run_input + [{"role": "assistant", "content": assistant_text}]
            self.refresh_side()
        except Exception as exc:
            self.add_event(f"Run failed: {exc}")
        finally:
            self.busy = False

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
        side = self.query_one("#side", VerticalScroll)
        side.remove_children()
        show_notes = bool(self.active_agent and self.active_agent.uses_notes)
        show_todo = bool(self.active_agent and self.active_agent.uses_todo)
        side.set_class(show_notes or show_todo, "visible")

        if show_notes:
            side.mount(Static("[b]Notes[/b]"))
            if self.notes_store.notes:
                for note in self.notes_store.notes:
                    side.mount(Static(f"[b]{note.title}[/b]\n[{note.category}] {note.body[:240]}"))
            else:
                side.mount(Static("No notes yet."))

        if show_todo:
            side.mount(Static("[b]TODO[/b]"))
            if self.todo_store.items:
                for index, item in enumerate(self.todo_store.items):
                    marker = "x" if item.done else " "
                    side.mount(Static(f"{index}. [{marker}] {item.title}"))
            else:
                side.mount(Static("No TODOs yet."))
