from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SessionRecord


def discover_sessions(provider: str) -> list[SessionRecord]:
    """Discovers stored sessions for the requested assistant provider.

    Args:
        provider: Assistant provider key, e.g. "claude" or "copilot".

    Returns:
        A list of discovered sessions sorted by last update time, newest first.

    Raises:
        ValueError: If the provider is not supported.
    """

    if provider == "claude":
        return _discover_claude_sessions()
    if provider == "copilot":
        return _discover_copilot_sessions()
    if provider == "antigravity":
        return _discover_antigravity_sessions()
    raise ValueError(f"Unsupported provider: {provider}")


def delete_session(session: SessionRecord) -> None:
    """Deletes the session from disk.

    Args:
        session: Session descriptor containing provider and storage path.

    Raises:
        ValueError: If the provider is not supported.
        OSError: If filesystem deletion fails.
    """

    if session.provider == "claude":
        _delete_claude_session_file(session.storage_path)
        return
    if session.provider == "copilot":
        shutil.rmtree(session.storage_path)
        return
    if session.provider == "antigravity":
        _delete_antigravity_session(session.storage_path, session.session_id)
        return
    raise ValueError(f"Unsupported provider: {session.provider}")


def _delete_claude_session_file(session_file: Path) -> None:
    """Deletes a Claude session file and prunes empty parent directory.

    Args:
        session_file: Path to the Claude session jsonl file.
    """

    session_file.unlink(missing_ok=False)

    parent_dir = session_file.parent
    try:
        if parent_dir.is_dir() and not any(parent_dir.iterdir()):
            parent_dir.rmdir()
    except OSError:
        # Best-effort cleanup only; deletion of the selected session file has
        # already succeeded.
        return


def _delete_antigravity_session(session_path: Path, session_id: str) -> None:
    """Deletes an Antigravity session from brain, conversations db, and summaries."""

    if session_path.is_dir():
        shutil.rmtree(session_path)

    # Clean up associated SQLite database and WAL/SHM files
    app_dir = session_path.parent.parent
    conv_dir = app_dir / "conversations"
    if conv_dir.is_dir():
        for db_file in conv_dir.glob(f"{session_id}.db*"):
            try:
                db_file.unlink()
            except OSError:
                pass

    # Prune row from conversation_summaries.db
    db_path = app_dir / "conversation_summaries.db"
    if db_path.is_file():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                (session_id,),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass


def _discover_claude_sessions() -> list[SessionRecord]:
    """Discovers Claude sessions from ~/.claude/projects."""

    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return []

    sessions: list[SessionRecord] = []
    for jsonl_path in root.glob("*/*.jsonl"):
        if not jsonl_path.is_file():
            continue

        metadata = _read_claude_metadata(jsonl_path)
        stat = jsonl_path.stat()
        project_path = metadata.get("cwd") or _decode_claude_project_path(
            jsonl_path.parent.name
        )
        title = metadata.get("title") or metadata.get("prompt") or jsonl_path.stem

        sessions.append(
            SessionRecord(
                provider="claude",
                session_id=jsonl_path.stem,
                title=_shorten(title, 70),
                project_path=project_path,
                size_bytes=stat.st_size,
                updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                storage_path=jsonl_path,
            )
        )

    return sorted(sessions, key=lambda s: s.updated_at, reverse=True)


def _discover_copilot_sessions() -> list[SessionRecord]:
    """Discovers Copilot sessions from ~/.copilot/session-state."""

    root = Path.home() / ".copilot" / "session-state"
    if not root.exists():
        return []

    sessions: list[SessionRecord] = []
    for session_dir in root.iterdir():
        if not session_dir.is_dir():
            continue

        workspace_file = session_dir / "workspace.yaml"
        metadata = _read_simple_yaml(workspace_file) if workspace_file.exists() else {}

        updated_at = _parse_iso_dt(metadata.get("updated_at"))
        if updated_at is None:
            updated_at = datetime.fromtimestamp(
                session_dir.stat().st_mtime, tz=timezone.utc
            )

        title = metadata.get("name") or session_dir.name
        project_path = metadata.get("cwd") or "Unknown project"

        sessions.append(
            SessionRecord(
                provider="copilot",
                session_id=session_dir.name,
                title=_shorten(title, 70),
                project_path=project_path,
                size_bytes=_directory_size_bytes(session_dir),
                updated_at=updated_at,
                storage_path=session_dir,
            )
        )

    return sorted(sessions, key=lambda s: s.updated_at, reverse=True)


def _discover_antigravity_sessions() -> list[SessionRecord]:
    """Discovers Antigravity sessions from ~/.gemini/antigravity-cli/brain and ~/.gemini/antigravity/brain."""

    roots = [
        Path.home() / ".gemini" / "antigravity-cli" / "brain",
        Path.home() / ".gemini" / "antigravity" / "brain",
    ]

    sessions: list[SessionRecord] = []
    seen_ids = set()

    for root in roots:
        if not root.exists():
            continue

        app_dir = root.parent

        for session_dir in root.iterdir():
            if not session_dir.is_dir() or session_dir.name.startswith("."):
                continue
            if session_dir.name in seen_ids:
                continue

            summary_meta = _read_antigravity_summary_db(app_dir, session_dir.name)
            transcript_meta = _read_antigravity_metadata(session_dir)
            stat = session_dir.stat()

            title = (
                summary_meta.get("title")
                or transcript_meta.get("prompt")
                or session_dir.name
            )
            project_path = (
                summary_meta.get("cwd")
                or transcript_meta.get("cwd")
                or "Unknown project"
            )
            updated_at = summary_meta.get("updated_at") or transcript_meta.get(
                "updated_at"
            )
            if updated_at is None:
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            sessions.append(
                SessionRecord(
                    provider="antigravity",
                    session_id=session_dir.name,
                    title=_shorten(title, 70),
                    project_path=project_path,
                    size_bytes=_directory_size_bytes(session_dir),
                    updated_at=updated_at,
                    storage_path=session_dir,
                )
            )
            seen_ids.add(session_dir.name)

    return sorted(sessions, key=lambda s: s.updated_at, reverse=True)


def _read_antigravity_summary_db(app_dir: Path, conversation_id: str) -> dict[str, Any]:
    """Reads conversation summary metadata from Antigravity SQLite database."""

    db_path = app_dir / "conversation_summaries.db"
    if not db_path.is_file():
        return {}

    result: dict[str, Any] = {}
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, preview, workspace_uris, last_modified_time "
            "FROM conversation_summaries WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            title_val, preview_val, uris_val, last_mod = row
            chosen_title = preview_val or title_val
            if chosen_title:
                result["title"] = chosen_title.strip()

            if uris_val:
                try:
                    parsed_uris = json.loads(uris_val)
                    if isinstance(parsed_uris, list) and parsed_uris:
                        first_uri = parsed_uris[0]
                        if isinstance(first_uri, str):
                            if first_uri.startswith("file://"):
                                result["cwd"] = first_uri[len("file://") :]
                            else:
                                result["cwd"] = first_uri
                except json.JSONDecodeError:
                    pass

            if last_mod:
                parsed_dt = _parse_iso_dt(str(last_mod))
                if parsed_dt:
                    result["updated_at"] = parsed_dt
    except sqlite3.Error:
        return {}

    return result


def _read_antigravity_metadata(session_dir: Path) -> dict[str, Any]:
    """Extracts metadata from an Antigravity conversation directory."""

    result: dict[str, Any] = {}

    log_files = [
        session_dir / ".system_generated" / "logs" / "transcript.jsonl",
        session_dir / ".system_generated" / "logs" / "transcript_full.jsonl",
        session_dir / "transcript.jsonl",
    ]

    log_path = None
    for candidate in log_files:
        if candidate.is_file():
            log_path = candidate
            break

    if log_path is None:
        return result

    stat = log_path.stat()
    result["updated_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    with log_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx > 250:
                break
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "cwd" not in result:
                if isinstance(payload.get("cwd"), str):
                    result["cwd"] = payload["cwd"]
                elif "tool_calls" in payload and isinstance(
                    payload["tool_calls"], list
                ):
                    for tc in payload["tool_calls"]:
                        if isinstance(tc, dict):
                            args = tc.get("arguments") or tc.get("args") or {}
                            if (
                                isinstance(args, dict)
                                and "Cwd" in args
                                and isinstance(args["Cwd"], str)
                            ):
                                result["cwd"] = args["Cwd"]
                                break

            if "prompt" not in result and payload.get("type") == "USER_INPUT":
                content = payload.get("content")
                if isinstance(content, str) and content:
                    if "<USER_REQUEST>" in content and "</USER_REQUEST>" in content:
                        content = content.split("<USER_REQUEST>", 1)[1].split(
                            "</USER_REQUEST>", 1
                        )[0]
                    result["prompt"] = " ".join(content.split())

            if "cwd" in result and "prompt" in result:
                break

    return result


def _read_claude_metadata(jsonl_path: Path) -> dict[str, str]:
    """Extracts useful metadata from a Claude jsonl session file.

    Args:
        jsonl_path: Path to the Claude session jsonl file.

    Returns:
        A dictionary that may contain keys like "cwd" and "prompt".
    """

    result: dict[str, str] = {}

    with jsonl_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx > 250:
                break
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            cwd = payload.get("cwd")
            if isinstance(cwd, str) and "cwd" not in result:
                result["cwd"] = cwd

            if payload.get("type") == "user":
                message = payload.get("message", {})
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content and "prompt" not in result:
                        result["prompt"] = " ".join(content.split())

            if "cwd" in result and "prompt" in result:
                break

    return result


def _decode_claude_project_path(encoded: str) -> str:
    """Decodes Claude's dash-encoded project directory name to a path string."""

    if not encoded:
        return "Unknown project"
    if encoded.startswith("-"):
        return "/" + encoded[1:].replace("-", "/")
    return encoded.replace("-", "/")


def _read_simple_yaml(path: Path) -> dict[str, str]:
    """Reads a simple key:value YAML-like file into a dictionary.

    This parser intentionally handles only flat `key: value` rows used by
    Copilot workspace metadata.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed key/value pairs.
    """

    values: dict[str, str] = {}

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()

    return values


def _directory_size_bytes(path: Path) -> int:
    """Computes total size in bytes for all files under a directory."""

    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def _parse_iso_dt(value: str | None) -> datetime | None:
    """Parses ISO datetime text and ensures timezone-aware UTC values."""

    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _shorten(text: str, limit: int) -> str:
    """Shortens text with ellipsis when it exceeds the provided limit."""

    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "..."
