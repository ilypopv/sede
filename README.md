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

## Tests

Install dev dependencies and run tests:

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Test stack includes:

- Unit tests for parsing, formatting, deletion logic, and CLI helper behavior
- Integration tests for real filesystem discovery flows for Claude and Copilot
- Coverage gate at 90% with branch coverage enabled

## CI

GitHub Actions workflow is defined in `.github/workflows/ci.yml`.

CI runs on push and pull request with a Python matrix:

- 3.9
- 3.10
- 3.11
- 3.12

Each CI job:

- Installs project with dev dependencies
- Runs full pytest suite
- Enforces coverage threshold
- Uploads `coverage.xml` artifact for Python 3.12
