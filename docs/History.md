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
- Added a color-coded top status line for Ready, Working, Needs input, and Executing code states.
- Changed Code Interpreter downloads so the confirmation modal dismisses before downloads start, and identical existing files are skipped instead of duplicated.
- Moved sync/async OpenAI-compatible Yandex clients into `AgentContext` so agents can reuse host clients instead of recreating them.
- Added `/theme` with direct selection, picker selection, palette access, and Tab completion for Textual theme names.
- Render reasoning stream items with extracted reasoning text/summaries instead of generic event labels.
- Centered modal windows and filtered Textual's built-in theme command so the palette shows one Theme entry.
- Added live streaming for reasoning text/summary deltas when models emit them.
- Changed reasoning rendering to stream in gray, finalize as Markdown, and suppress duplicate completed reasoning items.
- Added the active reasoning level to the top status line.

## 2026-06-30

- Added the built-in Pro Analyst agent with Data Analyst functionality, markdown skill loading, advanced local file tools, and allowlisted command execution.
- Added bundled Pro Analyst skills for PPTX, DOCX, guided data exploration, and markdown-to-PDF workflows.
- Kept PPTX/DOCX generation inside Code Interpreter so local `ma` dependencies do not grow.

## 2026-07-01

- Changed Pro Analyst to reuse one Code Interpreter container across model/reasoning context updates.
- Kept Pro Analyst upload and Code Interpreter tools wired to the same reused container ID.
- Added a skill metadata snapshot to Pro Analyst instructions and strengthened the requirement to call `list_skills()` and `load_skill(...)`.
- Let Pro Analyst use host TODO tools and show the TODO pane for multi-step analysis plans.
- Added double-Escape interruption for active chat runs by tracking the Textual worker, cancelling it on the second Escape within 2 seconds, preserving partial transcript output, and avoiding fake assistant history after cancellation.
- Fixed Pro Analyst upload guidance by returning the API-reported Code Interpreter `container_path`, instructing the agent to use it exactly, and recreating the container if the host client changes.
- Changed Pro Analyst skill handling to use the context-built metadata snapshot before data exploration instead of refreshing skill metadata during normal execution, and strengthened upload-before-analysis instructions.
- Added dynamic `container_id` props, broader final attached-file scanning, and `/download all` for downloading every file from the active agent's Code Interpreter container.
- Added multi-directory agent loading: bundled agents plus the current working directory's `agents/` by default, explicit multi-path `--agents-dir`, local override precedence, and a documented Windows `ma.bat` helper for running from arbitrary directories.

## 2026-07-13

- Added per-directory `ma.ini` persistence for the active agent, selected model, and reasoning level, so folder-specific agents and model configurations restore independently.
- Added persistent per-directory composer history: the last 10 submitted prompts and slash commands are recalled with Up/Down and stored in `ma.ini`.
- Made all launch-directory `.env` values available to agents through `AgentContext.env` and `os.environ`, so project-specific settings also reach ordinary agent code and child processes.
- Added `/save <filename>` for exporting the current structured session as text, Markdown, JSON, or CSV, including finalized model output and runtime events.
