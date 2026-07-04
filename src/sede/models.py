from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SessionRecord:
    """Represents one discoverable assistant session in storage."""

    provider: str
    session_id: str
    title: str
    project_path: str
    size_bytes: int
    updated_at: datetime
    storage_path: Path
