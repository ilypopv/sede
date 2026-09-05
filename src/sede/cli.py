"""Command-line interface for sede.

Provides the Typer application, interactive TUI flows (provider selection
and session picking), and the non-interactive ``clean`` command for bulk
deletion of archived assistant sessions.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Union, cast

import questionary
import typer
from prompt_toolkit.application import Application
from prompt_toolkit.filters import Always, IsDone
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.containers import ScrollOffsets
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension, LayoutDimension
from prompt_toolkit.styles import Style
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

ValidateSelectionFn = Callable[[list[str]], Union[bool, str]]
FormattedChoiceTitle = list[tuple[str, str]]

_PROVIDER_LABELS = {
    "claude": "Claude Code",
    "copilot": "GitHub Copilot",
    "antigravity": "Antigravity",
    "opencode": "OpenCode",
}

_TUI_STYLE = Style.from_dict(
    {
        "question": "bold",
        "pointer": "fg:ansicyan bold",
        "selected": "noinherit",
        "highlighted": "noinherit",
        "separator": "fg:ansigray",
        "instruction": "fg:ansigray",
        "text": "",
        "session-title": "bold",
        "session-label": "fg:ansigray",
        "session-path": "fg:ansicyan",
        "session-storage": "fg:ansigray",
        "session-meta": "",
        "session-divider": "fg:ansigray",
        "validation-toolbar": "fg:ansired bold",
    }
)

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
    ("sede clean", "Delete all sessions for every provider, no prompts"),
    ("sede --help", "Show help"),
    ("sede --version", "Show version"),
]

_HELP_OPTIONS = [
    ("--assistant, -a TEXT", "Assistant to manage: claude, copilot, antigravity, or opencode"),
    ("--yes, -y", "Skip confirmation prompt before deletion"),
]

_HELP_CLEAN_OPTIONS = [
    ("--dry-run", "Show what would be deleted without deleting anything"),
    ("--yes, -y", "Skip confirmation prompt before deletion"),
    ("--claude", "Only clean Claude Code sessions"),
    ("--copilot", "Only clean GitHub Copilot sessions"),
    ("--antigravity, --agy", "Only clean Antigravity sessions"),
    ("--opencode", "Only clean OpenCode sessions"),
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
    console.print()
    console.print("[bold]CLEAN OPTIONS[/bold]")
    for opt, desc in _HELP_CLEAN_OPTIONS:
        console.print(f"  [cyan]{opt:<{_HELP_COL_WIDTH}}[/cyan]{desc}")


def _choices_height_dimension() -> Dimension:
    """Calculates available vertical height for the choices list to fit on screen.

    Returns:
        A Dimension with a minimum of 1 line and a maximum sized to the
        current terminal height, reserving space for surrounding UI chrome.
    """
    term_height = shutil.get_terminal_size((80, 24)).lines
    # Reserve lines for banner + info (~11), provider menu prompt (~2),
    # provider header (~3), sessions prompt (~1), footer (~2)
    max_height = max(4, term_height - 19)
    return Dimension(min=1, max=max_height)


def _create_inquirer_layout_with_footer(
    control: InquirerControl,
    get_prompt_tokens: Callable[[], list[tuple[str, str]]],
    footer: str,
) -> Layout:
    """Creates the default questionary layout with an external footer row.

    Args:
        control: Inquirer control rendering the choice list.
        get_prompt_tokens: Callback returning the prompt's formatted tokens.
        footer: Footer text shown below the choice list.

    Returns:
        The questionary layout with the footer row appended.
    """
    layout = questionary_common.create_inquirer_layout(control, get_prompt_tokens)
    if not isinstance(layout.container, HSplit):
        return layout

    control.show_cursor = False
    for child in layout.container.children:
        if (
            isinstance(child, ConditionalContainer)
            and isinstance(child.content, Window)
            and child.content.content is control
        ):
            child.content.dont_extend_height = Always()
            child.content.always_hide_cursor = Always()
            child.content.height = _choices_height_dimension
            child.content.scroll_offsets = ScrollOffsets(top=0, bottom=4)
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


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    assistant: str | None = typer.Option(
        None,
        "--assistant",
        "-a",
        help="Assistant to manage: claude, copilot, antigravity, or opencode",
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
        ctx: Typer context, used to detect whether a subcommand (e.g.
            ``clean``) is being dispatched instead of the default TUI flow.
        assistant: Optional fixed assistant provider from CLI flags.
        yes: Whether to skip the deletion confirmation prompt.
        show_help: Whether to show the help screen and exit.
        show_version: Whether to show the version and exit.
    """
    if show_help:
        _print_help_screen()
        raise typer.Exit()

    if show_version:
        console.print(f"sede v{__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

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


@app.command()
def clean(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be deleted without deleting anything",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt before deletion",
    ),
    claude: bool = typer.Option(
        False, "--claude", help="Only clean Claude Code sessions"
    ),
    copilot: bool = typer.Option(
        False, "--copilot", help="Only clean GitHub Copilot sessions"
    ),
    antigravity: bool = typer.Option(
        False, "--antigravity", "--agy", help="Only clean Antigravity sessions"
    ),
    opencode: bool = typer.Option(
        False, "--opencode", help="Only clean OpenCode sessions"
    ),
) -> None:
    """Deletes every discovered session for the selected provider(s).

    With no provider flag, cleans every supported provider. Combine with
    ``--dry-run`` to preview what would be deleted, or ``--yes`` to skip the
    confirmation prompt.

    Args:
        dry_run: Whether to preview deletions without modifying the filesystem.
        yes: Whether to skip the confirmation prompt before deletion.
        claude: Whether to limit cleanup to Claude Code sessions.
        copilot: Whether to limit cleanup to GitHub Copilot sessions.
        antigravity: Whether to limit cleanup to Antigravity sessions.
        opencode: Whether to limit cleanup to OpenCode sessions.
    """
    selected_providers = [
        provider
        for provider, flag in (
            ("claude", claude),
            ("copilot", copilot),
            ("antigravity", antigravity),
            ("opencode", opencode),
        )
        if flag
    ] or list(_PROVIDER_LABELS)

    sessions_by_provider = {
        provider: discover_sessions(provider) for provider in selected_providers
    }
    all_sessions = [
        session
        for sessions in sessions_by_provider.values()
        for session in sessions
    ]

    if not all_sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    total_size = sum(session.size_bytes for session in all_sessions)
    provider_names = ", ".join(_PROVIDER_LABELS[p] for p in selected_providers)
    console.print(
        f"[bold]{len(all_sessions)} session(s) found across {provider_names}. "
        f"Total size: {_human_size(total_size)}.[/bold]"
    )
    console.print()
    _print_clean_sessions(sessions_by_provider)

    if dry_run:
        console.print()
        console.print(
            f"[cyan]Dry run: {len(all_sessions)} session(s) would be deleted. "
            "No files were changed.[/cyan]"
        )
        return

    if not yes:
        console.print()
        confirmed = questionary.confirm(
            f"Delete {len(all_sessions)} session(s)? This operation cannot be undone.",
            default=False,
        ).ask()
        if not confirmed:
            console.print("[yellow]Cleanup cancelled.[/yellow]")
            return

    deleted = 0
    failed: list[str] = []
    for session in all_sessions:
        try:
            delete_session(session)
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{session.session_id}: {exc}")

    console.print()
    if deleted:
        console.print(f"[green]Deleted {deleted} session(s).[/green]")
    if failed:
        console.print("[red]Failed to delete:[/red]")
        for row in failed:
            console.print(f"  - {row}")


def _print_clean_sessions(
    sessions_by_provider: dict[str, list[SessionRecord]],
) -> None:
    """Prints a per-provider listing of sessions targeted by `clean`.

    Args:
        sessions_by_provider: Discovered sessions keyed by provider, for the
            providers selected on the `clean` command line.
    """
    for provider, sessions in sessions_by_provider.items():
        if not sessions:
            continue
        total_size = sum(session.size_bytes for session in sessions)
        console.print(
            f"[bold]{_PROVIDER_LABELS[provider]}[/bold]: "
            f"{len(sessions)} session(s), {_human_size(total_size)}"
        )
        for session in sessions:
            console.print(
                f"  - {session.title}\n"
                f"    {session.project_path}\n"
                f"    {_human_size(session.size_bytes)} | "
                f"{session.updated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )
        console.print()


def _pick_provider(cli_provider: str | None) -> str | None:
    """Resolves provider from CLI option or interactive menu selection.

    Args:
        cli_provider: Provider value passed via the `--assistant` flag, or
            None to fall back to the interactive menu.

    Returns:
        The resolved provider key, or None when the value is invalid or the
        user quits the interactive menu.
    """
    if cli_provider:
        normalized = cli_provider.strip().lower()
        if normalized == "agy":
            normalized = "antigravity"
        if normalized in _PROVIDER_LABELS:
            return normalized
        console.print(
            "[red]Unknown assistant. Use claude, copilot, antigravity, or opencode.[/red]"
        )
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

    chosen_sessions = cast(list[SessionRecord], selected)
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
    failed: list[str] = []
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


def _print_provider_header(provider: str, sessions: list[SessionRecord]) -> None:
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


def _pick_sessions(sessions: list[SessionRecord]) -> list[SessionRecord] | str:
    """Prompts user to choose one or more sessions for deletion.

    Args:
        sessions: Sessions available for selection.

    Returns:
        The selected sessions, an empty list when nothing was selected, or
        `_BACK_SENTINEL` when the user navigated back.
    """
    mapping: dict[str, SessionRecord] = {
        session.session_id: session for session in sessions
    }

    choices: list[Choice | Separator] = [
        Choice(
            title=_session_choice_title(session, index=idx),
            value=session.session_id,
        )
        for idx, session in enumerate(sessions, 1)
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


def _print_selected_summary(sessions: list[SessionRecord]) -> None:
    """Prints a compact summary of selected sessions before deletion.

    Args:
        sessions: Sessions chosen by the user, about to be deleted.
    """
    console.print("[bold]Selected for deletion:[/bold]")
    for session in sessions:
        console.print(
            f"- {session.title}\n"
            f"  {session.project_path}\n"
            f"  {_human_size(session.size_bytes)} | "
            f"{session.updated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )


def _session_choice_title(
    session: SessionRecord, index: int | None = None
) -> FormattedChoiceTitle:
    """Builds a formatted multi-line card row for a session choice item.

    Args:
        session: Session to render.
        index: Optional 1-based position shown as a numeric prefix.

    Returns:
        A list of (style class, text) tuples for the checkbox choice row.
    """
    storage_hint = _session_storage_hint(session)
    formatted_dt = session.updated_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    size_str = _human_size(session.size_bytes)
    indent = "     "
    divider = "─" * 56
    prefix = f"{index}. " if index is not None else ""

    return [
        ("class:session-title", f"{prefix}{session.title}\n"),
        ("class:session-label", f"{indent}Project:  "),
        ("class:session-path", f"{session.project_path}\n"),
        ("class:session-label", f"{indent}Storage:  "),
        ("class:session-storage", f"{storage_hint}\n"),
        ("class:session-label", f"{indent}Details:  "),
        ("class:session-meta", f"{size_str}  •  {formatted_dt}\n"),
        ("class:session-divider", f"{indent}{divider}"),
    ]


def _session_storage_hint(session: SessionRecord) -> str:
    """Returns a display-friendly storage path for a session.

    Args:
        session: Session whose storage path should be displayed.

    Returns:
        The storage path with the home directory replaced by "~" when
        applicable, otherwise the full path unchanged.
    """
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
    choices: Sequence[Choice | Separator],
    selected_options: list[Any],
) -> list[Any]:
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
    choices: Sequence[Choice | Separator],
    footer: str,
    validate: ValidateSelectionFn,
) -> list[str] | str | None:  # pragma: no cover
    """Runs custom checkbox prompt with explicit back and quit controls.

    Args:
        message: Prompt text shown above the choice list.
        choices: Selectable choices and separators to render.
        footer: Footer text describing available key bindings.
        validate: Callback invoked with the currently selected values on
            submit; return True to accept, or False/a string error message
            to reject.

    Returns:
        The selected values, `_BACK_SENTINEL` when the user pressed the
        back key, or None when the user quit or interrupted the prompt.
    """
    if not callable(validate):
        raise TypeError("validate must be callable")

    control = InquirerControl(choices)
    control.show_cursor = False

    def get_prompt_tokens() -> list[tuple[str, str]]:
        if control.is_answered:
            return [("class:answer", "done")]
        return [("class:question", f" {message} ")]

    def get_selected_values() -> list[str]:
        selected_values = [choice.value for choice in control.get_selected_values()]
        return [value for value in selected_values if isinstance(value, str)]

    def perform_validation(selected_values: list[str]) -> bool:
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
        style=_TUI_STYLE,
    )

    try:
        return question.run()
    except KeyboardInterrupt:
        return None


def _provider_menu_with_quit() -> str | None:  # pragma: no cover
    """Shows provider selection menu with keyboard shortcuts for quit/select.

    Returns:
        The selected provider key, or None when the user quit the menu.
    """
    choices: list[Choice] = [
        Choice(
            "1. Claude Code\n   Delete archived Claude Code sessions\n",
            value="claude",
        ),
        Choice(
            "2. GitHub Copilot\n   Delete archived Copilot sessions\n",
            value="copilot",
        ),
        Choice(
            "3. Antigravity\n   Delete archived Antigravity sessions\n",
            value="antigravity",
        ),
        Choice(
            "4. OpenCode\n   Delete archived OpenCode sessions",
            value="opencode",
        ),
    ]

    control = InquirerControl(choices, pointer="➤")
    control.show_cursor = False

    def get_prompt_tokens() -> list[tuple[str, str]]:
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
        style=_TUI_STYLE,
    )

    return question.run()


def _human_size(size_bytes: int) -> str:
    """Formats byte count into human-readable units.

    Args:
        size_bytes: Size in bytes.

    Returns:
        A human-readable string such as "1.5 KB".
    """
    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"
