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
- `/agent <name>` switches directly to an agent by folder name or display name.
- `/model` opens the model selector.
- `/model <model>` switches directly to a model by ID or display name.
- `/reasoning` opens the reasoning selector for the current model.
- `/reasoning low`, `/reasoning medium`, and similar direct forms update reasoning without opening the selector.
- `/theme` opens the centered UI theme selector.
- `/theme <name>` switches directly to a Textual theme such as `nord`, `gruvbox`, or `textual-dark`.
- `/download` opens the download-mode selector.
- `/download auto` downloads Code Interpreter generated files automatically.
- `/download ask` asks before downloading Code Interpreter generated files. This is the default.
- `/download skip` leaves generated files in the remote container and only displays their names.
- `/new` starts a new chat session, clearing conversation history, session notes/TODOs, transcript, and downloaded-file tracking.
- `/help` opens the command help window.
- `/reload` reloads agents from disk.
- `/notes save` saves current notes to a markdown file.
- `/notes clear` clears current notes.
- `/exit` exits the app.

The command palette exposes the same main app commands: Agent, Model, Reasoning, Theme, Download, New, Help, Reload, Notes Save, Notes Clear, and Exit.
When you type a slash command, `ma` shows possible completions in muted text above the composer. Press Tab to complete the current command prefix, including agent names, model names, and theme names.
On startup, `ma` shows a small splash screen while agents and models are initialized in the background. The message composer appears after startup finishes.
The top status line shows the active agent/model, current reasoning level, and current run status: Ready, Working, Needs input, or Executing code.
Modal windows such as Help, selection pickers, clarification prompts, and download confirmation appear centered over the app.

## Built-In Agents

- `simple`: a concise assistant with web search.
- `deep_research`: a research assistant that uses web search, notes, and TODOs.
- `data_analyst`: a local-data analyst that can list and inspect files in the current directory, upload selected files to Code Interpreter, run analysis, and return generated files.
- `pro_analyst`: an advanced local-data analyst with Data Analyst capabilities plus markdown skills, TODO planning, safe local file read/write/edit tools, and allowlisted `cmd`/`bash`/`ssh` command execution.

The Data Analyst local filesystem tools are:

- `ls(mask=None)`: list files in the current directory, optionally using a glob mask.
- `inspect(filename)`: inspect CSV/XLS/XLSX files, including sheets, shape, columns, dtypes, and first rows.
- `upload(filenames)`: upload selected local files into the active Code Interpreter container.

Pro Analyst adds:

- `list_skills()`: list skills from `skills/<skill_id>/skill.md` in the current directory and from bundled Pro Analyst skills.
- `load_skill(skill_id)`: load full instructions for one skill.
- `read_file(filename, max_bytes=200000)`: read a local UTF-8 text file.
- `write_file(filename, content, overwrite=False)`: write a local UTF-8 text file.
- `edit_file(filename, unified_diff)`: apply a unified diff to a local UTF-8 text file.
- `execute_command(command, args=None, timeout_seconds=60)`: run only `cmd`, `bash`, or `ssh`.

Pro Analyst reuses one Code Interpreter container while its agent module remains loaded, so changing `/model` or `/reasoning` does not create a new container. Uploads and Code Interpreter calls are kept on that same container. Its prompt includes a current skill metadata snapshot, and the agent is instructed to call `list_skills()` and `load_skill(...)` before specialized work. Pro Analyst also uses TODO tools for visible multi-step planning.

Bundled Pro Analyst skills include PPTX presentation, DOCX document, guided data exploration, and markdown-to-PDF workflows. PPTX/DOCX files are generated inside Code Interpreter and returned for download; `ma` does not install Office-generation libraries locally.

Custom Pro Analyst skills use this shape:

```markdown
---
id: my_skill
name: My Skill
description: What this skill helps with.
tags: [reporting, data]
---

Skill instructions for the agent.
```

Generated Code Interpreter code is shown as a collapsed expandable block. Code output/logs are shown in dark green. The agent is instructed to return every file it creates so `ma` can download or report it according to `/download`.
When a returned file already exists in the working directory with the same name, size, and checksum, `ma` skips saving a duplicate. If the name exists but the content differs, it writes a suffixed file such as `chart-1.png`.

When a model streams reasoning, `ma` shows it live in gray and then reformats the completed reasoning block as Markdown.

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
    context.log("My Agent loaded.")
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

Run `/reload` after editing or adding an agent.

The notes tool accepts `extra` as optional text metadata. Use JSON text there if you want to preserve several custom fields in one note.

`context.client` and `context.aclient` provide sync and async OpenAI-compatible Yandex clients for agents that need direct API access, such as creating Code Interpreter containers or uploading files.

`context.log(message)` displays a light-green message in the transcript. It is a Python callback for agent code, not a model-callable tool by default.

The clarification tool is available through `context.clarification_tools`. It exposes:

```python
ask_user_clarification(
    question: str,
    options: list[{"title": str, "detail": str}],
    allow_custom_answer: bool = False,
) -> {"title": str, "detail": str}
```

When called, `ma` opens a modal for the user. If `allow_custom_answer` is true, the user can choose `Own answer` and type custom text.
