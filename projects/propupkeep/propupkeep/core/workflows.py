from __future__ import annotations

from propupkeep.ai.formatter import OpenAIIssueFormatter
from propupkeep.core.errors import UserVisibleError
from propupkeep.core.logging_utils import get_logger
from propupkeep.core.sanitize import sanitize_filename, sanitize_user_text
from propupkeep.models.issue import IssueReport, SnapshotRecord
from propupkeep.services.router import IssueRouter
from propupkeep.storage.repository import IssueRepository


class IssueWorkflowService:
    def __init__(
        self,
        formatter: OpenAIIssueFormatter,
        router: IssueRouter,
        repository: IssueRepository,
        max_input_chars: int,
    ) -> None:
        self._formatter = formatter
        self._router = router
        self._repository = repository
        self._max_input_chars = max_input_chars
        self._logger = get_logger(__name__)

    def submit_unit_notes(self, building: str, unit_number: str, raw_observations: str) -> IssueReport:
        sanitized_notes = sanitize_user_text(raw_observations, max_chars=self._max_input_chars)
        if not sanitized_notes:
            raise UserVisibleError("Please enter notes before formatting for the team.")

        formatted_issue = self._formatter.format_issue(
            raw_observations=sanitized_notes,
            building=building,
            unit_number=unit_number,
        )
        recipients = self._router.route_recipients(
            category=formatted_issue.category,
            urgency=formatted_issue.urgency,
        )

        report = IssueReport(
            building=building,
            unit_number=unit_number,
            raw_observations=sanitized_notes,
            issue=formatted_issue.issue,
            urgency=formatted_issue.urgency,
            category=formatted_issue.category,
            recommended_action=formatted_issue.recommended_action,
            recipients=recipients,
        )

        self._repository.save_issue_report(report)
        self._logger.info(
            "Issue report created",
            extra={
                "context": {
                    "report_id": report.report_id,
                    "building": report.building,
                    "unit_number": report.unit_number,
                    "urgency": report.urgency.value,
                    "category": report.category.value,
                }
            },
        )
        return report

    def save_snapshot(self, building: str, unit_number: str, file_name: str, note: str) -> SnapshotRecord:
        snapshot = SnapshotRecord(
            building=building,
            unit_number=unit_number,
            file_name=sanitize_filename(file_name),
            note=sanitize_user_text(note, max_chars=1000),
        )
        self._repository.save_snapshot(snapshot)
        self._logger.info(
            "Snapshot saved",
            extra={
                "context": {
                    "snapshot_id": snapshot.snapshot_id,
                    "building": snapshot.building,
                    "unit_number": snapshot.unit_number,
                }
            },
        )
        return snapshot

    def list_recent_activity(self, limit: int = 100) -> list[dict]:
        return self._repository.list_recent_activity(limit=limit)
