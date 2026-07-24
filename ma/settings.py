from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    agent_name: str | None = None
    model_id: str | None = None
    reasoning_level: str | None = None
    max_turns: int | None = None
    prompt_history: tuple[str, ...] = ()


def settings_path(directory: Path | None = None) -> Path:
    return (directory or Path.cwd()) / "ma.ini"


def load_settings(path: Path | None = None) -> AppSettings:
    parser = configparser.ConfigParser()
    try:
        parser.read(settings_path() if path is None else path, encoding="utf-8")
    except (OSError, configparser.Error):
        return AppSettings()

    try:
        if not parser.has_section("ma"):
            return AppSettings()
        section = parser["ma"]
        settings = AppSettings(
            agent_name=_value(section.get("agent")),
            model_id=_value(section.get("model")),
            reasoning_level=_value(section.get("reasoning")),
            max_turns=_positive_int(section.get("maxturns")),
        )
        return AppSettings(
            agent_name=settings.agent_name,
            model_id=settings.model_id,
            reasoning_level=settings.reasoning_level,
            max_turns=settings.max_turns,
            prompt_history=_load_history(parser),
        )
    except configparser.Error:
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    parser = configparser.ConfigParser()
    parser["ma"] = {
        "agent": settings.agent_name or "",
        "model": settings.model_id or "",
        "reasoning": settings.reasoning_level or "agent_default",
        "maxturns": str(settings.max_turns) if settings.max_turns is not None else "agent_default",
    }
    parser["history"] = {
        f"item_{index}": entry for index, entry in enumerate(settings.prompt_history[-10:])
    }
    try:
        with (settings_path() if path is None else path).open("w", encoding="utf-8") as file:
            parser.write(file)
    except OSError:
        pass


def _value(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _positive_int(value: str | None) -> int | None:
    try:
        number = int(value or "")
    except ValueError:
        return None
    return number if number > 0 else None


def _load_history(parser: configparser.ConfigParser) -> tuple[str, ...]:
    if not parser.has_section("history"):
        return ()
    entries: list[tuple[int, str]] = []
    for key, value in parser.items("history", raw=True):
        if not key.startswith("item_"):
            continue
        try:
            index = int(key.removeprefix("item_"))
        except ValueError:
            continue
        if index >= 0 and value.strip():
            entries.append((index, value))
    return tuple(value for _, value in sorted(entries)[-10:])
