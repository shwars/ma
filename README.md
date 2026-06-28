# ma

Mitya's Agent (`ma`) is an educational terminal chat application for learning how coding and agent chat tools are built. It uses Textual for the UI, OpenAI Agents SDK for agent orchestration, and Yandex Cloud through its OpenAI-compatible API.

## Features

- Dynamic agents loaded from `agents/<name>/main.py`
- Streaming terminal chat UI
- Markdown formatting after each streamed assistant block completes
- Yandex Cloud OpenAI-compatible model runtime
- Commands for agent/model selection, reload, and notes
- Command palette entries matching the main slash commands
- Tab completion and muted live hints for slash commands
- Startup splash screen while agents and models initialize
- Session-scoped notes and TODO tools for agents
- Optional separate notes/TODO side panes controlled by each agent's `get_props()`
- Full-width two-line composer with Ctrl+Enter for new lines

## Quick Start

Requirements:

- Python 3.11+
- `uv`

Install dependencies:

```powershell
uv sync
```

Create a local `.env` file with Yandex Cloud credentials:

```text
folder_id=your-yandex-folder-id
api_key=your-yandex-api-key
```

Run the app:

```powershell
uv run ma
```

## Configuration

`config.json` is optional. If it is missing and credentials are available, `ma` asks the Yandex Cloud OpenAI-compatible models API for available models. The model selector shows only Responses-compatible text models using the `gpt://` scheme.

Credential priority:

1. `folder_id` / `api_key` in `config.json`
2. `folder_id` / `api_key` in `.env`
3. `YANDEX_FOLDER_ID` / `YANDEX_API_KEY` environment variables
4. `folder_id` / `api_key` environment variables

Use `config.example.json` when you want to customize the model list. Model IDs can include `%folder_id%`, which is substituted when config loads:

```json
{
  "models": [
    {
      "id": "qwen3",
      "display_name": "Qwen3 235B",
      "model_id": "gpt://%folder_id%/qwen3-235b-a22b-fp8"
    }
  ]
}
```

The model selector always includes `Agent Default`. Choosing it means `ma` does not inject a model into the root agent; the agent file keeps responsibility for selecting its own model.

## Commands

- `/agent` selects the active agent.
- `/model` selects the active model.
- `/reasoning` selects the reasoning effort for the current model.
- `/reload` reloads agents from disk.
- `/notes save` saves session notes to a markdown file.
- `/notes clear` clears session notes.
- `/exit` exits the app.

While typing a slash command, press Tab to complete the current prefix. `ma` also shows matching completions in muted text above the composer.

## Built-In Agents

- `simple`: a concise assistant with web search.
- `deep_research`: a research assistant that uses web search, notes, and TODOs.

## Creating Agents

Create `agents/my_agent/main.py` and export a global `agent` object:

```python
from agents import Agent, WebSearchTool

agent = Agent(
    name="MyAgent",
    instructions="Help the user clearly and concisely.",
    tools=[WebSearchTool()],
)
```

Agents can optionally receive host context and declare UI properties:

```python
def set_context(context):
    agent.tools = [*context.notes_tools, *context.todo_tools]


def get_props():
    return {
        "display_name": "My Agent",
        "uses_notes": True,
        "uses_todo": True,
    }
```

Run `/reload` after adding or editing an agent.

## Development

Run tests:

```powershell
uv run --extra dev pytest
```

Useful docs:

- [Architecture](docs/Architecture.md)
- [User Manual](docs/UserManual.md)
- [History](docs/History.md)
