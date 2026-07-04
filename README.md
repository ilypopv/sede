# sede

Session deleter for coding assistants (`Claude Code` and `GitHub Copilot`).

## Features

- Interactive assistant selection (`claude` or `copilot`)
- Session listing with project path and size
- Multiple choice selection for deletion
- Confirmation prompt before deletion

## Install

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/sede
```

Optional flags:

```bash
.venv/bin/sede --assistant copilot
.venv/bin/sede --assistant claude --yes
```

## Environment Policy

- Do not install dependencies into base/system Python.
- Always use the project-local virtual environment (`.venv`).

## Session Sources

- Claude: `~/.claude/projects/*/*.jsonl`
- Copilot: `~/.copilot/session-state/<session-id>/`
