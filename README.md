# sede: SEssion DEleter

<img src="https://raw.githubusercontent.com/ilypopv/sede/main/imgs/sede.png" alt="logo" width="180" align="left">

_Delete archived coding assistant sessions from terminal, fast and safely._

[![CI](https://img.shields.io/github/actions/workflow/status/ilypopv/sede/ci.yml?style=flat-square&label=CI)](https://github.com/ilypopv/sede/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)

<br clear="left" />

## Features

- Interactive TUI flow for provider selection and session deletion
- Supports `Claude Code`, `GitHub Copilot`, and `Antigravity`
- Multi-select deletion with confirmation
- Storage-aware list: title, project path, storage path, size, updated-at
- Safe Claude cleanup: removes selected session file and prunes empty project directory
- Non-interactive `clean` command for scripted, bulk deletion with a `--dry-run` preview

## Installation

**Recommended**

```bash
uv tool install sede
```

Or

```bash
pipx install sede
```

## Run

After installation, run:

```bash
sede
```

## Bulk Cleanup

Delete every discovered session, across all providers, without the interactive TUI:

```bash
sede clean
```

Preview what would be deleted first, without touching anything:

```bash
sede clean --dry-run
```

Limit cleanup to one provider (`--claude`, `--copilot`, `--antigravity`/`--agy`):

```bash
sede clean --copilot --dry-run
sede clean --claude --yes
```

Skip the confirmation prompt with `--yes`/`-y`. If some session files require elevated
permissions to remove, re-run with `sudo`:

```bash
sudo sede clean --dry-run
sudo sede clean --yes
```

## TUI Preview

Main screen:

```text
               _      
  ___  ___  __| | ___ 
 / __|/ _ \/ _` |/ _ \
 \__ \  __/ (_| |  __/
 |___/\___|\__,_|\___|

Session Deleter
https://github.com/ilypopv/sede/
Deep clean archived coding assistant sessions from your device.

 Choose coding assistant
 ➤ 1. Claude Code
   Delete archived Claude Code sessions

   2. GitHub Copilot
   Delete archived Copilot sessions

   3. Antigravity
   Delete archived Antigravity sessions

↑↓ Navigate  |  Enter / → Select  |  Ctrl+C / Q Quit
```

Session selection screen:

```text
 Available sessions: Claude Code
 1 session(s) loaded. Total size: 1.5 MB.

 Choose sessions to delete
 » ○ 1. Session title...
     Project:  /Users/you/project-path
     Storage:  ~/.claude/projects/-Users-you-project/
     Details:  1.5 MB  •  2026-07-03 09:44 UTC

↑↓ Navigate  |  ← Back  |  Space Select  |  A Toggle All  |  Enter Delete  |  Ctrl+C / Q Quit
```

When no sessions are found for a provider, the same screen layout is shown instead:

```text
 Available sessions: Claude Code
 0 session(s) loaded. Total size: 0 B.

 No sessions found for Claude Code.

 Press any key to go back...
```

## Safety Notes

- Deletion is permanent.
- Claude: deletes selected `.jsonl` session file, then removes parent project dir only if empty.
- Copilot: deletes the selected session directory recursively.
- Antigravity: deletes the selected conversation directory recursively.
- Always review selected entries before confirming.

## Session Sources

- Claude: `~/.claude/projects/*/*.jsonl`
- Copilot: `~/.copilot/session-state/<session-id>/`
- Antigravity: `~/.gemini/antigravity-cli/brain/<session-id>/` and `~/.gemini/antigravity/brain/<session-id>/`
