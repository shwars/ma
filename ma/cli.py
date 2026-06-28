from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mitya's Agent terminal chat")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.json")
    parser.add_argument("--agents-dir", type=Path, default=Path("agents"), help="Path to local agents directory")
    parser.add_argument("--version", action="version", version=f"ma {__version__}")
    args = parser.parse_args(argv)

    from .app import MaApp

    MaApp(config_path=args.config, agents_dir=args.agents_dir).run()
