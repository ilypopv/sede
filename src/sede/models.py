"""Data models for sede.

Defines :class:`SessionRecord`, the core immutable value object representing a
discovered assistant session across all supported providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SessionRecord:
    """Represents one discoverable assistant session in storage.

    Attributes:
        provider: Assistant provider key (e.g., ``"claude"``, ``"copilot"``,
            ``"antigravity"``).
        session_id: Unique identifier for the session within its provider.
        title: Human-readable session title.
        project_path: Filesystem path of the associated project.
        size_bytes: Total session size in bytes.
        updated_at: Last update timestamp (timezone-aware, UTC).
        storage_path: Filesystem path where the session is stored.
    """

    provider: str
    session_id: str
    title: str
    project_path: str
    size_bytes: int
    updated_at: datetime
    storage_path: Path
