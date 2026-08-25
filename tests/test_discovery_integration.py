from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sede import discovery


def _set_mtime(path: Path, when: datetime) -> None:
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def test_discover_claude_sessions_reads_metadata_and_sorts(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    projects_root = home / ".claude" / "projects"
    session_dir_1 = projects_root / "-Users-me-project-a"
    session_dir_2 = projects_root / "-Users-me-project-b"
    session_dir_1.mkdir(parents=True)
    session_dir_2.mkdir(parents=True)

    session_1 = session_dir_1 / "11111111-1111-1111-1111-111111111111.jsonl"
    session_2 = session_dir_2 / "22222222-2222-2222-2222-222222222222.jsonl"

    session_1.write_text(
        '{"type":"user","cwd":"/Users/me/project-a","message":{"content":"Fix parser"}}\n',
        encoding="utf-8",
    )
    session_2.write_text('{"type":"mode","mode":"normal"}\n', encoding="utf-8")

    _set_mtime(session_1, datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc))
    _set_mtime(session_2, datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc))

    sessions = discovery.discover_sessions("claude")

    assert len(sessions) == 2
    assert sessions[0].session_id == "11111111-1111-1111-1111-111111111111"
    assert sessions[0].title == "Fix parser"
    assert sessions[0].project_path == "/Users/me/project-a"

    assert sessions[1].session_id == "22222222-2222-2222-2222-222222222222"
    assert sessions[1].project_path == "/Users/me/project/b"


def test_discover_copilot_sessions_reads_workspace_and_falls_back_to_mtime(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    root = home / ".copilot" / "session-state"
    s1 = root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    s2 = root / "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    s1.mkdir(parents=True)
    s2.mkdir(parents=True)

    (s1 / "workspace.yaml").write_text(
        "id: a\ncwd: /tmp/app-a\nname: Session A\nupdated_at: 2026-07-04T12:00:00Z\n",
        encoding="utf-8",
    )
    (s1 / "events.jsonl").write_text("event\n", encoding="utf-8")

    (s2 / "events.jsonl").write_text("event\n", encoding="utf-8")
    _set_mtime(s2, datetime(2026, 7, 4, 11, 0, tzinfo=timezone.utc))

    sessions = discovery.discover_sessions("copilot")

    assert len(sessions) == 2
    assert sessions[0].session_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert sessions[0].title == "Session A"
    assert sessions[0].project_path == "/tmp/app-a"

    assert sessions[1].session_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert sessions[1].title == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert sessions[1].project_path == "Unknown project"


def test_discover_antigravity_sessions_reads_transcript_and_sorts(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    brain_cli = home / ".gemini" / "antigravity-cli" / "brain"
    brain_ide = home / ".gemini" / "antigravity" / "brain"
    s1 = brain_cli / "conv-1"
    s2 = brain_ide / "conv-2"
    s3 = brain_cli / "conv-3"

    logs_1 = s1 / ".system_generated" / "logs"
    logs_1.mkdir(parents=True)
    logs_2 = s2 / ".system_generated" / "logs"
    logs_2.mkdir(parents=True)
    s3.mkdir(parents=True)

    (logs_1 / "transcript.jsonl").write_text(
        '{"type":"USER_INPUT","content":"<USER_REQUEST>\\nAdd Antigravity feature\\n</USER_REQUEST>","cwd":"/path/to/project-1"}\n',
        encoding="utf-8",
    )
    (logs_2 / "transcript.jsonl").write_text(
        '{"type":"USER_INPUT","content":"Simple prompt"}\n',
        encoding="utf-8",
    )

    _set_mtime(
        logs_1 / "transcript.jsonl", datetime(2026, 7, 4, 15, 0, tzinfo=timezone.utc)
    )
    _set_mtime(
        logs_2 / "transcript.jsonl", datetime(2026, 7, 4, 14, 0, tzinfo=timezone.utc)
    )
    _set_mtime(s3, datetime(2026, 7, 4, 13, 0, tzinfo=timezone.utc))

    sessions = discovery.discover_sessions("antigravity")

    assert len(sessions) == 3
    assert sessions[0].session_id == "conv-1"
    assert sessions[0].title == "Add Antigravity feature"
    assert sessions[0].project_path == "/path/to/project-1"

    assert sessions[1].session_id == "conv-2"
    assert sessions[1].title == "Simple prompt"
    assert sessions[1].project_path == "Unknown project"

    assert sessions[2].session_id == "conv-3"
    assert sessions[2].title == "conv-3"
    assert sessions[2].project_path == "Unknown project"


def test_discover_antigravity_sessions_reads_summary_db(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    app_dir = home / ".gemini" / "antigravity-cli"
    brain = app_dir / "brain"
    s1 = brain / "c-1"
    s1.mkdir(parents=True)

    project_dir = tmp_path / "workspace" / "sede"
    project_uri = f"file://{project_dir.as_posix()}"

    db_path = app_dir / "conversation_summaries.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE conversation_summaries "
        "(conversation_id TEXT PRIMARY KEY, title TEXT, preview TEXT, workspace_uris TEXT, last_modified_time TEXT)"
    )
    conn.execute(
        "INSERT INTO conversation_summaries VALUES "
        f"('c-1', 'Generic Title', 'Fixing Secondary Screen Header', '[\"{project_uri}\"]', '2026-08-25T16:00:00Z')"
    )
    conn.commit()
    conn.close()

    sessions = discovery.discover_sessions("antigravity")

    assert len(sessions) == 1
    assert sessions[0].session_id == "c-1"
    assert sessions[0].title == "Fixing Secondary Screen Header"
    assert sessions[0].project_path == project_dir.as_posix()
