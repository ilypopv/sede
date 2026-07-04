from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from sede import cli
from sede.models import SessionRecord


class _ConfirmTrue:
    def ask(self):
        return True


def test_cli_end_to_end_flow_with_mocks(monkeypatch, tmp_path: Path) -> None:
    session = SessionRecord(
        provider="copilot",
        session_id="sid-1",
        title="Copilot Session",
        project_path=str(tmp_path / "project"),
        size_bytes=2048,
        updated_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        storage_path=tmp_path / ".copilot" / "session-state" / "sid-1",
    )

    deleted = []

    monkeypatch.setattr(cli, "discover_sessions", lambda provider: [session])
    monkeypatch.setattr(cli, "_pick_sessions", lambda sessions: [session])
    monkeypatch.setattr(
        cli.questionary, "confirm", lambda *args, **kwargs: _ConfirmTrue()
    )
    monkeypatch.setattr(cli, "delete_session", lambda s: deleted.append(s.session_id))

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--assistant", "copilot"])

    assert result.exit_code == 0
    assert deleted == ["sid-1"]
    assert "Deleted 1 session(s)." in result.stdout
