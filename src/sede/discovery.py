from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SessionRecord

_PROFILE_SCAN_DEPTH = 3


def _find_profile_targets(marker_glob: str, relative_target: str) -> list[Path]:
    """Finds every `relative_target` dir reachable from home through dirs
    matching `marker_glob`, including provider "profile" setups that behave
    like an alternate home directory (e.g. a ``HOME``-overriding launcher
    script), such as ``~/.copilot-profiles/<name>/session-state`` or
    ``~/.copilot-profiles/<name>/.copilot/session-state``.

    Args:
        marker_glob: Glob for provider-owned dot-directories directly under
            home, e.g. ".copilot*", ".claude*", or ".gemini*". Using a glob
            instead of an exact name catches sibling directories such as
            ``.copilot-profiles`` alongside ``.copilot``.
        relative_target: Path, relative to a marker or profile directory,
            where session data is expected to live, e.g. "session-state",
            "projects", or "antigravity-cli/brain".

    Returns:
        Deduplicated list of existing target directories.
    """

    found: list[Path] = []
    seen_targets: set[Path] = set()
    seen_markers: set[Path] = set()

    def add(directory: Path) -> None:
        target = directory / relative_target
        if target.is_dir() and target not in seen_targets:
            seen_targets.add(target)
            found.append(target)

    def scan(base: Path, depth: int) -> None:
        if depth <= 0:
            return
        try:
            marker_dirs = sorted(base.glob(marker_glob))
        except OSError:
            return

        for marker_dir in marker_dirs:
            if not marker_dir.is_dir():
                continue
            try:
                resolved = marker_dir.resolve()
            except OSError:
                resolved = marker_dir
            if resolved in seen_markers:
                continue
            seen_markers.add(resolved)

            add(marker_dir)

            try:
                profile_dirs = [
                    entry
                    for entry in sorted(marker_dir.iterdir())
                    if entry.is_dir() and not entry.name.startswith(".")
                ]
            except OSError:
                profile_dirs = []

            for profile_dir in profile_dirs:
                add(profile_dir)
                scan(profile_dir, depth - 1)

    scan(Path.home(), _PROFILE_SCAN_DEPTH)
    return found


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
    """Deletes an Antigravity session from brain, conversations db, and summaries.

    Args:
        session_path: Path to the session's directory under a brain root.
        session_id: Conversation identifier used to key the SQLite rows.
    """

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
    """Discovers Claude sessions from every ~/.claude*/projects directory.

    Covers alternate home overrides such as ~/.claude-work/projects.

    Returns:
        Discovered Claude sessions sorted by last update time, newest first.
    """

    sessions: list[SessionRecord] = []
    seen_paths: set[Path] = set()

    for root in _find_profile_targets(".claude*", "projects"):
        for jsonl_path in sorted(root.glob("*/*.jsonl")):
            if not jsonl_path.is_file():
                continue
            try:
                resolved = jsonl_path.resolve()
            except OSError:
                resolved = jsonl_path
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

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
    """Discovers Copilot sessions from every ~/.copilot*/session-state directory.

    Covers per-profile setups such as ~/.copilot-profiles/<name>/session-state
    or ~/.copilot-profiles/<name>/.copilot/session-state.

    Returns:
        Discovered Copilot sessions sorted by last update time, newest first.
    """

    sessions: list[SessionRecord] = []
    seen_ids: set[str] = set()

    for root in _find_profile_targets(".copilot*", "session-state"):
        for session_dir in sorted(root.iterdir()):
            if not session_dir.is_dir() or session_dir.name in seen_ids:
                continue

            workspace_file = session_dir / "workspace.yaml"
            metadata = (
                _read_simple_yaml(workspace_file) if workspace_file.exists() else {}
            )

            updated_at = _parse_iso_dt(metadata.get("updated_at"))
            if updated_at is None:
                updated_at = datetime.fromtimestamp(
                    session_dir.stat().st_mtime, tz=timezone.utc
                )

            title = (
                metadata.get("name")
                or _read_copilot_first_prompt(session_dir)
                or session_dir.name
            )
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
            seen_ids.add(session_dir.name)

    return sorted(sessions, key=lambda s: s.updated_at, reverse=True)


def _discover_antigravity_sessions() -> list[SessionRecord]:
    """Discovers Antigravity sessions from every ~/.gemini*/antigravity(-cli)/brain directory.

    Covers alternate home overrides such as ~/.gemini-work/antigravity/brain.

    Returns:
        Discovered Antigravity sessions sorted by last update time, newest first.
    """

    roots: list[Path] = []
    for relative in ("antigravity-cli/brain", "antigravity/brain"):
        roots.extend(_find_profile_targets(".gemini*", relative))

    sessions: list[SessionRecord] = []
    seen_ids = set()

    for root in roots:
        app_dir = root.parent

        for session_dir in sorted(root.iterdir()):
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
    """Reads conversation summary metadata from Antigravity SQLite database.

    Args:
        app_dir: Antigravity application directory containing
            conversation_summaries.db (the parent of the brain root).
        conversation_id: Conversation identifier to look up.

    Returns:
        A dictionary that may contain keys like "title", "cwd", and
        "updated_at". Empty when the database or row is missing.
    """

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
    """Extracts metadata from an Antigravity conversation directory.

    Args:
        session_dir: Path to the conversation directory under a brain root.

    Returns:
        A dictionary that may contain keys like "cwd", "prompt", and
        "updated_at". Empty when no transcript log file is found.
    """

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
        A dictionary that may contain keys like "cwd", "prompt", and "title".
        "title" prefers a user-set "custom-title" event (written by Claude
        Code's `/rename` command) over an auto-generated "ai-title" event,
        since Claude Code keeps re-emitting a fresh "ai-title" on later turns
        even after the session has been manually renamed, but its own UI
        still shows the custom title. Both event kinds keep their latest
        occurrence. Unlike "cwd"/"prompt", this title scan is not capped to
        the first 250 lines, since a rename can be appended well past that
        point in a long-running session; a cheap substring check keeps this
        from re-parsing every line of large files as JSON.
    """

    result: dict[str, str] = {}
    ai_title: str | None = None
    custom_title: str | None = None

    with jsonl_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            if idx <= 250 and ("cwd" not in result or "prompt" not in result):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = None

                if payload is not None:
                    cwd = payload.get("cwd")
                    if isinstance(cwd, str) and "cwd" not in result:
                        result["cwd"] = cwd

                    if payload.get("type") == "user":
                        message = payload.get("message", {})
                        if isinstance(message, dict):
                            content = message.get("content")
                            if (
                                isinstance(content, str)
                                and content
                                and "prompt" not in result
                            ):
                                result["prompt"] = " ".join(content.split())

            if "ai-title" in line or "custom-title" in line:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = payload.get("type")
                if event_type == "ai-title":
                    candidate = payload.get("aiTitle")
                    if isinstance(candidate, str) and candidate.strip():
                        ai_title = " ".join(candidate.split())
                elif event_type == "custom-title":
                    candidate = payload.get("customTitle")
                    if isinstance(candidate, str) and candidate.strip():
                        custom_title = " ".join(candidate.split())

    title = custom_title or ai_title
    if title:
        result["title"] = title

    return result


def _decode_claude_project_path(encoded: str) -> str:
    """Decodes Claude's dash-encoded project directory name to a path string.

    Args:
        encoded: Dash-encoded directory name, e.g. "-Users-me-Repo".

    Returns:
        The decoded filesystem path, or "Unknown project" when empty.
    """

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


def _read_copilot_first_prompt(session_dir: Path) -> str | None:
    """Reads the first user message from a Copilot session's events log.

    Used as a title fallback when a session has no "name" set in its
    workspace.yaml (either not yet auto-titled, or never renamed).

    Args:
        session_dir: Path to the Copilot session-state session directory.

    Returns:
        The first user message text, or None if unavailable.
    """

    events_path = session_dir / "events.jsonl"
    if not events_path.is_file():
        return None

    try:
        with events_path.open("r", encoding="utf-8") as f:
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

                if payload.get("type") != "user.message":
                    continue

                data = payload.get("data")
                if isinstance(data, dict):
                    content = data.get("content")
                    if isinstance(content, str) and content.strip():
                        return " ".join(content.split())
    except OSError:
        return None

    return None


def _directory_size_bytes(path: Path) -> int:
    """Computes total size in bytes for all files under a directory.

    Args:
        path: Directory to scan recursively.

    Returns:
        Sum of file sizes, in bytes, of every file found under `path`.
    """

    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def _parse_iso_dt(value: str | None) -> datetime | None:
    """Parses ISO datetime text and ensures timezone-aware UTC values.

    Args:
        value: ISO-8601 datetime string, or None. A trailing "Z" is treated
            as UTC.

    Returns:
        A timezone-aware datetime, or None when `value` is empty or invalid.
    """

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
    """Shortens text with ellipsis when it exceeds the provided limit.

    Args:
        text: Text to shorten. Internal whitespace runs are collapsed.
        limit: Maximum length of the returned string, including the
            ellipsis when truncation occurs.

    Returns:
        The cleaned text unchanged if it fits within `limit`, otherwise a
        truncated copy ending in "...".
    """

    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "..."
