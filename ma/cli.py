from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__


def default_agent_dirs() -> list[Path]:
    bundled_agents = Path(__file__).resolve().parent.parent / "agents"
    cwd_agents = Path.cwd() / "agents"
    dirs = [bundled_agents]
    if cwd_agents.exists() and cwd_agents.resolve() != bundled_agents.resolve():
        dirs.append(cwd_agents)
    return dirs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mitya's Agent terminal chat")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.json")
    parser.add_argument(
        "--agents-dir",
        type=Path,
        nargs="+",
        default=None,
        help="One or more agent directories. Overrides the default bundled/current-directory lookup.",
    )
    parser.add_argument("--version", action="version", version=f"ma {__version__}")
    args = parser.parse_args(argv)

    from .app import MaApp

    MaApp(config_path=args.config, agents_dir=args.agents_dir or default_agent_dirs()).run()
