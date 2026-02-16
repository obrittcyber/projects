from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from propupkeep.core.errors import PersistenceError
from propupkeep.models.issue import IssueReport, SnapshotRecord


class IssueRepository(ABC):
    @abstractmethod
    def save_issue_report(self, report: IssueReport) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_snapshot(self, snapshot: SnapshotRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_recent_activity(self, limit: int = 100) -> list[dict]:
        raise NotImplementedError


class JsonlIssueRepository(IssueRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_issue_report(self, report: IssueReport) -> None:
        entry = {
            "entry_type": "issue_report",
            "created_at": report.created_at.isoformat(),
            "payload": report.model_dump(mode="json"),
        }
        self._append_entry(entry)

    def save_snapshot(self, snapshot: SnapshotRecord) -> None:
        entry = {
            "entry_type": "snapshot",
            "created_at": snapshot.created_at.isoformat(),
            "payload": snapshot.model_dump(mode="json"),
        }
        self._append_entry(entry)

    def list_recent_activity(self, limit: int = 100) -> list[dict]:
        if not self._file_path.exists():
            return []

        entries: list[dict] = []
        try:
            with self._file_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            raise PersistenceError(
                "Unable to read local activity log.",
                detail=str(exc),
            ) from exc

        return list(reversed(entries[-limit:]))

    def _append_entry(self, entry: dict) -> None:
        try:
            with self._lock:
                with self._file_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=True))
                    handle.write("\n")
        except OSError as exc:
            raise PersistenceError(
                "Unable to persist activity locally.",
                detail=str(exc),
            ) from exc
