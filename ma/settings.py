from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    agent_name: str | None = None
    model_id: str | None = None
    reasoning_level: str | None = None


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
        return AppSettings(
            agent_name=_value(section.get("agent")),
            model_id=_value(section.get("model")),
            reasoning_level=_value(section.get("reasoning")),
        )
    except configparser.Error:
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    parser = configparser.ConfigParser()
    parser["ma"] = {
        "agent": settings.agent_name or "",
        "model": settings.model_id or "",
        "reasoning": settings.reasoning_level or "agent_default",
    }
    try:
        with (settings_path() if path is None else path).open("w", encoding="utf-8") as file:
            parser.write(file)
    except OSError:
        pass


def _value(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None
