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


def test_discover_claude_sessions_uses_ai_title_and_multiple_profile_roots(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    default_root = home / ".claude" / "projects" / "-Users-me-project-a"
    work_root = home / ".claude-work" / "projects" / "-Users-me-project-b"
    default_root.mkdir(parents=True)
    work_root.mkdir(parents=True)

    titled = default_root / "11111111-1111-1111-1111-111111111111.jsonl"
    untitled = work_root / "22222222-2222-2222-2222-222222222222.jsonl"

    titled.write_text(
        '{"type":"user","cwd":"/Users/me/project-a","message":{"content":"raw prompt"}}\n'
        '{"type":"ai-title","aiTitle":"Fix the parser bug"}\n',
        encoding="utf-8",
    )
    untitled.write_text(
        '{"type":"user","cwd":"/Users/me/project-b","message":{"content":"No title yet"}}\n',
        encoding="utf-8",
    )

    _set_mtime(titled, datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc))
    _set_mtime(untitled, datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc))

    sessions = discovery.discover_sessions("claude")

    assert len(sessions) == 2
    assert sessions[0].title == "Fix the parser bug"
    assert sessions[1].title == "No title yet"


def test_discover_copilot_sessions_finds_profile_dirs_and_falls_back_to_first_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    profile_root = home / ".copilot-profiles" / "az" / "session-state"
    nested_root = home / ".copilot-profiles" / "epam" / ".copilot" / "session-state"

    named_session = profile_root / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    unnamed_session = nested_root / "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    named_session.mkdir(parents=True)
    unnamed_session.mkdir(parents=True)

    (named_session / "workspace.yaml").write_text(
        "id: a\ncwd: /tmp/app-a\nname: Session A\nupdated_at: 2026-07-04T12:00:00Z\n",
        encoding="utf-8",
    )
    (unnamed_session / "workspace.yaml").write_text(
        "id: b\ncwd: /tmp/app-b\nupdated_at: 2026-07-04T11:00:00Z\n",
        encoding="utf-8",
    )
    (unnamed_session / "events.jsonl").write_text(
        '{"type":"user.message","data":{"content":"Investigate profile bug"}}\n',
        encoding="utf-8",
    )

    sessions = discovery.discover_sessions("copilot")

    assert len(sessions) == 2
    assert sessions[0].title == "Session A"
    assert sessions[0].project_path == "/tmp/app-a"
    assert sessions[1].title == "Investigate profile bug"
    assert sessions[1].project_path == "/tmp/app-b"


def test_discover_antigravity_sessions_finds_alternate_home_root(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: home))

    brain = home / ".gemini-work" / "antigravity" / "brain"
    session_dir = brain / "conv-alt"
    logs_dir = session_dir / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "transcript.jsonl").write_text(
        '{"type":"USER_INPUT","content":"Alternate home prompt","cwd":"/path/alt"}\n',
        encoding="utf-8",
    )

    sessions = discovery.discover_sessions("antigravity")

    assert len(sessions) == 1
    assert sessions[0].session_id == "conv-alt"
    assert sessions[0].title == "Alternate home prompt"
    assert sessions[0].project_path == "/path/alt"


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
