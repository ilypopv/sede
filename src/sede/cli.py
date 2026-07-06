from __future__ import annotations

from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union, cast

import questionary
import typer
from prompt_toolkit.application import Application
from prompt_toolkit.filters import Always, IsDone
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import LayoutDimension
from questionary import Choice
from questionary.constants import INVALID_INPUT
from questionary.prompts import common as questionary_common
from questionary.prompts.common import InquirerControl, Separator
from rich.console import Console

from . import __version__
from .discovery import delete_session, discover_sessions
from .models import SessionRecord

app = typer.Typer(
    add_completion=False,
    add_help_option=False,
    no_args_is_help=False,
    help="Session deleter for coding assistants",
)
console = Console()

ValidateSelectionFn = Callable[[List[str]], Union[bool, str]]
FormattedChoiceTitle = List[Tuple[str, str]]

_PROVIDER_LABELS = {
    "claude": "Claude Code",
    "copilot": "GitHub Copilot",
}

_BACK_SENTINEL = "__sede_back__"

_APP_BANNER = r"""
               _      
  ___  ___  __| | ___ 
 / __|/ _ \/ _` |/ _ \
 \__ \  __/ (_| |  __/
 |___/\___|\__,_|\___|
"""

_HELP_COMMANDS = [
    ("sede", "Main menu"),
    ("sede --help", "Show help"),
    ("sede --version", "Show version"),
]

_HELP_OPTIONS = [
    ("--assistant, -a TEXT", "Assistant to manage: claude or copilot"),
    ("--yes, -y", "Skip confirmation prompt before deletion"),
]

_HELP_COL_WIDTH = 28


def _print_help_screen() -> None:
    """Prints the branded help screen with command reference."""
    console.print(f"[bold cyan]{_APP_BANNER}[/bold cyan]")
    console.print(f"[bold]Session Deleter v{__version__}[/bold]")
    console.print("[blue]https://github.com/ilypopv/sede/[/blue]")
    console.print()
    console.print("[bold]COMMANDS[/bold]")
    for cmd, desc in _HELP_COMMANDS:
        console.print(f"  [cyan]{cmd:<{_HELP_COL_WIDTH}}[/cyan]{desc}")
    console.print()
    console.print("[bold]OPTIONS[/bold]")
    for opt, desc in _HELP_OPTIONS:
        console.print(f"  [cyan]{opt:<{_HELP_COL_WIDTH}}[/cyan]{desc}")


def _create_inquirer_layout_with_footer(
    control: InquirerControl,
    get_prompt_tokens: Callable[[], List[Tuple[str, str]]],
    footer: str,
) -> Layout:
    """Creates the default questionary layout with an external footer row."""

    layout = questionary_common.create_inquirer_layout(control, get_prompt_tokens)
    if not isinstance(layout.container, HSplit):
        return layout

    for child in layout.container.children:
        if (
            isinstance(child, ConditionalContainer)
            and isinstance(child.content, Window)
            and child.content.content is control
        ):
            child.content.dont_extend_height = Always()
            break

    footer_control = FormattedTextControl(
        text=lambda: [("", "\n"), ("class:text", footer)],
    )
    layout.container.children.append(
        ConditionalContainer(
            Window(
                height=LayoutDimension.exact(2),
                content=footer_control,
            ),
            filter=~IsDone(),
        )
    )
    return layout


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
    show_help: bool = typer.Option(
        False,
        "--help",
        "-h",
        is_eager=True,
        help="Show help and exit",
    ),
    show_version: bool = typer.Option(
        False,
        "--version",
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Application entrypoint.

    Args:
        help: Whether to show the help screen and exit.
        version: Whether to show the version and exit.
        assistant: Optional fixed assistant provider from CLI flags.
        yes: Whether to skip the deletion confirmation prompt.
    """

    if show_help:
        _print_help_screen()
        raise typer.Exit()

    if show_version:
        console.print(f"sede v{__version__}")
        raise typer.Exit()

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
    """Resolves provider from CLI option or interactive menu selection."""

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
    """Renders the branded home screen banner and project info."""

    console.print(f"[bold cyan]{_APP_BANNER}[/bold cyan]")
    console.print(f"[bold]Session Deleter v{__version__}[/bold]")
    console.print("[blue]https://github.com/ilypopv/sede/[/blue]")
    console.print(
        "[dim]Deep clean archived coding assistant sessions from your device.[/dim]"
    )
    console.print()


def _run_provider_flow(provider: str, yes: bool) -> bool:
    """Runs one provider-specific selection and deletion flow.

    Args:
        provider: Provider key selected by user.
        yes: Whether confirmation is skipped.

    Returns:
        True when caller should navigate back to provider menu, else False.
    """

    sessions = discover_sessions(provider)
    _print_provider_header(provider, sessions)

    if not sessions:
        console.print(
            f"[yellow] No sessions found for {_PROVIDER_LABELS[provider]}.[/yellow]"
        )
        console.print()
        _wait_for_any_key(" Press any key to go back... ")
        return True

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


def _print_provider_header(provider: str, sessions: List[SessionRecord]) -> None:
    """Renders the secondary screen header shared by empty and loaded states.

    Args:
        provider: Provider key whose sessions are being displayed.
        sessions: Discovered sessions for the provider (may be empty).
    """

    total_size = sum(session.size_bytes for session in sessions)
    console.print(f"[bold] Available sessions: {_PROVIDER_LABELS[provider]}[/bold]")
    console.print(
        f"[dim] {len(sessions)} session(s) loaded. "
        f"Total size: {_human_size(total_size)}.[/dim]"
    )
    console.print()


def _pick_sessions(sessions: List[SessionRecord]) -> Union[List[SessionRecord], str]:
    """Prompts user to choose one or more sessions for deletion."""

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

    selected_ids = _checkbox_with_back(
        "Choose sessions to delete",
        choices=choices,
        footer=(
            "↑↓ Navigate  |  ← Back  |  Space Select  |  A Toggle All  |  Enter Delete  |  Ctrl+C / Q Quit"
        ),
        validate=lambda selected: True if selected else "Select at least one session",
    )

    if selected_ids == _BACK_SENTINEL:
        return _BACK_SENTINEL

    if not selected_ids:
        return []

    return [mapping[item] for item in selected_ids if item in mapping]


def _print_selected_summary(sessions: List[SessionRecord]) -> None:
    """Prints a compact summary of selected sessions before deletion."""

    console.print("[bold]Selected for deletion:[/bold]")
    for session in sessions:
        console.print(
            f"- {session.title}\n"
            f"  {session.project_path}\n"
            f"  {_human_size(session.size_bytes)} | "
            f"{session.updated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )


def _session_choice_title(session: SessionRecord) -> FormattedChoiceTitle:
    """Builds a formatted multi-line title row for a session choice item."""

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
    """Returns a display-friendly storage path for a session."""

    path_for_display = session.storage_path
    if session.provider == "claude":
        path_for_display = session.storage_path.parent

    full_path = str(path_for_display)
    home_path = str(Path.home())
    if full_path.startswith(home_path):
        return full_path.replace(home_path, "~", 1)
    return full_path


def _wait_for_any_key(message: str) -> None:  # pragma: no cover
    """Blocks until the user presses any key, including arrow keys.

    Uses a bare prompt_toolkit ``Application`` (no input buffer) so that
    every keypress, arrow keys included, falls through to our ``Keys.Any``
    binding instead of being consumed by default buffer/history bindings.

    Note: the binding intentionally omits ``eager=True``. Eager bindings
    are matched before prompt_toolkit's built-in cursor-position-response
    (CPR) handler, which would otherwise cause the terminal's automatic CPR
    reply (sent moments after the screen renders) to be misread as a user
    keypress and exit the screen on its own.

    Args:
        message: Prompt text shown while waiting for input.
    """

    control = FormattedTextControl(text=[("class:question", message)])
    layout = Layout(Window(content=control))

    bindings = KeyBindings()

    @bindings.add(Keys.Any)
    def _continue(event: Any) -> None:
        event.app.exit(result=None)

    application = Application(layout=layout, key_bindings=bindings, style=None)

    try:
        application.run()
    except KeyboardInterrupt:
        return


def _compute_toggled_select_all(
    choices: Sequence[Union[Choice, Separator]],
    selected_options: List[Any],
) -> List[Any]:
    """Computes the next selection state for the "select/deselect all" key.

    Selects every selectable choice when not all of them are currently
    selected; deselects everything when they already are, so a single key
    toggles between "select all" and "clear selection".

    Args:
        choices: All choices shown in the checkbox prompt, including
            separators and disabled items.
        selected_options: Currently selected choice values.

    Returns:
        The new list of selected values.
    """

    selectable_values = [
        item.value
        for item in choices
        if not isinstance(item, Separator) and not item.disabled
    ]
    all_selected = bool(selectable_values) and all(
        value in selected_options for value in selectable_values
    )
    return [] if all_selected else selectable_values


def _checkbox_with_back(
    message: str,
    choices: Sequence[Union[Choice, Separator]],
    footer: str,
    validate: ValidateSelectionFn,
) -> Union[List[str], str, None]:  # pragma: no cover
    """Runs custom checkbox prompt with explicit back and quit controls."""

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

    layout = _create_inquirer_layout_with_footer(
        control,
        get_prompt_tokens,
        footer,
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
    def _toggle_select_all(_event):
        control.selected_options = _compute_toggled_select_all(
            control.choices, control.selected_options
        )
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
    def _down(event: Any) -> None:
        _move_cursor_down(event)

    @bindings.add(Keys.Up, eager=True)
    def _up(event: Any) -> None:
        _move_cursor_up(event)

    @bindings.add(Keys.Left, eager=True)
    def _go_back(event: Any) -> None:
        control.is_answered = True
        event.app.exit(result=_BACK_SENTINEL)

    @bindings.add(Keys.ControlM, eager=True)
    def _submit(event: Any) -> None:
        selected_values = get_selected_values()
        control.submission_attempted = True
        if perform_validation(selected_values):
            control.is_answered = True
            event.app.exit(result=selected_values)

    @bindings.add(Keys.Any)
    def _other(_event: Any) -> None:
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
    """Shows provider selection menu with keyboard shortcuts for quit/select."""

    choices: List[Choice] = [
        Choice(
            "1. Claude Code\n   Delete archived Claude Code sessions\n",
            value="claude",
        ),
        Choice(
            "2. GitHub Copilot\n   Delete archived Copilot sessions",
            value="copilot",
        ),
    ]

    control = InquirerControl(choices, pointer="➤")

    def get_prompt_tokens() -> List[Tuple[str, str]]:
        return [("class:question", " Choose coding assistant ")]

    layout = _create_inquirer_layout_with_footer(
        control,
        get_prompt_tokens,
        "↑↓ Navigate  |  Enter / → Select  |  Ctrl+C / Q Quit",
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
    def _down(event: Any) -> None:
        _move_cursor_down(event)

    @bindings.add(Keys.Up, eager=True)
    def _up(event: Any) -> None:
        _move_cursor_up(event)

    @bindings.add(Keys.ControlM, eager=True)
    def _submit(event: Any) -> None:
        pointed = control.get_pointed_at()
        control.is_answered = True
        event.app.exit(result=pointed.value if isinstance(pointed.value, str) else None)

    @bindings.add(Keys.Right, eager=True)
    def _submit_right(event: Any) -> None:
        pointed = control.get_pointed_at()
        control.is_answered = True
        event.app.exit(result=pointed.value if isinstance(pointed.value, str) else None)

    @bindings.add(Keys.Any)
    def _other(_event: Any) -> None:
        return None

    question = Application(
        layout=Layout(layout.container) if isinstance(layout, Layout) else layout,
        key_bindings=bindings,
        style=None,
    )

    return question.run()


def _human_size(size_bytes: int) -> str:
    """Formats byte count into human-readable units."""

    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"
