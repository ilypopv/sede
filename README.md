# sede: SEssion DEleter

_Delete archived coding assistant sessions from terminal, fast and safely._

[![CI](https://img.shields.io/github/actions/workflow/status/ilypopv/sede/ci.yml?style=flat-square&label=CI)](https://github.com/ilypopv/sede/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)

## Features

- Interactive TUI flow for provider selection and session deletion
- Supports `Claude Code` and `GitHub Copilot`
- Multi-select deletion with confirmation
- Storage-aware list: title, project path, storage path, size, updated-at
- Safe Claude cleanup: removes selected session file and prunes empty project directory

## Quick Start

Installation pipeline is being finalized.

```bash
# TODO: upcoming release install command(s)
# brew install ...
# winget install ...
```

Temporary local/dev setup:

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

Run:

```bash
.venv/bin/sede
```

Optional flags:

```bash
.venv/bin/sede --assistant copilot
.venv/bin/sede --assistant claude --yes
```

## TUI Preview

Main screen:

```text
   _____ ______ _____  ______
  / ____|  ____|  __ \|  ____|
 | (___ | |__  | |  | | |__
  \___ \|  __| | |  | |  __|
  ____) | |____| |__| | |____
 |_____/|______|_____/|______|

Session Deleter Engine
https://github.com/ilypopv/sede/
Deep clean archived coding assistant sessions from your device.

 Choose coding assistant
 ➤ 1. Claude Code
   Delete archived Claude Code sessions

   2. GitHub Copilot
   Delete archived Copilot sessions

   ↑↓ Navigate  |  Enter / → Select  |  Ctrl+C / Q Quit
```

Session selection screen:

```text
 Choose sessions to delete
 » ○ Session title...
   /Users/you/project-path
   ~/.claude/projects/-Users-you-project/
   1.5 MB | 2026-07-03 09:44 UTC

   ↑↓ Navigate  |  ← Back  |  Space Select  |  A All  |  Enter Delete  |  Ctrl+C / Q Quit
```

## Safety Notes

- Deletion is permanent.
- Claude: deletes selected `.jsonl` session file, then removes parent project dir only if empty.
- Copilot: deletes the selected session directory recursively.
- Always review selected entries before confirming.

## Session Sources

- Claude: `~/.claude/projects/*/*.jsonl`
- Copilot: `~/.copilot/session-state/<session-id>/`

## Roadmap

- Stable package installation via system package managers
- Binary releases for macOS/Windows
- Further UX/QoL enhancements for TUI workflows
