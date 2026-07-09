# Architecture

`ma` is a small educational terminal chat application built around the OpenAI Agents SDK and Yandex Cloud's OpenAI-compatible API.

## Application Shape

- `ma.cli` exposes the `ma` console command.
- `ma.app` contains the Textual UI: transcript, input line, status line, selectors, and optional right-side notes/TODO panes.
- `ma.config` loads optional `config.json`, optional `.env`, and process environment credentials.
- `ma.runtime` creates the Yandex-backed Agents SDK model:
  - `AsyncOpenAI(base_url="https://ai.api.cloud.yandex.net/v1", api_key=..., project=folder_id)`
  - `OpenAIResponsesModel(model=model_uri, openai_client=...)`
- `ma.agent_loader` discovers and imports user agents from one or more `agents/<name>/main.py` directories.
- `ma.stores` and `ma.tools` provide session-scoped notes and TODO tools.
- `agents/data_analyst/filesystem_tools.py` provides reusable local file tools for Data Analyst-style agents.
- `agents/pro_analyst/skill_tools.py` and `filesystem_tools.py` provide markdown skill loading plus advanced local file/command tools.

## Agent Contract

Each agent lives in `agents/<agent_name>/main.py`.

Required:

```python
agent = Agent(...)
```

Optional:

```python
def set_context(context): ...
def get_props() -> dict: ...
```

`set_context(context)` is called after loading and when model/context changes. `get_props()` controls UI hints. Missing props default to:

```python
{
    "display_name": "<Folder Name>",
    "uses_notes": False,
    "uses_todo": False,
}
```

Agents may also return `"container_id": "<code-interpreter-container-id>"` when they own a Code Interpreter container. `LoadedAgent.set_context()` refreshes props after calling `set_context(context)`, so runtime values created during context application are visible to the UI.

The loader imports agent files by path under an internal module name. This avoids colliding with the OpenAI Agents SDK package, which is also named `agents`.

Agent lookup is multi-directory. By default, the CLI configures the loader with the bundled project `agents/` directory first and `Path.cwd() / "agents"` second when that folder exists and is distinct. If the same agent folder name appears in multiple directories, the later directory wins, so project-local agents override bundled examples. Passing `--agents-dir path1 path2` replaces the default lookup with those explicit directories.

## Context Object

Agents receive an `AgentContext` with:

- `config`
- `selected_model`
- `model`
- `reasoning_level`
- `folder_id`
- `api_key`
- `client`
- `aclient`
- `notes_store`
- `todo_store`
- `notes_tools`
- `todo_tools`
- `clarification_tools`
- `log`

`client` is the sync OpenAI-compatible Yandex client and `aclient` is the async version. They are created by `ma.runtime` so agents can use direct API features without recreating clients.

Only the root `agent.model` is automatically overridden before a run. If an agent owns subagents, `set_context` should update them.

When a reasoning level is selected for the current model, `ma` applies it to the root agent's `model_settings.reasoning` before running. `Agent Default` leaves the agent's own reasoning settings untouched.

## Configuration

`config.json` is optional. Credentials are resolved independently in this priority order:

1. `folder_id` / `api_key` in `config.json`
2. `folder_id` / `api_key` in `.env`
3. `YANDEX_FOLDER_ID` / `YANDEX_API_KEY` in `.env`
4. `YANDEX_FOLDER_ID` / `YANDEX_API_KEY` process environment variables
5. `folder_id` / `api_key` process environment variables

Models can be configured with `model_id`, `model_uri`, or `model`. `model_id` is preferred in examples. Any `%folder_id%` placeholder in configured model IDs is replaced after credentials are resolved.

When `config.json` is missing and both credentials are available, `ma` queries Yandex Cloud's OpenAI-compatible models endpoint and uses the returned model IDs in `/model`. Only Responses-compatible text models with the `gpt://` scheme are shown in the model selector.

The first model option is always `Agent Default`. Selecting it means `ma` does not inject a model into the root agent, so the agent file is responsible for choosing its own model.

## Built-In Data Analyst

`agents/data_analyst/main.py` creates a Code Interpreter container using `context.client` during `set_context`. It configures reusable tools from `filesystem_tools.py`:

- `ls(mask=None)`
- `inspect(filename)`
- `upload(filenames)`

The tools are rooted at `Path.cwd()`, reject absolute paths and `..`, and inspect CSV/XLS/XLSX files with pandas. The `upload` tool copies selected local files into the active Code Interpreter container. The agent instructions require all produced files to be returned in the final answer.

## Built-In Pro Analyst

`agents/pro_analyst/main.py` copies the Data Analyst architecture and adds markdown skills plus advanced local tools:

- host TODO tools for visible multi-step planning
- `list_skills()` and `load_skill(skill_id)`
- `read_file(filename, max_bytes=200000)`
- `write_file(filename, content, overwrite=False)`
- `edit_file(filename, unified_diff)`
- `execute_command(command, args=None, timeout_seconds=60)`

Skills are folders containing `skill.md` frontmatter and instructions. Pro Analyst searches both `Path.cwd()` and `agents/pro_analyst`; current-directory skills override bundled skills with the same ID. `set_context` injects a current skill metadata snapshot into the agent instructions before each run/context update. The agent is instructed to review that snapshot before data exploration and not to reload skill metadata during normal execution. `list_skills()` remains available for explicit user requests to inspect available skills.

Pro Analyst keeps a module-level Code Interpreter container ID and creates the container lazily. Model or reasoning changes rebuild the tool list but reuse the same container ID for both `upload` and `CodeInterpreterTool`. If the host sync client changes, Pro Analyst creates a new matching container instead of reusing a stale ID. A `/reload` re-imports the module and may create a new container. Bundled PPTX/DOCX skills instruct the agent to build those files in Code Interpreter and return them for download, so local `ma` dependencies stay minimal.

Pro Analyst's `upload` tool returns the local name, file ID, container ID, byte count, and exact `container_path` reported by the API. The agent instructions require needed local data files to be uploaded before Code Interpreter data analysis, require Code Interpreter Python to use `container_path` directly, and tell the agent to list the Code Interpreter working directory before retrying if a file is not found.

## UI Lifecycle

The transcript initially mounts a lightweight splash screen and keeps the composer hidden and unfocused. After Textual's first refresh, `ma` starts background initialization for model construction and agent loading, then removes the splash and focuses the composer when startup completes.

The top status line shows the active agent, active model, reasoning level, download mode, and current status. Status values are color-coded: Ready is white, Working is light green, Needs input is blue, and Executing code is yellow.

Modal screens are explicitly centered in Textual CSS so selectors, help, clarification, note detail, and download confirmation appear over the middle of the app.

The composer owns Enter, Ctrl+Enter, and Tab handling. Enter submits, Ctrl+Enter inserts a newline, and Tab completes slash commands. A muted hint line above the composer shows matching command completions while the user types. Completion candidates are dynamic: built-in commands plus loaded agent names/display names, configured model IDs/display names, and Textual theme names.

`/new` starts a fresh chat session by clearing conversation history, session notes/TODOs, transcript widgets, and downloaded Code Interpreter file tracking. It keeps the selected agent, model, and reasoning settings.

Active chat runs are tracked as Textual workers. During a run, pressing Esc once writes a dim warning to the transcript; pressing Esc again within 2 seconds calls `Worker.cancel()` on the active chat worker. Cancellation finalizes any partial assistant/reasoning blocks, records `Run interrupted.`, returns the status to Ready, and does not add a synthetic assistant response to conversation history.

## Tools

Notes tools:

- `create_note(category, title, body, url=None, extra=None)`
- `list_notes(category=None, title_search=None)`
- `clear_notes()`

TODO tools:

- `create_todo(title, position=None)`
- `mark_todo_done(index)`
- `get_next_todo()`

Clarification tools:

- `ask_user_clarification(question, options, allow_custom_answer=False)`

Each clarification option has `title` and `detail`. The tool opens a modal and blocks the current agent run until the user selects an option or enters a custom answer. It returns `{"title": ..., "detail": ...}`.

Stores are in memory for the current chat session. `/notes save` exports notes to markdown.

`extra` is accepted by the tool as text so the Agents SDK can generate a strict JSON schema. The store keeps it as metadata.

`context.log(message)` is a host callback, not a model-callable tool. It writes a light-green message into the transcript so agent code can expose progress or educational breadcrumbs.

## Streaming Flow

The UI calls `Runner.run_streamed(active_agent.agent, input_items)`.

It displays:

- raw text deltas as assistant output
- reasoning text/summary deltas as a live gray reasoning block
- run item events as tool-call/tool-output status lines
- reasoning items as reasoning status lines when the provider includes reasoning summaries or text
- agent update events as handoff status lines
- Code Interpreter code as collapsed expandable blocks
- Code Interpreter logs/output in dark green

Assistant text and reasoning text are streamed as plain text inside their active output blocks. When a block ends, either before a tool/agent event or at run completion, `ma` finalizes the whole block as Markdown so tables, code fences, lists, and other multi-token Markdown constructs render consistently. If reasoning has already streamed, a matching completed reasoning run item is skipped to avoid duplicate transcript entries.

After a run, the app stores `result.to_input_list()` when available so future turns preserve SDK conversation history.

If the chat worker is cancelled, history is left unchanged from before the interrupted user turn. Provider-side cancellation depends on the SDK/client honoring coroutine cancellation, but the UI stops awaiting the stream and becomes usable again.

## Code Interpreter Files

`ma` scans streaming run items and final result surfaces for file annotations containing `file_id` and `filename`. At run completion it checks `new_items`, `raw_responses`, `final_output`, and `to_input_list()` when available.

The download policy is controlled by:

- `/download auto`: download new files immediately.
- `/download ask`: ask before downloading. This is the default.
- `/download skip`: show file names but do not download.
- `/download all`: download every file listed in the active agent's exposed Code Interpreter container.

Downloaded files are written to `Path.cwd()`. Existing filenames are preserved by suffixing new paths, such as `chart-1.png`. Downloaded file IDs are tracked per session to avoid duplicate downloads.
Before suffixing, `ma` checks whether the direct target filename already has the same size and SHA-256 checksum as the downloaded bytes. Identical files are treated as already present and are not written again.

`/download all` requires the active agent to expose `container_id` through props. It uses `client.containers.files.list(container_id=...)` and `client.containers.files.content.retrieve(file_id, container_id=...)`, saves by the basename of the container path, and records downloaded file IDs so later automatic scans do not duplicate them.
