from __future__ import annotations

import importlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


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

    def set_context(self, context: Any) -> None:
        setter = getattr(self.module, "set_context", None)
        if callable(setter):
            setter(context)


class AgentLoader:
    def __init__(self, agents_dir: Path | str = "agents") -> None:
        self.agents_dir = Path(agents_dir)

    def discover(self) -> list[str]:
        if not self.agents_dir.exists():
            return []
        names: list[str] = []
        for path in sorted(self.agents_dir.iterdir()):
            if path.is_dir() and (path / "main.py").exists():
                names.append(path.name)
        return names

    def load(self, name: str) -> LoadedAgent:
        agent_dir = self.agents_dir / name
        main_py = agent_dir / "main.py"
        if not main_py.exists():
            raise FileNotFoundError(f"No agent module found at {main_py}")

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

        props_getter = getattr(module, "get_props", None)
        props = props_getter() if callable(props_getter) else {}
        props.setdefault("display_name", name.replace("_", " ").title())
        props.setdefault("uses_notes", False)
        props.setdefault("uses_todo", False)

        return LoadedAgent(name=name, module=module, agent=agent, props=props)

    def reload(self, name: str) -> LoadedAgent:
        return self.load(name)

    def _forget_module(self, module_prefix: str) -> None:
        for key in list(sys.modules):
            if key.startswith(module_prefix):
                del sys.modules[key]
