from __future__ import annotations

import importlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


@dataclass
class LoadedAgent:
    name: str
    module: ModuleType
    agent: Any
    props: dict[str, Any]

    @property
    def display_name(self) -> str:
        return str(self.props.get("display_name") or self.name.replace("_", " ").title())

    @property
    def uses_notes(self) -> bool:
        return bool(self.props.get("uses_notes", False))

    @property
    def uses_todo(self) -> bool:
        return bool(self.props.get("uses_todo", False))

    @property
    def container_id(self) -> str | None:
        value = self.props.get("container_id")
        return str(value) if value else None

    def set_context(self, context: Any) -> None:
        setter = getattr(self.module, "set_context", None)
        if callable(setter):
            setter(context)
        self.refresh_props()

    def refresh_props(self) -> None:
        props_getter = getattr(self.module, "get_props", None)
        self.props = props_getter() if callable(props_getter) else {}
        self.props.setdefault("display_name", self.name.replace("_", " ").title())
        self.props.setdefault("uses_notes", False)
        self.props.setdefault("uses_todo", False)


class AgentLoader:
    def __init__(self, agents_dir: Path | str | Iterable[Path | str] = "agents") -> None:
        if isinstance(agents_dir, (str, Path)):
            dirs = [agents_dir]
        else:
            dirs = list(agents_dir)
        self.agent_dirs = [Path(path) for path in dirs]

    def discover(self) -> list[str]:
        agents = self._agent_paths()
        return sorted(agents)

    def load(self, name: str) -> LoadedAgent:
        agents = self._agent_paths()
        agent_dir = agents.get(name)
        if agent_dir is None:
            raise FileNotFoundError(f"No agent module found for {name}")
        main_py = agent_dir / "main.py"

        importlib.invalidate_caches()
        module_prefix = f"ma_loaded_agents.{name}."
        self._forget_module(module_prefix)
        module_name = f"{module_prefix}main_{time.time_ns()}"

        module = ModuleType(module_name)
        module.__file__ = str(main_py)
        module.__package__ = module_name.rpartition(".")[0]
        old_path = list(sys.path)
        try:
            sys.path.insert(0, str(agent_dir))
            sys.modules[module_name] = module
            source = main_py.read_text(encoding="utf-8")
            exec(compile(source, str(main_py), "exec"), module.__dict__)
        finally:
            sys.path[:] = old_path

        agent = getattr(module, "agent", None)
        if agent is None:
            raise AttributeError(f"{main_py} must export a global 'agent' object")

        loaded = LoadedAgent(name=name, module=module, agent=agent, props={})
        loaded.refresh_props()
        return loaded

    def reload(self, name: str) -> LoadedAgent:
        return self.load(name)

    def _agent_paths(self) -> dict[str, Path]:
        agents: dict[str, Path] = {}
        for agents_dir in self.agent_dirs:
            if not agents_dir.exists():
                continue
            for path in sorted(agents_dir.iterdir()):
                if path.is_dir() and (path / "main.py").exists():
                    agents[path.name] = path
        return agents

    def _forget_module(self, module_prefix: str) -> None:
        for key in list(sys.modules):
            if key.startswith(module_prefix):
                del sys.modules[key]
