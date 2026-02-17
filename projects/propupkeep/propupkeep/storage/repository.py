from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from propupkeep.core.errors import PersistenceError
from propupkeep.models.issue import Comment, IssueReport, Status


class IssueRepository(ABC):
    @abstractmethod
    def save_issue_report(self, report: IssueReport) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_recent_activity(self, limit: int = 100) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_issues(self) -> list[IssueReport]:
        raise NotImplementedError

    @abstractmethod
    def get_issue(self, issue_id: str) -> IssueReport | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_issue(self, issue: IssueReport) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_comment(self, issue_id: str, comment: Comment) -> IssueReport:
        raise NotImplementedError

    @abstractmethod
    def update_status(self, issue_id: str, new_status: Status) -> IssueReport:
        raise NotImplementedError


class JsonlIssueRepository(IssueRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_issue_report(self, report: IssueReport) -> None:
        self.upsert_issue(report)

    def list_recent_activity(self, limit: int = 100) -> list[dict]:
        issues = self.list_issues()
        return [self._serialize_issue_entry(issue) for issue in issues[:limit]]

    def list_issues(self) -> list[IssueReport]:
        with self._lock:
            issues_by_id = self._load_issues_map_unlocked()
        issues = list(issues_by_id.values())
        issues.sort(key=lambda issue: issue.updated_at, reverse=True)
        return issues

    def get_issue(self, issue_id: str) -> IssueReport | None:
        with self._lock:
            issues_by_id = self._load_issues_map_unlocked()
            return issues_by_id.get(issue_id)

    def upsert_issue(self, issue: IssueReport) -> None:
        with self._lock:
            issues_by_id = self._load_issues_map_unlocked()
            issues_by_id[issue.report_id] = issue
            self._rewrite_all_issues_unlocked(issues_by_id)

    def add_comment(self, issue_id: str, comment: Comment) -> IssueReport:
        with self._lock:
            issues_by_id = self._load_issues_map_unlocked()
            issue = issues_by_id.get(issue_id)
            if issue is None:
                raise PersistenceError(f"Issue {issue_id} not found.")

            updated_issue = issue.model_copy(
                update={
                    "comments": [*issue.comments, comment],
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            issues_by_id[issue_id] = updated_issue
            self._rewrite_all_issues_unlocked(issues_by_id)
            return updated_issue

    def update_status(self, issue_id: str, new_status: Status) -> IssueReport:
        with self._lock:
            issues_by_id = self._load_issues_map_unlocked()
            issue = issues_by_id.get(issue_id)
            if issue is None:
                raise PersistenceError(f"Issue {issue_id} not found.")

            updated_issue = issue.model_copy(
                update={
                    "status": new_status,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            issues_by_id[issue_id] = updated_issue
            self._rewrite_all_issues_unlocked(issues_by_id)
            return updated_issue

    def _load_issues_map_unlocked(self) -> dict[str, IssueReport]:
        issues_by_id: dict[str, IssueReport] = {}
        if not self._file_path.exists():
            return issues_by_id

        try:
            with self._file_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    payload = None
                    if isinstance(entry, dict) and entry.get("entry_type") == "issue_report":
                        payload = entry.get("payload")
                    elif isinstance(entry, dict):
                        payload = entry

                    if not isinstance(payload, dict):
                        continue

                    try:
                        issue = IssueReport.model_validate(payload)
                    except ValidationError:
                        continue
                    issues_by_id[issue.report_id] = issue
        except OSError as exc:
            raise PersistenceError(
                "Unable to read local activity log.",
                detail=str(exc),
            ) from exc
        return issues_by_id

    def _rewrite_all_issues_unlocked(self, issues_by_id: dict[str, IssueReport]) -> None:
        try:
            ordered_issues = sorted(issues_by_id.values(), key=lambda issue: issue.created_at)
            with self._file_path.open("w", encoding="utf-8") as handle:
                for issue in ordered_issues:
                    handle.write(json.dumps(self._serialize_issue_entry(issue), ensure_ascii=True))
                    handle.write("\n")
        except OSError as exc:
            raise PersistenceError(
                "Unable to persist activity locally.",
                detail=str(exc),
            ) from exc

    def _serialize_issue_entry(self, issue: IssueReport) -> dict:
        return {
            "entry_type": "issue_report",
            "created_at": issue.created_at.isoformat(),
            "payload": issue.model_dump(mode="json", exclude_none=False),
        }
