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
