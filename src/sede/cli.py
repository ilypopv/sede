from __future__ import annotations

from datetime import timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union, cast

import questionary
import typer
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from questionary import Choice
from questionary.constants import INVALID_INPUT
from questionary.prompts import common as questionary_common
from questionary.prompts.common import InquirerControl, Separator
from rich.console import Console

from .discovery import delete_session, discover_sessions
from .models import SessionRecord

app = typer.Typer(add_completion=False, help="Session deleter for coding assistants")
console = Console()

_PROVIDER_LABELS = {
    "claude": "Claude Code",
    "copilot": "GitHub Copilot",
}

_BACK_SENTINEL = "__sede_back__"

_APP_BANNER = r"""
   _____ ______ _____  ______ 
  / ____|  ____|  __ \|  ____|
 | (___ | |__  | |  | | |__   
  \___ \|  __| | |  | |  __|  
  ____) | |____| |__| | |____ 
 |_____/|______|_____/|______|
"""


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
    if assistant:
        provider = _pick_provider(assistant)
        if provider is None:
            raise typer.Exit(code=1)
        _run_provider_flow(provider, yes)
        return

    while True:
        provider = _pick_provider(None)
        if provider is None:
            return

        should_back = _run_provider_flow(provider, yes)
        if not should_back:
            return


def _pick_provider(cli_provider: Optional[str]) -> Optional[str]:
    if cli_provider:
        normalized = cli_provider.strip().lower()
        if normalized in _PROVIDER_LABELS:
            return normalized
        console.print("[red]Unknown assistant. Use claude or copilot.[/red]")
        return None

    console.clear()
    _print_home_screen()
    return _provider_menu_with_quit()


def _print_home_screen() -> None:
    console.print(f"[bold cyan]{_APP_BANNER}[/bold cyan]")
    console.print("[bold]Session Deleter Engine[/bold]")
    console.print("[blue]https://github.com/ilypopv/sede/[/blue]")
    console.print(
        "[dim]Deep clean archived coding assistant sessions from your device.[/dim]"
    )
    console.print()


def _run_provider_flow(provider: str, yes: bool) -> bool:
    sessions = discover_sessions(provider)
    if not sessions:
        console.print(
            f"[yellow]No sessions found for {_PROVIDER_LABELS[provider]}.[/yellow]"
        )
        return True

    console.print(f"[bold] Available sessions: {_PROVIDER_LABELS[provider]}[/bold]")
    console.print(f"[dim] {len(sessions)} session(s) loaded.[/dim]")
    console.print()

    selected = _pick_sessions(sessions)
    if selected == _BACK_SENTINEL:
        return True

    if not selected:
        console.print("[yellow]Nothing selected. Exit.[/yellow]")
        return False

    chosen_sessions = cast(List[SessionRecord], selected)
    _print_selected_summary(chosen_sessions)

    if not yes:
        confirmed = questionary.confirm(
            f"Delete {len(selected)} session(s)? This operation cannot be undone.",
            default=False,
        ).ask()
        if not confirmed:
            console.print("[yellow]Deletion cancelled.[/yellow]")
            return False

    deleted = 0
    failed: List[str] = []
    for session in chosen_sessions:
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

    return False


def _pick_sessions(sessions: List[SessionRecord]) -> Union[List[SessionRecord], str]:
    mapping: Dict[str, SessionRecord] = {
        session.session_id: session for session in sessions
    }

    choices: List[Union[Choice, Separator]] = [
        Choice(
            title=_session_choice_title(session),
            value=session.session_id,
        )
        for session in sessions
    ]

    choices.extend(
        [
            Separator(" "),
            Separator(
                "↑↓ Navigate  |  ← Back  |  Space Select  |  A All  |  Enter Delete  |  Ctrl+C / Q Quit"
            ),
        ]
    )

    selected_ids = _checkbox_with_back(
        "Choose sessions to delete",
        choices=choices,
        validate=lambda selected: True if selected else "Select at least one session",
    )

    if selected_ids == _BACK_SENTINEL:
        return _BACK_SENTINEL

    if not selected_ids:
        return []

    return [mapping[item] for item in selected_ids if item in mapping]


def _print_selected_summary(sessions: List[SessionRecord]) -> None:
    console.print("[bold]Selected for deletion:[/bold]")
    for session in sessions:
        console.print(
            f"- {session.title}\n"
            f"  {session.project_path}\n"
            f"  {_human_size(session.size_bytes)} | "
            f"{session.updated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )


def _session_choice_title(session: SessionRecord) -> str:
    storage_hint = _session_storage_hint(session)
    return [
        ("", f"{session.title}\n"),
        ("", f"  {session.project_path}\n"),
        ("fg:#7a7a7a", f"  {storage_hint}\n"),
        (
            "",
            f"  {_human_size(session.size_bytes)} | "
            f"{session.updated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        ),
    ]


def _session_storage_hint(session: SessionRecord) -> str:
    path_for_display = session.storage_path
    if session.provider == "claude":
        path_for_display = session.storage_path.parent

    full_path = str(path_for_display)
    home_path = str(Path.home())
    if full_path.startswith(home_path):
        return full_path.replace(home_path, "~", 1)
    return full_path


def _checkbox_with_back(
    message: str,
    choices: Sequence[Union[Choice, Separator]],
    validate,
) -> Union[List[str], str, None]:  # pragma: no cover
    if not callable(validate):
        raise ValueError("validate must be callable")

    control = InquirerControl(choices)

    def get_prompt_tokens() -> List[Tuple[str, str]]:
        if control.is_answered:
            return [("class:answer", "done")]
        return [("class:question", f" {message} ")]

    def get_selected_values() -> List[str]:
        selected_values = [choice.value for choice in control.get_selected_values()]
        return [value for value in selected_values if isinstance(value, str)]

    def perform_validation(selected_values: List[str]) -> bool:
        verdict = validate(selected_values)
        valid = verdict is True

        if not valid:
            if verdict is False:
                error_text = INVALID_INPUT
            else:
                error_text = str(verdict)
            error_message = FormattedText([("class:validation-toolbar", error_text)])
        control.error_message = (
            error_message if not valid and control.submission_attempted else None
        )

        return valid

    layout = questionary_common.create_inquirer_layout(
        control,
        get_prompt_tokens,
    )

    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _abort(event):
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    @bindings.add("q", eager=True)
    @bindings.add("Q", eager=True)
    def _quit(event):
        control.is_answered = True
        event.app.exit(result=None)

    @bindings.add(" ", eager=True)
    def _toggle(_event):
        pointed_choice = control.get_pointed_at().value
        if pointed_choice in control.selected_options:
            control.selected_options.remove(pointed_choice)
        else:
            control.selected_options.append(pointed_choice)
        perform_validation(get_selected_values())

    @bindings.add("a", eager=True)
    def _select_all(_event):
        control.selected_options = [
            item.value
            for item in control.choices
            if not isinstance(item, Separator) and not item.disabled
        ]
        perform_validation(get_selected_values())

    def _move_cursor_down(_event):
        control.select_next()
        while not control.is_selection_valid():
            control.select_next()

    def _move_cursor_up(_event):
        control.select_previous()
        while not control.is_selection_valid():
            control.select_previous()

    @bindings.add(Keys.Down, eager=True)
    def _down(event):
        _move_cursor_down(event)

    @bindings.add(Keys.Up, eager=True)
    def _up(event):
        _move_cursor_up(event)

    @bindings.add(Keys.Left, eager=True)
    def _go_back(event):
        control.is_answered = True
        event.app.exit(result=_BACK_SENTINEL)

    @bindings.add(Keys.ControlM, eager=True)
    def _submit(event):
        selected_values = get_selected_values()
        control.submission_attempted = True
        if perform_validation(selected_values):
            control.is_answered = True
            event.app.exit(result=selected_values)

    @bindings.add(Keys.Any)
    def _other(_event):
        return None

    question = Application(
        layout=Layout(layout.container) if isinstance(layout, Layout) else layout,
        key_bindings=bindings,
        style=None,
    )

    try:
        return question.run()
    except KeyboardInterrupt:
        return None


def _provider_menu_with_quit() -> Optional[str]:  # pragma: no cover
    choices: List[Choice] = [
        Choice(
            "1. Claude Code\n   Delete archived Claude Code sessions\n",
            value="claude",
        ),
        Choice(
            "2. GitHub Copilot\n   Delete archived Copilot sessions\n",
            value="copilot",
        ),
        Separator("↑↓ Navigate  |  Enter / → Select  |  Ctrl+C / Q Quit"),
    ]

    control = InquirerControl(choices, pointer="➤")

    def get_prompt_tokens() -> List[Tuple[str, str]]:
        return [("class:question", " Choose coding assistant ")]

    layout = questionary_common.create_inquirer_layout(
        control,
        get_prompt_tokens,
    )

    bindings = KeyBindings()

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.ControlQ, eager=True)
    def _abort(event):
        event.app.exit(result=None)

    @bindings.add("q", eager=True)
    @bindings.add("Q", eager=True)
    def _quit(event):
        event.app.exit(result=None)

    def _move_cursor_down(_event):
        control.select_next()
        while not control.is_selection_valid():
            control.select_next()

    def _move_cursor_up(_event):
        control.select_previous()
        while not control.is_selection_valid():
            control.select_previous()

    @bindings.add(Keys.Down, eager=True)
    def _down(event):
        _move_cursor_down(event)

    @bindings.add(Keys.Up, eager=True)
    def _up(event):
        _move_cursor_up(event)

    @bindings.add(Keys.ControlM, eager=True)
    def _submit(event):
        pointed = control.get_pointed_at()
        control.is_answered = True
        event.app.exit(result=pointed.value if isinstance(pointed.value, str) else None)

    @bindings.add(Keys.Right, eager=True)
    def _submit_right(event):
        pointed = control.get_pointed_at()
        control.is_answered = True
        event.app.exit(result=pointed.value if isinstance(pointed.value, str) else None)

    @bindings.add(Keys.Any)
    def _other(_event):
        return None

    question = Application(
        layout=Layout(layout.container) if isinstance(layout, Layout) else layout,
        key_bindings=bindings,
        style=None,
    )

    return question.run()


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
