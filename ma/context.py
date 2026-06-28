from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig, ModelChoice
from .stores import NotesStore, TodoStore


@dataclass
class AgentContext:
    config: AppConfig
    selected_model: ModelChoice | None
    model: Any
    folder_id: str
    api_key: str
    notes_store: NotesStore
    todo_store: TodoStore
    notes_tools: list[Any]
    todo_tools: list[Any]
