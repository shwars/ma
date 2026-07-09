from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from ma import cli


def test_default_agent_dirs_include_bundled_and_existing_cwd_agents(tmp_path, monkeypatch):
    cwd_agents = tmp_path / "agents"
    cwd_agents.mkdir()
    monkeypatch.chdir(tmp_path)

    dirs = cli.default_agent_dirs()

    assert dirs[0] == Path(cli.__file__).resolve().parent.parent / "agents"
    assert dirs[1] == cwd_agents


def test_cli_agents_dir_accepts_single_and_multiple_paths(monkeypatch, tmp_path):
    calls = []

    class FakeMaApp:
        def __init__(self, config_path=None, agents_dir=None):
            calls.append({"config_path": config_path, "agents_dir": agents_dir})

        def run(self):
            calls[-1]["ran"] = True

    fake_app_module = ModuleType("ma.app")
    fake_app_module.MaApp = FakeMaApp
    monkeypatch.setitem(sys.modules, "ma.app", fake_app_module)

    one = tmp_path / "one"
    two = tmp_path / "two"

    cli.main(["--agents-dir", str(one)])
    cli.main(["--agents-dir", str(one), str(two)])

    assert calls[0]["agents_dir"] == [one]
    assert calls[0]["ran"] is True
    assert calls[1]["agents_dir"] == [one, two]
    assert calls[1]["ran"] is True
