# ma

Mitya's Agent (`ma`) is an educational terminal chat application for learning how coding and agent chat tools are built. It uses Textual for the UI, OpenAI Agents SDK for agent orchestration, and Yandex Cloud through its OpenAI-compatible API.

## Features

- Dynamic agents loaded from `agents/<name>/main.py`
- Streaming terminal chat UI
- Markdown formatting after each streamed assistant block completes
- Streaming gray reasoning output that finalizes as Markdown when the reasoning block completes
- Yandex Cloud OpenAI-compatible model runtime
- Commands for agent/model selection, reload, and notes
- Code Interpreter output display with generated-file download controls
- A top status line showing Ready, Working, Needs input, Executing code, and the active reasoning level
- Command palette entries matching the main slash commands
- Tab completion and muted live hints for slash commands
- Double-Escape interrupt for cancelling an active agent run
- Startup splash screen while agents and models initialize
- Session-scoped notes and TODO tools for agents
- Host logging and user-clarification integration tools for agents
- Optional separate notes/TODO side panes controlled by each agent's `get_props()`
- Full-width two-line composer with Ctrl+Enter for new lines
- Persistent per-directory prompt and command history
- Session export to text, Markdown, JSON, or CSV with `/save <filename>`

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
MY_PROJECT_SETTING=project-specific-value
```

Every value in the launch directory's `.env` is loaded into the `ma` process when it starts. Agent code can read project settings explicitly through `context.env["MY_PROJECT_SETTING"]`, or through `os.getenv("MY_PROJECT_SETTING")` when ordinary Python code or child processes need them. Treat these values as sensitive configuration and do not log secrets.

Run the app:

```powershell
uv run ma
```

To start `ma` from any working directory on Windows, put a small `ma.bat` somewhere on `PATH`:

```bat
@uv --project <path_to_ma_dir> run ma %*
```

When no `--agents-dir` is provided, `ma` loads bundled agents from `<path_to_ma_dir>/agents` and also checks `./agents` in the current working directory when it exists. Current-directory agents override bundled agents with the same folder name.

`ma` saves the active agent, model, and reasoning choice in `ma.ini` in the directory where it is launched. This keeps startup settings aligned with local agents and configuration. Missing or unavailable saved values fall back to the normal defaults.

## Run From GitHub

You can run `ma` without cloning the repository. `uv` installs the application from GitHub into an isolated environment while keeping your current directory as the working directory, so its `.env`, `config.json`, and local `./agents/` directory continue to work.

For a one-off session:

```powershell
uvx --from git+https://github.com/shwars/ma ma
```

To install `ma` persistently as a command on your `PATH`:

```powershell
uv tool install git+https://github.com/shwars/ma
ma
```

Refresh that installation with:

```powershell
uv tool upgrade ma
```

Cloning the repository and using `uv sync` remains the recommended workflow for development or modifying bundled agents.

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

- `/agent [name]` selects the active agent, or opens the selector when no name is given.
- `/model [model]` selects the active model, or opens the selector when no model is given.
- `/reasoning` selects the reasoning effort for the current model.
- `/theme [name]` selects a Textual UI theme, or opens the centered selector when no theme is given.
- `/download auto`, `/download ask`, `/download skip` controls Code Interpreter generated-file downloads. Default is `ask`.
- `/download all` downloads every file from the active agent's exposed Code Interpreter container.
- `/new` starts a new chat session and clears session state.
- `/help` opens the command help window.
- `/reload` reloads agents from disk.
- `/notes save` saves session notes to a markdown file.
- `/notes clear` clears session notes.
- `/exit` exits the app.

While typing a slash command, press Tab to complete the current prefix. `ma` also shows matching completions in muted text above the composer, including available agent names, model names, and theme names. With an empty composer, press Up to recall the newest submitted prompt or command and continue browsing history with Up/Down. Editing a recalled entry returns the arrows to normal cursor navigation. The last 10 submitted entries are stored in the `[history]` section of the local `ma.ini`.

During an active run, press Esc once to show an interrupt warning. Press Esc again within 2 seconds to cancel the current agent run. Partial assistant/reasoning output stays in the transcript.

## Built-In Agents

- `simple`: a concise assistant with web search.
- `deep_research`: a research assistant that uses web search, notes, and TODOs.
- `data_analyst`: a local-data analyst that can list/inspect local CSV/XLS/XLSX files, upload selected files to Code Interpreter, run analysis, and return generated files.
- `pro_analyst`: an advanced data analyst with Data Analyst capabilities plus skill loading, TODO planning, safe local file read/write/edit tools, and allowlisted command execution.

For Code Interpreter runs, generated code appears as a collapsed expandable block. Code output/logs are shown in dark green. Files returned by Code Interpreter follow the active `/download` mode. `/download all` is available when the active agent exposes a `container_id` prop.
If a returned file already exists with the same name, size, and checksum, `ma` treats it as already downloaded instead of writing a suffixed duplicate.

Pro Analyst reuses one Code Interpreter container while its agent module remains loaded, so `/model` and `/reasoning` changes keep uploads and Code Interpreter calls on the same container. Its prompt includes a current skill metadata snapshot, and it is instructed to review that snapshot before exploring data, then call `load_skill(...)` only when applying a relevant skill. Skills live in `skills/<skill_id>/skill.md` under either the current working directory or `agents/pro_analyst/`. Current-directory skills override bundled skills at context-build time. PPTX/DOCX skills generate files inside Code Interpreter, not through local `ma` dependencies.

For Pro Analyst, the `upload` tool returns the exact `container_path` for each uploaded file. Code Interpreter Python should use that value instead of guessing from the local filename. Local data files should always be uploaded before Code Interpreter data analysis begins.

Minimal skill format:

```markdown
---
id: my_skill
name: My Skill
description: What this skill helps with.
tags: [reporting, data]
---

Skill instructions for the agent.
```

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
    context.log("My Agent loaded.")
    project_setting = context.env.get("MY_PROJECT_SETTING")
    agent.tools = [
        *context.notes_tools,
        *context.todo_tools,
        *context.clarification_tools,
    ]


def get_props():
    return {
        "display_name": "My Agent",
        "uses_notes": True,
        "uses_todo": True,
    }
```

Run `/reload` after adding or editing an agent.

Agent discovery is multi-directory. By default, `ma` scans the bundled repo `agents/` directory first and the current working directory's `agents/` directory second, so project-local agents can override bundled examples. Use `--agents-dir path1 path2` to replace that default lookup with explicit directories; when duplicate names exist, the later directory wins.

`context.client` and `context.aclient` provide sync and async OpenAI-compatible Yandex clients. `context.log(message)` writes a light-green message to the transcript. `context.clarification_tools` exposes `ask_user_clarification(question, options, allow_custom_answer=False)`, where each option has `title` and `detail`; it returns the selected `{title, detail}`. `context.env` contains the raw key/value pairs from the launch directory's `.env`; `os.getenv(...)` exposes the effective process environment, including those values for child processes. Keep credentials and other secrets out of transcript messages.

## Saving Sessions

Use `/save <filename>` to export the current session. Supported extensions are `.txt`, `.md`, `.json`, and `.csv`; the extension selects the output format and an existing file is replaced. Exports include chronological user messages, commands, completed assistant and reasoning blocks, tool calls and full outputs, Code Interpreter code/logs, agent logs, handoffs, and transcript events. The command palette includes **Save Session Output**, which places `/save ` in the composer so you can enter the filename.

## Development

Run tests:

```powershell
uv run --extra dev pytest
```

Useful docs:

- [Architecture](docs/Architecture.md)
- [User Manual](docs/UserManual.md)
- [History](docs/History.md)
