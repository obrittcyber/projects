from __future__ import annotations

from propupkeep.ai.formatter import OpenAIIssueFormatter
from propupkeep.core.errors import UserVisibleError
from propupkeep.core.logging_utils import get_logger
from propupkeep.core.sanitize import sanitize_filename, sanitize_user_text
from propupkeep.models.issue import IssueMetadata, IssueReport, IssueSource
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

    def submit_issue(
        self,
        source: IssueSource,
        note_text: str,
        metadata: IssueMetadata,
        image_bytes: bytes | None = None,
        image_filename: str | None = None,
    ) -> IssueReport:
        sanitized_note_text = sanitize_user_text(note_text, max_chars=self._max_input_chars)
        sanitized_filename = sanitize_filename(image_filename) if image_filename else None
        sanitized_metadata = self._sanitize_metadata(metadata)

        has_note = bool(sanitized_note_text)
        has_image = bool(image_bytes)
        if not has_note and not has_image:
            raise UserVisibleError("Please add a note or a photo before submitting.")
        if source == IssueSource.NOTE and not has_note:
            raise UserVisibleError("Please enter notes before formatting for the team.")

        raw_observations = self._build_observation_context(
            source=source,
            metadata=sanitized_metadata,
            note_text=sanitized_note_text,
            image_filename=sanitized_filename,
            image_bytes=image_bytes,
        )

        formatted_issue = self._formatter.format_issue(
            source=source,
            metadata=sanitized_metadata,
            note_text=sanitized_note_text or None,
            image_filename=sanitized_filename,
            image_bytes=image_bytes,
        )
        recipients = self._router.route_recipients(
            category=formatted_issue.category,
            urgency=formatted_issue.urgency,
        )

        report = IssueReport(
            source=source,
            property_name=sanitized_metadata.property_name,
            building=sanitized_metadata.building,
            unit_number=sanitized_metadata.unit_number,
            area=sanitized_metadata.area,
            note_text=sanitized_note_text or None,
            image_filename=sanitized_filename,
            raw_observations=raw_observations,
            reported_observation=formatted_issue.reported_observation,
            issue=formatted_issue.issue,
            urgency=formatted_issue.urgency,
            category=formatted_issue.category,
            recommended_action=formatted_issue.recommended_action,
            extracted_entities=formatted_issue.extracted_entities,
            confidence=formatted_issue.confidence,
            needs_followup=formatted_issue.needs_followup,
            followup_questions=formatted_issue.followup_questions,
            photo_observation=formatted_issue.photo_observation,
            recipients=recipients,
        )

        self._repository.save_issue_report(report)
        self._logger.info(
            "Issue report created",
            extra={
                "context": {
                    "report_id": report.report_id,
                    "source": report.source.value,
                    "property_name": report.property_name,
                    "building": report.building,
                    "unit_number": report.unit_number,
                    "urgency": report.urgency.value,
                    "category": report.category.value,
                }
            },
        )
        return report

    def list_recent_activity(self, limit: int = 100) -> list[dict]:
        return self._repository.list_recent_activity(limit=limit)

    def _sanitize_metadata(self, metadata: IssueMetadata) -> IssueMetadata:
        return IssueMetadata(
            property_name=sanitize_user_text(metadata.property_name, max_chars=120),
            building=sanitize_user_text(metadata.building, max_chars=120),
            unit_number=sanitize_user_text(metadata.unit_number, max_chars=30),
            area=sanitize_user_text(metadata.area or "", max_chars=120) or None,
        )

    def _build_observation_context(
        self,
        source: IssueSource,
        metadata: IssueMetadata,
        note_text: str,
        image_filename: str | None,
        image_bytes: bytes | None,
    ) -> str:
        area = metadata.area or "Unknown"
        note_block = note_text or "[none provided]"
        image_name = image_filename or "[none provided]"
        image_length = len(image_bytes) if image_bytes else 0
        context = (
            f"Source: {source.value}\n"
            f"Property: {metadata.property_name}\n"
            f"Building: {metadata.building}\n"
            f"Unit: {metadata.unit_number}\n"
            f"Area: {area}\n"
            f"Note: {note_block}\n"
            f"Image Filename: {image_name}\n"
            f"Image Bytes Length: {image_length}"
        )
        return context[:4000]
