# AGENTS.md

## Stack & Layout
- Python >=3.9, `setuptools` (`src/` layout), package `sede` at `src/sede/` (`cli.py:38` entry `sede.cli:app`, also `python -m sede` via `src/sede/__main__.py:1`).
- Core modules: `src/sede/cli.py` (Typer + questionary/prompt_toolkit TUI + `clean` subcommand), `src/sede/discovery.py` (per-provider scan/delete), `src/sede/models.py:15` (`SessionRecord` dataclass).
- Dependencies: `typer`, `questionary`, `rich` (`pyproject.toml:13`); dev adds `pytest`, `pytest-cov`, `pydocstyle`, `ruff` (`pyproject.toml:15`).

## Setup & Run
- Install dev: `pip install -e .[dev]` (CI does this — `.github/workflows/ci.yml:33`) or `uv pip install -e .[dev]` / `uv sync --extra dev`.
- Run CLI: `sede` (TUI), `sede --help` / `sede --version` (custom help at `src/sede/cli.py:107`), `sede --assistant {claude|copilot|antigravity|agy}`, `sede clean [--dry-run] [--yes] [--claude] [--copilot] [--antigravity|--agy]`.
- Verify docstrings: `uv run pydocstyle src --convention google` and `uv run ruff check --select D src` — both must pass with 0 errors.

## Test & CI
- Tests: `pytest` (config at `pyproject.toml:37` — `testpaths = ["tests"]`, `--cov=src/sede --cov-fail-under=90 --cov-report=term-missing --cov-report=xml`, `branch=true`).
- Coverage threshold is 90% — new code must keep coverage green.
- Single test: `pytest tests/test_cli.py::test_clean_dry_run_lists_sessions_without_deleting` (same pattern for discovery: `pytest tests/test_discovery_unit.py -k test_decode`).
- CI matrix: Python 3.10–3.14 on `ubuntu-latest` (`.github/workflows/ci.yml:18`), publish on `v*` tags via trusted publishing (`.github/workflows/publish.yml`).

## Architecture Notes
- Session sources (verify against `src/sede/discovery.py` / `README.md:135`):
  - Claude: `~/.claude/projects/*/*.jsonl` — delete removes file + prunes empty parent dir (`discovery.py:145`).
  - Copilot: `~/.copilot/session-state/<id>/` — recursive `shutil.rmtree`.
  - Antigravity: `~/.gemini/antigravity(-cli)/brain/<id>/` + `conversations/<id>.db*` + row in `conversation_summaries.db` (`discovery.py:163`).
- Profile/home-override scan: `_find_profile_targets()` (`discovery.py:22`) globs `~/.claude*`, `~/.copilot*`, `~/.gemini*` at `$HOME` and recurses `_PROFILE_SCAN_DEPTH=3` into non-dot subdirs to find `projects`/`session-state`/`antigravity*/brain`. Deduplicates via `resolve()`. Mock `Path.home()` in tests (see `tests/test_discovery_integration.py`).
- Deletion is permanent; `clean --dry-run` is the safe preview.

## Conventions
- Strict Google Style docstrings required for every `src/sede/*.py` (`pyproject.toml: [tool.pydocstyle] convention="google"`, `[tool.ruff.lint.pydocstyle] convention="google"`). Every module/class/function needs `Args`/`Returns`/`Raises`/`Attributes` as applicable; summary line must be single sentence ending with period, blank line before `Args`. No blank line after closing `"""` (D202 is enforced — `ruff check --select D` auto-fixes it). `SessionRecord` (`models.py:15`) documents all 7 attributes; `clean` (`cli.py:255`) and `main` (`cli.py:188`) Args must match signature; inner helpers `add`/`scan` (`discovery.py:47`) also have docstrings.
- No formatter/typecheck config beyond ruff pydocstyle — match current style (4-space indent, `from __future__ import annotations`, typed signatures).
- Keep `src/sede/cli.py` TUI helpers (`_TUI_STYLE`, `_BACK_SENTINEL`, `_checkbox_with_back`, `_provider_menu_with_quit`) intact; tests mock them rather than driving a real terminal.
