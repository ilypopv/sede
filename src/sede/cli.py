from __future__ import annotations

from datetime import timezone
from typing import Dict, List, Optional

import questionary
import typer
from questionary import Choice
from rich.console import Console
from rich.table import Table

from .discovery import delete_session, discover_sessions
from .models import SessionRecord

app = typer.Typer(add_completion=False, help="Session deleter for coding assistants")
console = Console()

_PROVIDER_LABELS = {
    "claude": "Claude Code",
    "copilot": "GitHub Copilot",
}


@app.command()
def main(
    assistant: Optional[str] = typer.Option(
        None,
        "--assistant",
        "-a",
        help="Assistant to manage: claude or copilot",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt before deletion",
    ),
) -> None:
    provider = _pick_provider(assistant)
    if provider is None:
        raise typer.Exit(code=1)

    sessions = discover_sessions(provider)
    if not sessions:
        console.print(
            f"[yellow]No sessions found for {_PROVIDER_LABELS[provider]}.[/yellow]"
        )
        return

    _print_sessions_table(
        sessions, title=f"Available sessions: {_PROVIDER_LABELS[provider]}"
    )

    selected = _pick_sessions(sessions)
    if not selected:
        console.print("[yellow]Nothing selected. Exit.[/yellow]")
        return

    _print_sessions_table(selected, title="Selected for deletion")

    if not yes:
        confirmed = questionary.confirm(
            f"Delete {len(selected)} session(s)? This operation cannot be undone.",
            default=False,
        ).ask()
        if not confirmed:
            console.print("[yellow]Deletion cancelled.[/yellow]")
            return

    deleted = 0
    failed: List[str] = []
    for session in selected:
        try:
            delete_session(session)
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{session.session_id}: {exc}")

    if deleted:
        console.print(f"[green]Deleted {deleted} session(s).[/green]")
    if failed:
        console.print("[red]Failed to delete:[/red]")
        for row in failed:
            console.print(f"  - {row}")


def _pick_provider(cli_provider: Optional[str]) -> Optional[str]:
    if cli_provider:
        normalized = cli_provider.strip().lower()
        if normalized in _PROVIDER_LABELS:
            return normalized
        console.print("[red]Unknown assistant. Use claude or copilot.[/red]")
        return None

    answer = questionary.select(
        "Choose coding assistant:",
        choices=[
            Choice("Claude Code", value="claude"),
            Choice("GitHub Copilot", value="copilot"),
        ],
    ).ask()
    return answer


def _pick_sessions(sessions: List[SessionRecord]) -> List[SessionRecord]:
    mapping: Dict[str, SessionRecord] = {
        session.session_id: session for session in sessions
    }

    choices = [
        Choice(
            title=(
                f"{session.title} | {session.project_path} | "
                f"{_human_size(session.size_bytes)} | {session.updated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            ),
            value=session.session_id,
        )
        for session in sessions
    ]

    selected_ids = questionary.checkbox(
        "Choose sessions to delete (multiple choice):",
        choices=choices,
        validate=lambda selected: True if selected else "Select at least one session",
    ).ask()

    if not selected_ids:
        return []

    return [mapping[item] for item in selected_ids if item in mapping]


def _print_sessions_table(sessions: List[SessionRecord], title: str) -> None:
    table = Table(title=title, show_lines=False)
    table.add_column("Session", overflow="fold")
    table.add_column("Project", overflow="fold")
    table.add_column("Size", justify="right")
    table.add_column("Updated (UTC)")
    table.add_column("Storage path", overflow="fold")

    for session in sessions:
        table.add_row(
            session.title,
            session.project_path,
            _human_size(session.size_bytes),
            session.updated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            str(session.storage_path),
        )

    console.print(table)


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"
