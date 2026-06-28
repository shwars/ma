# ma — Mitya's Agent

This is educational reference implementation for learning how coding agents are built based on OpenAI Agents SDK in Yandex Cloud. It consists of the following components:

* Console chat interface inside `ma` directory - starting point for end user. This console application is similar to OpenCode, Codex, Claude Code, etc., and it allows to chat with different agents. It should be startable via `ma` command (defined in repo root).
* Agents are implemented as Python packages inside `agents` directory. Each agent has his own directory, and exposes one main OpenAI Agents SDK `Agent` implementation which is used for chatting. Agents should be dynamically loaded by `ma` chat interface, eg. if new agent is added or code is modified - it should be easily reflected in `ma` chat (maybe after issuing /reload command)

## `ma` Chat Interface

Main `ma` application should allow main text-based streaming chat with current agent. Streaming should ideally support main markdown formatting, including bold, italic, headers, tables formatting "on the fly". It should also support displaying main events: reasoning, tool calls, internal tool calls (eg. web search, file search, etc.), MCP calls, etc. All those categories should be nicely color-coded.

The following main commands should be supported:
/agent - select agent (separate dropdown displaying agents should be provided)
/model - select model (from a section in config.json)
/reload - reload agents from disk
/notes save - save current list of notes on disk as md file
/notes clear - clears current list of notes

config.json sets the overall configuration:
- folder_id
- api_key
- list of available models

Also, `ma` provides two tools that agents can use if they want:
- `notes` tool that supports creating notes with the fields `cateogory`, `title`, `body`. The tool exposes list of function tools: create_note, clear_notes, list_notes (by category, by title search, or all). Ideally notes should also support additional user-defined fields such as url, etc.
- `todo` tool that supports creating TODO lists. It provides functions to create todo item (in arbitrary position), mark item as done, get next item.

Each agent implemented inside `agents` directory receives context object from `ma` application, which includes those tools (each one is a list of tool functions), selected model, folder_id and api_key. It should also indicate if it uses todo or notes tools or not.

If the current agent uses todo or notes tools or both, those tools should be displayed on the right pane during chat dialog, and should be updated in realtime to reflect agent's state.

## Pre-build Agents

As part of the implementation, there are the following agents provided:
- `simple` - simple agent with just WebSearch tool
- `deep_research` - agent that uses todo and notes tool + web search to explore the given topic and collect short summaries of obtained information with URLs.

## Implementation Details

- This implementation is educational, so the code should always prefer simplicity over complexity. It should not check for all possible cases of errors, rather preferring simple logic and some possible run-time errors than checking for all cases and avoiding problems.
- During implementation, you need to keep the updated documentation inside `docs` directory. 
- `docs/Architecture.md` should reflect current version of application architecture, including the interface of communicating with agents (providing context and getting streaming), all tools provided by `ma` application, etc. 
- `docs/History.md` should reflect all major architectural changed and decisions done during development, so that we can always see the progress, what we have tried, what worked and what not.
- `docs/UserManual.md` provides simple user manual, explaining overall idea of `ma`, commands of the interface, available agents, and how to build your own agent.

## Installation & tooling

- Everything should be implemented in Python
- Look for some nice UI library to build text-based UI with colors and tables
- Repo should work just by cloning it from GitHub, but you can also provide some infrastructure for intalling it using pip install or uv