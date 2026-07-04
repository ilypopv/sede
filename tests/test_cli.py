from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from sede import cli
from sede.models import SessionRecord


def _sample_session(provider: str = "claude") -> SessionRecord:
    storage = (
        Path.home() / ".claude" / "projects" / "p" / "sid.jsonl"
        if provider == "claude"
        else Path.home() / ".copilot" / "session-state" / "sid"
    )
    return SessionRecord(
        provider=provider,
        session_id="sid",
        title="Sample Session",
        project_path="/tmp/project",
        size_bytes=1536,
        updated_at=datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc),
        storage_path=storage,
    )


def test_session_storage_hint_uses_parent_for_claude() -> None:
    record = _sample_session("claude")
    hint = cli._session_storage_hint(record)
    assert hint.endswith("/.claude/projects/p")


def test_session_storage_hint_uses_session_dir_for_copilot() -> None:
    record = _sample_session("copilot")
    hint = cli._session_storage_hint(record)
    assert hint.endswith("/.copilot/session-state/sid")


def test_session_choice_title_contains_storage_line() -> None:
    record = _sample_session("copilot")
    tokens = cli._session_choice_title(record)
    joined = "".join(t[1] for t in tokens)

    assert "Sample Session" in joined
    assert "/tmp/project" in joined
    assert ".copilot/session-state/sid" in joined
    assert "1.5 KB" in joined


def test_run_provider_flow_returns_true_when_no_sessions(monkeypatch) -> None:
    monkeypatch.setattr(cli, "discover_sessions", lambda provider: [])

    result = cli._run_provider_flow("claude", yes=True)

    assert result is True


def test_run_provider_flow_returns_true_when_back(monkeypatch) -> None:
    monkeypatch.setattr(cli, "discover_sessions", lambda provider: [_sample_session()])
    monkeypatch.setattr(cli, "_pick_sessions", lambda sessions: cli._BACK_SENTINEL)

    result = cli._run_provider_flow("claude", yes=True)

    assert result is True


def test_run_provider_flow_deletes_selected_when_yes(monkeypatch) -> None:
    deleted = []
    session = _sample_session("claude")

    monkeypatch.setattr(cli, "discover_sessions", lambda provider: [session])
    monkeypatch.setattr(cli, "_pick_sessions", lambda sessions: [session])
    monkeypatch.setattr(cli, "delete_session", lambda s: deleted.append(s.session_id))

    result = cli._run_provider_flow("claude", yes=True)

    assert result is False
    assert deleted == ["sid"]


def test_run_provider_flow_cancelled_by_confirm(monkeypatch) -> None:
    session = _sample_session("claude")
    deleted = []

    class _ConfirmFalse:
        def ask(self):
            return False

    monkeypatch.setattr(cli, "discover_sessions", lambda provider: [session])
    monkeypatch.setattr(cli, "_pick_sessions", lambda sessions: [session])
    monkeypatch.setattr(
        cli.questionary, "confirm", lambda *args, **kwargs: _ConfirmFalse()
    )
    monkeypatch.setattr(cli, "delete_session", lambda s: deleted.append(s.session_id))

    result = cli._run_provider_flow("claude", yes=False)

    assert result is False
    assert deleted == []


def test_main_invokes_provider_flow(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(cli, "_pick_provider", lambda value: "copilot")
    monkeypatch.setattr(
        cli,
        "_run_provider_flow",
        lambda provider, yes: calls.append((provider, yes)) or False,
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0
    assert calls == [("copilot", False)]


def test_main_with_invalid_assistant_exits_non_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--assistant", "bad-provider"])

    assert result.exit_code == 1


def test_pick_provider_accepts_cli_values() -> None:
    assert cli._pick_provider("claude") == "claude"
    assert cli._pick_provider("  copilot ") == "copilot"


def test_pick_provider_rejects_unknown_cli_value() -> None:
    assert cli._pick_provider("other") is None


def test_pick_sessions_returns_back(monkeypatch) -> None:
    session = _sample_session("claude")
    monkeypatch.setattr(
        cli, "_checkbox_with_back", lambda *args, **kwargs: cli._BACK_SENTINEL
    )

    selected = cli._pick_sessions([session])

    assert selected == cli._BACK_SENTINEL


def test_pick_sessions_maps_selected_ids(monkeypatch) -> None:
    s1 = _sample_session("claude")
    s2 = SessionRecord(
        provider="claude",
        session_id="sid-2",
        title="Second",
        project_path="/tmp/p2",
        size_bytes=500,
        updated_at=datetime(2026, 7, 4, 11, 0, tzinfo=timezone.utc),
        storage_path=Path.home() / ".claude" / "projects" / "p2" / "sid-2.jsonl",
    )
    monkeypatch.setattr(
        cli, "_checkbox_with_back", lambda *args, **kwargs: ["sid", "sid-2"]
    )

    selected = cli._pick_sessions([s1, s2])

    assert [x.session_id for x in selected] == ["sid", "sid-2"]


def test_pick_sessions_returns_empty_when_no_selection(monkeypatch) -> None:
    session = _sample_session("claude")
    monkeypatch.setattr(cli, "_checkbox_with_back", lambda *args, **kwargs: None)

    selected = cli._pick_sessions([session])

    assert selected == []


def test_human_size_formats_units() -> None:
    assert cli._human_size(0) == "0 B"
    assert cli._human_size(1024) == "1.0 KB"
    assert cli._human_size(1024 * 1024) == "1.0 MB"


def test_run_provider_flow_collects_failures(monkeypatch) -> None:
    session = _sample_session("copilot")

    monkeypatch.setattr(cli, "discover_sessions", lambda provider: [session])
    monkeypatch.setattr(cli, "_pick_sessions", lambda sessions: [session])

    def _boom(_session):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "delete_session", _boom)

    result = cli._run_provider_flow("copilot", yes=True)

    assert result is False


def test_print_home_screen_renders_without_crash() -> None:
    cli._print_home_screen()
