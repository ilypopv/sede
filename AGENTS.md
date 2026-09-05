# AGENTS.md

## Stack & Layout

- Python >=3.9, `setuptools` `src/` layout. Package `sede` at `src/sede/`; entry `sede.cli:app` (`src/sede/cli.py:38`), also `python -m sede` (`src/sede/__main__.py:1`).
- Core modules: `src/sede/cli.py` (Typer + questionary/prompt_toolkit TUI, `clean` subcommand), `src/sede/discovery.py` (scan/delete per provider), `src/sede/models.py:15` (`SessionRecord` — 7 attrs).
- Deps: `typer`, `questionary`, `rich` (`pyproject.toml:13`); dev adds `pytest`, `pytest-cov`, `pydocstyle`, `ruff`.

## Setup & Run

- Install: `pip install -e .[dev]` (CI at `.github/workflows/ci.yml:33`) or `uv sync --extra dev` / `uv pip install -e .[dev]`.
- CLI: `sede` (TUI), `sede --help` / `sede --version` (custom help `src/sede/cli.py:109`), `sede --assistant {claude|copilot|antigravity|opencode|agy}` (`agy` → `antigravity`), `sede clean [--dry-run] [--yes] [--claude] [--copilot] [--antigravity|--agy] [--opencode]`.
- Docstrings must pass both: `uv run pydocstyle src --convention google` and `uv run ruff check --select D src` — 0 errors.

## Test & CI

- `pytest` — config `pyproject.toml:36` (`testpaths=["tests"]`, `--cov=src/sede --cov-fail-under=90 --cov-report=term-missing --cov-report=xml`, `branch=true`). Keep coverage ≥90%.
- Single test: `pytest tests/test_cli.py::test_clean_dry_run_lists_sessions_without_deleting` or `pytest tests/test_discovery_unit.py -k test_decode`.
- CI: `ubuntu-latest`, Python 3.10–3.14 (`.github/workflows/ci.yml:18`); publish on `v*` tags via trusted publishing (`.github/workflows/publish.yml`).

## Architecture

- Session sources (`src/sede/discovery.py`):
  - Claude `~/.claude/projects/*/*.jsonl` — delete unlinks file + prunes empty parent dir (`discovery.py:152`).
  - Copilot `~/.copilot/session-state/<id>/` — `shutil.rmtree`.
  - Antigravity `~/.gemini/antigravity(-cli)/brain/<id>/` + `conversations/<id>.db*` + row in `conversation_summaries.db` (`discovery.py:170`).
  - OpenCode SQLite `~/.local/share/opencode/opencode.db` (fallback `~/Library/Application Support/opencode/opencode.db`, `XDG_DATA_HOME` honoured; same XDG path for brew/non-brew). Deletes via `PRAGMA foreign_keys=ON` + explicit `DELETE FROM part/message/session` — shared DB never removed (`discovery.py:516`). `discover_sessions("opencode")` returns only chat sessions; caches (`~/.cache/opencode`, `~/.local/state/opencode`, snapshot/log) intentionally excluded (`discovery.py:416`).
- Profile scan: `_find_profile_targets()` (`discovery.py:23`) globs `~/.claude*`, `~/.copilot*`, `~/.gemini*` at `$HOME` and recurses `_PROFILE_SCAN_DEPTH=3` into non-dot subdirs for `projects`/`session-state`/`antigravity*/brain`. Deduplicates via `resolve()`. In tests mock `Path.home()` (see `tests/test_discovery_integration.py`).
- Deletion is permanent; `clean --dry-run` is the safe preview.

## Conventions

- Strict Google docstrings required for every `src/sede/*.py` (`[tool.pydocstyle] convention="google"`, `[tool.ruff.lint.pydocstyle] convention="google"`). Summary: single sentence ending with period, blank line before `Args`/`Returns`/`Raises`/`Attributes`, no blank line after `"""` (D202, auto-fixable). `clean`/`main` Args must match signature; inner `add`/`scan` (`discovery.py:48`) also need docstrings.
- No formatter/typecheck config beyond ruff pydocstyle — match existing style (4-space indent, `from __future__ import annotations`, typed signatures).
- Keep TUI helpers intact: `_TUI_STYLE`, `_BACK_SENTINEL`, `_checkbox_with_back`, `_provider_menu_with_quit` (`src/sede/cli.py:56`); tests mock them instead of driving a terminal.
