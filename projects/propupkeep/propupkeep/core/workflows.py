from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from propupkeep.ai.formatter import OpenAIIssueFormatter
from propupkeep.core.errors import UserVisibleError
from propupkeep.core.logging_utils import get_logger
from propupkeep.core.sanitize import sanitize_filename, sanitize_user_text
from propupkeep.models.issue import IssueMetadata, IssueReport, IssueSource
from propupkeep.services.router import IssueRouter
from propupkeep.storage.repository import IssueRepository


class IssueWorkflowService:
    _allowed_image_mime = {"image/png", "image/jpeg", "image/jpg"}
    _mime_to_extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
    }

    def __init__(
        self,
        formatter: OpenAIIssueFormatter,
        router: IssueRouter,
        repository: IssueRepository,
        max_input_chars: int,
        max_upload_bytes: int,
        uploads_dir: Path,
        project_root: Path,
    ) -> None:
        self._formatter = formatter
        self._router = router
        self._repository = repository
        self._max_input_chars = max_input_chars
        self._max_upload_bytes = max_upload_bytes
        self._project_root = project_root.resolve()
        self._uploads_dir = uploads_dir.resolve()
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        self._logger = get_logger(__name__)

    def submit_issue(
        self,
        source: IssueSource,
        note_text: str,
        metadata: IssueMetadata,
        image_bytes: bytes | None = None,
        image_filename: str | None = None,
        image_mime: str | None = None,
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
        if has_image and len(image_bytes) > self._max_upload_bytes:
            raise UserVisibleError("The uploaded image is too large. Please upload a smaller file.")
        normalized_image_mime = self._normalize_image_mime(image_mime) if has_image else None
        if has_image and not normalized_image_mime:
            raise UserVisibleError("Unsupported image type. Please upload PNG or JPEG.")

        report_id = str(uuid4())

        raw_observations = self._build_observation_context(
            source=source,
            metadata=sanitized_metadata,
            note_text=sanitized_note_text,
            image_filename=sanitized_filename,
            image_bytes=image_bytes,
            image_mime=normalized_image_mime,
        )

        formatted_issue = self._formatter.format_issue(
            source=source,
            metadata=sanitized_metadata,
            note_text=sanitized_note_text or None,
            image_filename=sanitized_filename,
            image_bytes=image_bytes,
            image_mime=normalized_image_mime,
        )
        recipients = self._router.route_recipients(
            category=formatted_issue.category,
            urgency=formatted_issue.urgency,
        )

        image_path = None
        if has_image and image_bytes and normalized_image_mime:
            image_path = self._save_image_upload(
                report_id=report_id,
                image_bytes=image_bytes,
                image_filename=sanitized_filename,
                image_mime=normalized_image_mime,
            )

        report = IssueReport(
            report_id=report_id,
            source=source,
            property_name=sanitized_metadata.property_name,
            building=sanitized_metadata.building,
            unit_number=sanitized_metadata.unit_number,
            area=sanitized_metadata.area,
            note_text=sanitized_note_text or None,
            image_filename=sanitized_filename,
            image_path=image_path,
            image_mime=normalized_image_mime,
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
                    "has_image": bool(report.image_path),
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
        image_mime: str | None,
    ) -> str:
        area = metadata.area or "Unknown"
        note_block = note_text or "[none provided]"
        image_name = image_filename or "[none provided]"
        mime_block = image_mime or "Unknown"
        image_length = len(image_bytes) if image_bytes else 0
        context = (
            f"Source: {source.value}\n"
            f"Property: {metadata.property_name}\n"
            f"Building: {metadata.building}\n"
            f"Unit: {metadata.unit_number}\n"
            f"Area: {area}\n"
            f"Note: {note_block}\n"
            f"Image Filename: {image_name}\n"
            f"Image Mime: {mime_block}\n"
            f"Image Bytes Length: {image_length}"
        )
        return context[:4000]

    def _normalize_image_mime(self, image_mime: str | None) -> str | None:
        if not image_mime:
            return None
        normalized = image_mime.strip().lower()
        if normalized in self._allowed_image_mime:
            return normalized
        return None

    def _save_image_upload(
        self,
        report_id: str,
        image_bytes: bytes,
        image_filename: str | None,
        image_mime: str,
    ) -> str:
        extension = Path(image_filename or "").suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg"}:
            extension = self._mime_to_extension[image_mime]

        target_name = f"{report_id}{extension}"
        uploads_root = self._uploads_dir.resolve()
        target_path = (uploads_root / target_name).resolve()
        if uploads_root not in target_path.parents:
            raise UserVisibleError("Invalid upload target path.")

        try:
            with target_path.open("wb") as handle:
                handle.write(image_bytes)
        except OSError as exc:
            raise UserVisibleError(
                "Could not store uploaded image locally.",
                detail=str(exc),
            ) from exc

        try:
            relative_path = target_path.relative_to(self._project_root)
        except ValueError as exc:
            raise UserVisibleError("Could not resolve upload storage path safely.") from exc
        return str(relative_path)
