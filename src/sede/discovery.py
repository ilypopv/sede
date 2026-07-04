from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .models import SessionRecord


def discover_sessions(provider: str) -> List[SessionRecord]:
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


def _discover_claude_sessions() -> List[SessionRecord]:
    """Discovers Claude sessions from ~/.claude/projects."""

    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return []

    sessions: List[SessionRecord] = []
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


def _discover_copilot_sessions() -> List[SessionRecord]:
    """Discovers Copilot sessions from ~/.copilot/session-state."""

    root = Path.home() / ".copilot" / "session-state"
    if not root.exists():
        return []

    sessions: List[SessionRecord] = []
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


def _read_claude_metadata(jsonl_path: Path) -> Dict[str, str]:
    """Extracts useful metadata from a Claude jsonl session file.

    Args:
        jsonl_path: Path to the Claude session jsonl file.

    Returns:
        A dictionary that may contain keys like "cwd" and "prompt".
    """

    result: Dict[str, str] = {}

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
                        result["prompt"] = content

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


def _read_simple_yaml(path: Path) -> Dict[str, str]:
    """Reads a simple key:value YAML-like file into a dictionary.

    This parser intentionally handles only flat `key: value` rows used by
    Copilot workspace metadata.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed key/value pairs.
    """

    values: Dict[str, str] = {}

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


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
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

    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."
