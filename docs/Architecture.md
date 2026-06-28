# Architecture

`ma` is a small educational terminal chat application built around the OpenAI Agents SDK and Yandex Cloud's OpenAI-compatible API.

## Application Shape

- `ma.cli` exposes the `ma` console command.
- `ma.app` contains the Textual UI: transcript, input line, selectors, and optional right-side notes/TODO panes.
- `ma.config` loads optional `config.json`, optional `.env`, and process environment credentials.
- `ma.runtime` creates the Yandex-backed Agents SDK model:
  - `AsyncOpenAI(base_url="https://ai.api.cloud.yandex.net/v1", api_key=..., project=folder_id)`
  - `OpenAIResponsesModel(model=model_uri, openai_client=...)`
- `ma.agent_loader` discovers and imports user agents from `agents/<name>/main.py`.
- `ma.stores` and `ma.tools` provide session-scoped notes and TODO tools.

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

The loader imports agent files by path under an internal module name. This avoids colliding with the OpenAI Agents SDK package, which is also named `agents`.

## Context Object

Agents receive an `AgentContext` with:

- `config`
- `selected_model`
- `model`
- `reasoning_level`
- `folder_id`
- `api_key`
- `notes_store`
- `todo_store`
- `notes_tools`
- `todo_tools`

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

## UI Lifecycle

The transcript initially mounts a lightweight splash screen and keeps the composer hidden and unfocused. After Textual's first refresh, `ma` starts background initialization for model construction and agent loading, then removes the splash and focuses the composer when startup completes.

The composer owns Enter, Ctrl+Enter, and Tab handling. Enter submits, Ctrl+Enter inserts a newline, and Tab completes slash commands. A muted hint line above the composer shows matching command completions while the user types.

## Tools

Notes tools:

- `create_note(category, title, body, url=None, extra=None)`
- `list_notes(category=None, title_search=None)`
- `clear_notes()`

TODO tools:

- `create_todo(title, position=None)`
- `mark_todo_done(index)`
- `get_next_todo()`

Stores are in memory for the current chat session. `/notes save` exports notes to markdown.

`extra` is accepted by the tool as text so the Agents SDK can generate a strict JSON schema. The store keeps it as metadata.

## Streaming Flow

The UI calls `Runner.run_streamed(active_agent.agent, input_items)`.

It displays:

- raw text deltas as assistant output
- run item events as tool-call/tool-output status lines
- agent update events as handoff status lines

Assistant text is streamed as plain text inside the active output block. When the block ends, either before a tool/agent event or at run completion, `ma` finalizes the whole block as Markdown so tables, code fences, lists, and other multi-token Markdown constructs render consistently.

After a run, the app stores `result.to_input_list()` when available so future turns preserve SDK conversation history.
