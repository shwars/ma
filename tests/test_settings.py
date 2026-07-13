from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from textual.app import App

from ma.app import MaApp
from ma.settings import AppSettings, load_settings, save_settings, settings_path


def test_settings_round_trip_and_default_path(tmp_path):
    path = settings_path(tmp_path)
    saved = AppSettings(agent_name="research", model_id="qwen", reasoning_level="medium")

    save_settings(saved, path)

    assert path.name == "ma.ini"
    assert load_settings(path) == saved


def test_missing_and_malformed_settings_use_defaults(tmp_path):
    path = tmp_path / "ma.ini"

    assert load_settings(path) == AppSettings()

    path.write_text("[ma\nagent = broken", encoding="utf-8")

    assert load_settings(path) == AppSettings()

    path.write_text("[ma]\nagent = %broken", encoding="utf-8")

    assert load_settings(path) == AppSettings()


def test_startup_restores_available_project_settings(tmp_path):
    async def run() -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "folder_id": "folder",
                    "api_key": "key",
                    "models": [
                        {"id": "custom", "model_id": "gpt://folder/custom/latest"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        agents_dir = tmp_path / "agents"
        for name in ("simple", "research"):
            agent_dir = agents_dir / name
            agent_dir.mkdir(parents=True)
            (agent_dir / "main.py").write_text("agent = object()\n", encoding="utf-8")

        path = tmp_path / "ma.ini"
        save_settings(AppSettings("research", "custom", "medium"), path)

        async with MaApp(config_path=config_path, agents_dir=agents_dir, settings_file=path).run_test() as pilot:
            for _ in range(10):
                await pilot.pause()
                if not pilot.app.starting:
                    break

            assert pilot.app.active_agent is not None
            assert pilot.app.active_agent.name == "research"
            assert pilot.app.selected_model is not None
            assert pilot.app.selected_model.id == "custom"
            assert pilot.app.selected_reasoning_level == "medium"

    asyncio.run(run())


def test_unavailable_project_settings_fall_back_to_defaults(tmp_path):
    async def run() -> None:
        agents_dir = tmp_path / "agents"
        simple_dir = agents_dir / "simple"
        simple_dir.mkdir(parents=True)
        (simple_dir / "main.py").write_text("agent = object()\n", encoding="utf-8")

        path = tmp_path / "ma.ini"
        save_settings(AppSettings("missing", "missing-model", "high"), path)

        async with MaApp(config_path=tmp_path / "missing.json", agents_dir=agents_dir, settings_file=path).run_test() as pilot:
            for _ in range(10):
                await pilot.pause()
                if not pilot.app.starting:
                    break

            assert pilot.app.active_agent is not None
            assert pilot.app.active_agent.name == "simple"
            assert pilot.app.selected_model is not None
            assert pilot.app.selected_model.id != "missing-model"
            assert pilot.app.selected_reasoning_level is None

    asyncio.run(run())


def test_exit_writes_current_settings(monkeypatch, tmp_path):
    path = tmp_path / "ma.ini"
    app = MaApp(config_path=tmp_path / "missing.json", settings_file=path)
    app.active_agent = SimpleNamespace(name="research")
    app.selected_model = SimpleNamespace(id="custom")
    app.reasoning_by_model_id["custom"] = "high"
    monkeypatch.setattr(App, "exit", lambda self, result=None, message=None: None)

    app.exit()

    assert load_settings(path) == AppSettings("research", "custom", "high")
