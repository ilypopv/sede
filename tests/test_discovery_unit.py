from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sede import discovery
from sede.models import SessionRecord


def test_discover_sessions_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported provider"):
        discovery.discover_sessions("unknown")


def test_decode_claude_project_path_variants() -> None:
    assert discovery._decode_claude_project_path("") == "Unknown project"
    assert discovery._decode_claude_project_path("-Users-me-Repo") == "/Users/me/Repo"
    assert discovery._decode_claude_project_path("Users-me-Repo") == "Users/me/Repo"


def test_parse_iso_dt_variants() -> None:
    dt_z = discovery._parse_iso_dt("2026-07-03T08:56:11.785Z")
    assert dt_z is not None
    assert dt_z.tzinfo is not None

    dt_naive = discovery._parse_iso_dt("2026-07-03T08:56:11")
    assert dt_naive is not None
    assert dt_naive.tzinfo == timezone.utc

    assert discovery._parse_iso_dt("not-a-date") is None
    assert discovery._parse_iso_dt(None) is None


def test_shorten_behaviour() -> None:
    assert discovery._shorten("abc", 5) == "abc"
    assert discovery._shorten("abcdef", 4) == "abc..."
    assert discovery._shorten("line1\n  line2\nline3", 50) == "line1 line2 line3"


def test_read_simple_yaml_parses_basic_pairs(tmp_path: Path) -> None:
    yaml_file = tmp_path / "workspace.yaml"
    yaml_file.write_text(
        "# comment\nid: s1\ncwd: /tmp/project\nname: demo: with colon\n",
        encoding="utf-8",
    )

    parsed = discovery._read_simple_yaml(yaml_file)

    assert parsed["id"] == "s1"
    assert parsed["cwd"] == "/tmp/project"
    assert parsed["name"] == "demo: with colon"


def test_directory_size_bytes_counts_nested_files(tmp_path: Path) -> None:
    root = tmp_path / "session"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "a.txt").write_bytes(b"1234")
    (nested / "b.txt").write_bytes(b"xyz")

    assert discovery._directory_size_bytes(root) == 7


def test_delete_session_removes_claude_file(tmp_path: Path) -> None:
    session_file = tmp_path / "s.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    record = SessionRecord(
        provider="claude",
        session_id="s",
        title="t",
        project_path="/tmp",
        size_bytes=1,
        updated_at=datetime.now(timezone.utc),
        storage_path=session_file,
    )

    discovery.delete_session(record)

    assert not session_file.exists()


def test_delete_session_prunes_empty_claude_parent_dir(tmp_path: Path) -> None:
    session_dir = tmp_path / "-Users-me-project"
    session_dir.mkdir()
    session_file = session_dir / "s.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")

    record = SessionRecord(
        provider="claude",
        session_id="s",
        title="t",
        project_path="/tmp",
        size_bytes=1,
        updated_at=datetime.now(timezone.utc),
        storage_path=session_file,
    )

    discovery.delete_session(record)

    assert not session_file.exists()
    assert not session_dir.exists()


def test_delete_session_keeps_non_empty_claude_parent_dir(tmp_path: Path) -> None:
    session_dir = tmp_path / "-Users-me-project"
    session_dir.mkdir()
    session_file = session_dir / "s.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    (session_dir / "keep.jsonl").write_text("{}\n", encoding="utf-8")

    record = SessionRecord(
        provider="claude",
        session_id="s",
        title="t",
        project_path="/tmp",
        size_bytes=1,
        updated_at=datetime.now(timezone.utc),
        storage_path=session_file,
    )

    discovery.delete_session(record)

    assert not session_file.exists()
    assert session_dir.exists()


def test_delete_session_prune_ignores_rmdir_failure(
    monkeypatch, tmp_path: Path
) -> None:
    session_dir = tmp_path / "-Users-me-project"
    session_dir.mkdir()
    session_file = session_dir / "s.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")

    original_rmdir = Path.rmdir

    def _boom(self: Path) -> None:
        if self == session_dir:
            raise OSError("simulated")
        original_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", _boom)

    record = SessionRecord(
        provider="claude",
        session_id="s",
        title="t",
        project_path="/tmp",
        size_bytes=1,
        updated_at=datetime.now(timezone.utc),
        storage_path=session_file,
    )

    discovery.delete_session(record)

    assert not session_file.exists()
    assert session_dir.exists()


def test_delete_claude_session_file_without_parent_directory(tmp_path: Path) -> None:
    file_without_parent = tmp_path / "orphan.jsonl"
    file_without_parent.write_text("{}\n", encoding="utf-8")

    discovery._delete_claude_session_file(file_without_parent)

    assert not file_without_parent.exists()


def test_delete_session_removes_copilot_directory(tmp_path: Path) -> None:
    session_dir = tmp_path / "copilot-session"
    session_dir.mkdir()
    (session_dir / "events.jsonl").write_text("[]", encoding="utf-8")
    record = SessionRecord(
        provider="copilot",
        session_id="c",
        title="t",
        project_path="/tmp",
        size_bytes=1,
        updated_at=datetime.now(timezone.utc),
        storage_path=session_dir,
    )

    discovery.delete_session(record)

    assert not session_dir.exists()


def test_delete_antigravity_session_cleans_db_and_summaries(tmp_path: Path) -> None:
    import sqlite3

    app_dir = tmp_path / ".gemini" / "antigravity-cli"
    brain_dir = app_dir / "brain"
    conv_dir = app_dir / "conversations"
    session_dir = brain_dir / "session-123"
    session_dir.mkdir(parents=True)
    conv_dir.mkdir(parents=True)

    db_file = conv_dir / "session-123.db"
    db_wal = conv_dir / "session-123.db-wal"
    db_file.write_text("data", encoding="utf-8")
    db_wal.write_text("wal", encoding="utf-8")

    summaries_db = app_dir / "conversation_summaries.db"
    conn = sqlite3.connect(str(summaries_db))
    conn.execute("CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO conversation_summaries VALUES ('session-123', 'My Session')")
    conn.commit()
    conn.close()

    discovery._delete_antigravity_session(session_dir, "session-123")

    assert not session_dir.exists()
    assert not db_file.exists()
    assert not db_wal.exists()

    conn = sqlite3.connect(str(summaries_db))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversation_summaries WHERE conversation_id = 'session-123'")
    assert cursor.fetchone() is None
    conn.close()


def test_read_antigravity_summary_db_parses_row(tmp_path: Path) -> None:
    import sqlite3

    app_dir = tmp_path
    summaries_db = app_dir / "conversation_summaries.db"
    conn = sqlite3.connect(str(summaries_db))
    conn.execute(
        "CREATE TABLE conversation_summaries "
        "(conversation_id TEXT, title TEXT, preview TEXT, workspace_uris TEXT, last_modified_time TEXT)"
    )
    conn.execute(
        "INSERT INTO conversation_summaries VALUES "
        "('s-1', 'Old Title', 'Fixing Bug', '[\"file:///workspace/project\"]', '2026-08-25T16:00:00Z')"
    )
    conn.commit()
    conn.close()

    meta = discovery._read_antigravity_summary_db(app_dir, "s-1")
    assert meta["title"] == "Fixing Bug"
    assert meta["cwd"] == "/workspace/project"
    assert meta["updated_at"] is not None


def test_delete_session_calls_antigravity_deleter(tmp_path: Path) -> None:
    session_dir = tmp_path / "antigravity-session"
    session_dir.mkdir()
    record = SessionRecord(
        provider="antigravity",
        session_id="ag-del",
        title="Delete me",
        project_path="/tmp",
        size_bytes=10,
        updated_at=datetime.now(timezone.utc),
        storage_path=session_dir,
    )
    discovery.delete_session(record)
    assert not session_dir.exists()


def test_read_antigravity_summary_db_variants(tmp_path: Path) -> None:
    import sqlite3

    app_dir = tmp_path
    summaries_db = app_dir / "conversation_summaries.db"
    conn = sqlite3.connect(str(summaries_db))
    conn.execute(
        "CREATE TABLE conversation_summaries "
        "(conversation_id TEXT, title TEXT, preview TEXT, workspace_uris TEXT, last_modified_time TEXT)"
    )
    conn.execute(
        "INSERT INTO conversation_summaries VALUES "
        "('s-raw', 'Title Only', '', '[\"/workspace/raw\"]', '2026-08-25T16:00:00Z'), "
        "('s-bad', 'Bad JSON', '', 'not-json', NULL)"
    )
    conn.commit()
    conn.close()

    meta_raw = discovery._read_antigravity_summary_db(app_dir, "s-raw")
    assert meta_raw["title"] == "Title Only"
    assert meta_raw["cwd"] == "/workspace/raw"

    meta_bad = discovery._read_antigravity_summary_db(app_dir, "s-bad")
    assert meta_bad["title"] == "Bad JSON"
    assert "cwd" not in meta_bad


def test_read_antigravity_summary_db_missing_file(tmp_path: Path) -> None:
    meta = discovery._read_antigravity_summary_db(tmp_path, "missing")
    assert meta == {}


def test_read_antigravity_metadata_handles_missing_file(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty-session"
    empty_dir.mkdir()
    metadata = discovery._read_antigravity_metadata(empty_dir)
    assert metadata == {}


def test_read_antigravity_metadata_handles_corrupted_jsonl(tmp_path: Path) -> None:
    session_dir = tmp_path / "corrupt-session"
    logs_dir = session_dir / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True)
    transcript = logs_dir / "transcript.jsonl"
    transcript.write_text("not json\n\n", encoding="utf-8")

    metadata = discovery._read_antigravity_metadata(session_dir)
    assert "updated_at" in metadata
    assert "prompt" not in metadata
    assert "cwd" not in metadata


def test_read_antigravity_metadata_extracts_tool_calls_cwd(tmp_path: Path) -> None:
    session_dir = tmp_path / "tool-cwd-session"
    logs_dir = session_dir / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True)
    transcript = logs_dir / "transcript.jsonl"
    transcript.write_text(
        '{"type":"PLANNER_RESPONSE","tool_calls":[{"arguments":{"Cwd":"/workspace/my-app"}}]}\n'
        '{"type":"USER_INPUT","content":"Build feature"}\n',
        encoding="utf-8",
    )

    metadata = discovery._read_antigravity_metadata(session_dir)
    assert metadata.get("cwd") == "/workspace/my-app"
    assert metadata.get("prompt") == "Build feature"


def test_discover_antigravity_sessions_handles_empty_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: tmp_path))
    assert discovery._discover_antigravity_sessions() == []


def test_find_profile_targets_matches_direct_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: tmp_path))
    target = tmp_path / ".copilot" / "session-state"
    target.mkdir(parents=True)

    found = discovery._find_profile_targets(".copilot*", "session-state")

    assert found == [target]


def test_find_profile_targets_finds_profile_subdirs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: tmp_path))

    direct = tmp_path / ".copilot-profiles" / "az" / "session-state"
    nested = tmp_path / ".copilot-profiles" / "epam" / ".copilot" / "session-state"
    direct.mkdir(parents=True)
    nested.mkdir(parents=True)

    found = set(discovery._find_profile_targets(".copilot*", "session-state"))

    assert found == {direct, nested}


def test_find_profile_targets_dedupes_and_handles_missing_home(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(discovery.Path, "home", staticmethod(lambda: tmp_path))

    assert discovery._find_profile_targets(".copilot*", "session-state") == []


def test_read_claude_metadata_prefers_ai_title(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "s.jsonl"
    jsonl_path.write_text(
        '{"type":"user","cwd":"/tmp/proj","message":{"content":"raw first prompt"}}\n'
        '{"type":"ai-title","aiTitle":"Generated Title"}\n',
        encoding="utf-8",
    )

    metadata = discovery._read_claude_metadata(jsonl_path)

    assert metadata["title"] == "Generated Title"
    assert metadata["prompt"] == "raw first prompt"
    assert metadata["cwd"] == "/tmp/proj"


def test_read_claude_metadata_keeps_latest_ai_title(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "s.jsonl"
    jsonl_path.write_text(
        '{"type":"ai-title","aiTitle":"First Title"}\n'
        '{"type":"ai-title","aiTitle":"Updated Title"}\n',
        encoding="utf-8",
    )

    metadata = discovery._read_claude_metadata(jsonl_path)

    assert metadata["title"] == "Updated Title"


def test_read_claude_metadata_prefers_custom_title_over_ai_title(
    tmp_path: Path,
) -> None:
    jsonl_path = tmp_path / "s.jsonl"
    jsonl_path.write_text(
        '{"type":"custom-title","customTitle":"my-custom-name"}\n'
        '{"type":"ai-title","aiTitle":"auto-generated-name"}\n',
        encoding="utf-8",
    )

    metadata = discovery._read_claude_metadata(jsonl_path)

    assert metadata["title"] == "my-custom-name"


def test_read_claude_metadata_falls_back_to_ai_title_without_custom_title(
    tmp_path: Path,
) -> None:
    jsonl_path = tmp_path / "s.jsonl"
    jsonl_path.write_text(
        '{"type":"ai-title","aiTitle":"auto-generated-name"}\n',
        encoding="utf-8",
    )

    metadata = discovery._read_claude_metadata(jsonl_path)

    assert metadata["title"] == "auto-generated-name"


def test_read_claude_metadata_skips_blank_and_malformed_lines(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "s.jsonl"
    jsonl_path.write_text(
        "\n"
        "not json\n"
        '{"type":"user","message":"not-a-dict"}\n'
        '{"type":"user","message":{"content":""}}\n'
        '{"type":"user","cwd":"/tmp/proj","message":{"content":"real prompt"}}\n',
        encoding="utf-8",
    )

    metadata = discovery._read_claude_metadata(jsonl_path)

    assert metadata["cwd"] == "/tmp/proj"
    assert metadata["prompt"] == "real prompt"
    assert "title" not in metadata


def test_read_claude_metadata_picks_up_rename_past_first_250_lines(
    tmp_path: Path,
) -> None:
    jsonl_path = tmp_path / "s.jsonl"
    lines = [
        '{"type":"user","cwd":"/tmp/proj","message":{"content":"raw first prompt"}}\n',
        '{"type":"ai-title","aiTitle":"Original Title"}\n',
    ]
    lines.extend('{"type":"mode","mode":"normal"}\n' for _ in range(300))
    lines.append('{"type":"ai-title","aiTitle":"Renamed Title"}\n')
    jsonl_path.write_text("".join(lines), encoding="utf-8")

    metadata = discovery._read_claude_metadata(jsonl_path)

    assert metadata["title"] == "Renamed Title"
    assert metadata["prompt"] == "raw first prompt"
    assert metadata["cwd"] == "/tmp/proj"


def test_read_copilot_first_prompt_returns_first_user_message(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "events.jsonl").write_text(
        '{"type":"session.start","data":{}}\n'
        '{"type":"user.message","data":{"content":"  fix   the bug  "}}\n'
        '{"type":"user.message","data":{"content":"second message"}}\n',
        encoding="utf-8",
    )

    assert discovery._read_copilot_first_prompt(session_dir) == "fix the bug"


def test_read_copilot_first_prompt_handles_missing_or_corrupt_events(
    tmp_path: Path,
) -> None:
    empty_dir = tmp_path / "no-events"
    empty_dir.mkdir()
    assert discovery._read_copilot_first_prompt(empty_dir) is None

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "events.jsonl").write_text("not json\n", encoding="utf-8")
    assert discovery._read_copilot_first_prompt(corrupt_dir) is None


def test_delete_session_rejects_unknown_provider(tmp_path: Path) -> None:
    p = tmp_path / "x"
    p.write_text("x", encoding="utf-8")
    record = SessionRecord(
        provider="other",
        session_id="x",
        title="t",
        project_path="/tmp",
        size_bytes=1,
        updated_at=datetime.now(timezone.utc),
        storage_path=p,
    )

    with pytest.raises(ValueError, match="Unsupported provider"):
        discovery.delete_session(record)
