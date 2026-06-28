from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from ma.tools import ClarificationOption, build_clarification_tools, normalize_clarification_options


def test_normalize_clarification_options_accepts_models_and_dicts():
    assert normalize_clarification_options(
        [
            ClarificationOption(title=" First ", detail=" Detail "),
            {"title": "Second", "detail": "More"},
            {"title": " ", "detail": "Ignored"},
        ]
    ) == [
        {"title": "First", "detail": "Detail"},
        {"title": "Second", "detail": "More"},
    ]


def test_clarification_tool_calls_async_asker_with_options():
    async def run() -> None:
        calls: list[tuple[str, list[dict[str, str]], bool]] = []

        async def ask(question: str, options: list[dict[str, str]], allow_custom_answer: bool) -> dict[str, str]:
            calls.append((question, options, allow_custom_answer))
            return options[0]

        tool = build_clarification_tools(ask)[0]
        context = SimpleNamespace(tool_name=tool.name, run_config=None)
        result = await tool.on_invoke_tool(
            context,
            json.dumps(
                {
                    "question": "Choose path",
                    "options": [{"title": "Fast", "detail": "Move quickly"}],
                    "allow_custom_answer": True,
                }
            ),
        )

        assert calls == [("Choose path", [{"title": "Fast", "detail": "Move quickly"}], True)]
        assert result == {"title": "Fast", "detail": "Move quickly"}

    asyncio.run(run())


def test_clarification_tool_handles_missing_options_without_custom_answer():
    async def run() -> None:
        async def ask(question: str, options: list[dict[str, str]], allow_custom_answer: bool) -> dict[str, str]:
            raise AssertionError("asker should not be called without options or custom answers")

        tool = build_clarification_tools(ask)[0]
        context = SimpleNamespace(tool_name=tool.name, run_config=None)
        result = await tool.on_invoke_tool(
            context,
            json.dumps({"question": "Choose path", "options": [], "allow_custom_answer": False}),
        )

        assert result == {
            "title": "No options",
            "detail": "The agent did not provide clarification options.",
        }

    asyncio.run(run())
