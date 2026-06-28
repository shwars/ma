# History

## 2026-06-28

- Chose Textual for the terminal UI because it naturally supports panes, selectors, inputs, and reactive state.
- Chose a vertical-slice first implementation: working CLI, dynamic agent loading, streaming, notes/TODO panes, and documentation.
- Chose Yandex Cloud through the OpenAI-compatible Responses API, matching the course notebook pattern with `AsyncOpenAI` and `OpenAIResponsesModel`.
- Chose a global `agent` variable as the required agent package contract. This keeps educational agents close to plain OpenAI Agents SDK examples.
- Added optional `set_context(context)` and `get_props()` hooks for host-provided tools and UI metadata.
- Made notes and TODOs session-scoped. Persistence is explicit through `/notes save`.
- Imported local agent modules by file path to avoid a name collision with the SDK package named `agents`.
- Added `/exit`, `/reasoning`, app command palette entries, color-coded transcript lines without role labels, and whitespace filtering for empty streamed output.
- Split notes and TODOs into separate panes, added selectable note detail modal, and moved input to a full-width multiline composer.
- Changed streamed assistant rendering to show plain text while deltas arrive, then finalize each completed assistant block as Markdown.
- Improved TODO pane rendering with no-wrap rows, horizontal scrolling, Unicode checkbox markers, and light-green completed items.
- Added slash-command Tab completion with muted completion hints, plus a startup splash shown before background initialization finishes.
- Changed startup so the composer stays hidden and disabled until initialization completes.

## 2026-06-29

- Added `context.log(...)` as a host callback for light-green agent progress messages.
- Added a model-callable clarification tool that opens a modal, waits for user selection or custom input, and returns the selected title/detail pair.
- Added the built-in Data Analyst agent with reusable local filesystem tools and Yandex Code Interpreter integration.
- Added Code Interpreter rendering: generated code appears collapsed, logs/output appear in dark green, and returned files follow `/download auto|ask|skip`.
- Added `/new` and `/help`, direct `/agent <name>` and `/model <model>` switching, dynamic Tab completion for agents/models, and a single palette Download command that opens mode selection.
