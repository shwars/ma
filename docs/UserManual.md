# User Manual

`ma` is a terminal chat application for experimenting with OpenAI Agents SDK agents running on Yandex Cloud.

## Setup

Install the project:

```powershell
uv sync
```

You can start without `config.json` if credentials are available through `.env` or environment variables.

For a local `.env` file, create:

```text
folder_id=your-yandex-folder-id
api_key=your-yandex-api-key
```

Credential priority is:

1. `folder_id` / `api_key` in `config.json`
2. `folder_id` / `api_key` in `.env`
3. `YANDEX_FOLDER_ID` / `YANDEX_API_KEY` in `.env`
4. `YANDEX_FOLDER_ID` / `YANDEX_API_KEY` environment variables
5. `folder_id` / `api_key` environment variables

Copy `config.example.json` to `config.json` only when you want to customize the model list or put credentials in config. If `config.json` is missing and credentials are available, `ma` asks the Yandex Cloud OpenAI-compatible models endpoint for available models.

The model selector shows only Responses-compatible text models using the `gpt://` scheme. Non-text models returned by the API or listed in config are filtered out.

Model IDs can use `%folder_id%`, which is replaced at load time:

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

The model selector always includes `Agent Default`. Choose it when the agent file should keep its own model instead of having `ma` inject the selected model.

Start the app:

```powershell
uv run ma
```

## Commands

- `/agent` opens the agent selector.
- `/model` opens the model selector.
- `/reasoning` opens the reasoning selector for the current model.
- `/reasoning low`, `/reasoning medium`, and similar direct forms update reasoning without opening the selector.
- `/reload` reloads agents from disk.
- `/notes save` saves current notes to a markdown file.
- `/notes clear` clears current notes.
- `/exit` exits the app.

The command palette exposes the same main app commands: Agent, Model, Reasoning, Reload, Notes Save, Notes Clear, and Exit.

## Built-In Agents

- `simple`: a concise assistant with web search.
- `deep_research`: a research assistant that uses web search, notes, and TODOs.

When the active agent uses notes or TODOs, the right pane shows that state live during the chat.
Notes and TODOs are displayed in separate panes. If only one pane is enabled for the selected agent, it uses the full right-side height.
Notes show one `category - title` row per note; select a note row and press Enter to open the full note.
TODOs show one item per line with `☐` for pending items and light-green `☑` rows for done items. Long TODOs do not wrap; use the bottom horizontal scrollbar to read them.
The message composer spans the full width of the app. Press Enter to send and Ctrl+Enter to insert a new line.

## Creating An Agent

Create a folder under `agents/` with a `main.py` file:

```python
from agents import Agent, WebSearchTool

agent = Agent(
    name="MyAgent",
    instructions="Help the user clearly and concisely.",
    tools=[WebSearchTool()],
)
```

To use host-provided tools:

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

Run `/reload` after editing or adding an agent.

The notes tool accepts `extra` as optional text metadata. Use JSON text there if you want to preserve several custom fields in one note.
