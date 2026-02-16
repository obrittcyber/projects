from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from propupkeep.ai.prompts import JSON_OUTPUT_INSTRUCTIONS, TEAM_BRIEF_SYSTEM_PROMPT
from propupkeep.config.settings import Settings
from propupkeep.core.errors import AIFormattingError, ConfigurationError
from propupkeep.core.logging_utils import get_logger
from propupkeep.models.issue import AIFormattedIssue, IssueMetadata, IssueSource


class OpenAIIssueFormatter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)

    def format_issue(
        self,
        source: IssueSource,
        metadata: IssueMetadata,
        note_text: str | None,
        image_filename: str | None = None,
        image_bytes: bytes | None = None,
    ) -> AIFormattedIssue:
        if not self._settings.openai_api_key:
            raise ConfigurationError(
                "AI formatting is unavailable. Set OPENAI_API_KEY to enable this feature."
            )

        user_prompt = self._build_user_prompt(
            source=source,
            metadata=metadata,
            note_text=note_text,
            image_filename=image_filename,
            image_bytes=image_bytes,
        )
        messages = [
            {"role": "system", "content": f"{TEAM_BRIEF_SYSTEM_PROMPT}\n\n{JSON_OUTPUT_INSTRUCTIONS}"},
            {"role": "user", "content": user_prompt},
        ]

        initial_content = self._chat_completion(messages)
        try:
            return self._parse_and_validate(initial_content)
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            self._logger.warning(
                "Initial AI response invalid; attempting single repair retry",
                extra={"context": {"error": str(first_error)}},
            )

            repaired_content = self._repair_once(
                invalid_response=initial_content,
                validation_error=str(first_error),
                source=source,
                metadata=metadata,
                note_text=note_text,
                image_filename=image_filename,
                image_bytes=image_bytes,
            )
            try:
                return self._parse_and_validate(repaired_content)
            except (ValidationError, ValueError, json.JSONDecodeError) as second_error:
                self._logger.error(
                    "AI response invalid after repair retry",
                    extra={"context": {"error": str(second_error)}},
                )
                raise AIFormattingError(
                    "We could not format this note right now. Please edit and try again.",
                    detail=str(second_error),
                ) from second_error

    def _repair_once(
        self,
        invalid_response: str,
        validation_error: str,
        source: IssueSource,
        metadata: IssueMetadata,
        note_text: str | None,
        image_filename: str | None,
        image_bytes: bytes | None,
    ) -> str:
        submission_context = self._build_user_prompt(
            source=source,
            metadata=metadata,
            note_text=note_text,
            image_filename=image_filename,
            image_bytes=image_bytes,
        )
        repair_prompt = (
            "Your previous answer failed JSON validation.\n"
            "Repair the output to satisfy the exact schema requirements.\n"
            "Do not change the core meaning or user-stated facts.\n\n"
            f"{submission_context}\n\n"
            f"Invalid Output:\n{invalid_response}\n\n"
            f"Validation Error:\n{validation_error}\n\n"
            f"{JSON_OUTPUT_INSTRUCTIONS}"
        )
        repair_messages = [
            {"role": "system", "content": TEAM_BRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": repair_prompt},
        ]
        return self._chat_completion(repair_messages)

    def _parse_and_validate(self, model_content: str) -> AIFormattedIssue:
        payload = self._extract_json_payload(model_content)
        return AIFormattedIssue.model_validate(payload)

    def _extract_json_payload(self, model_content: str) -> dict:
        text = model_content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("No JSON object found in the AI response.") from None
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise ValueError("AI response JSON must be an object.")
        return parsed

    def _chat_completion(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._settings.openai_model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        request = Request(
            self._settings.openai_chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._settings.request_timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            raise AIFormattingError(
                "AI service is temporarily unavailable. Please try again shortly.",
                detail=f"HTTP {exc.code}: {response_text}",
            ) from exc
        except URLError as exc:
            raise AIFormattingError(
                "Network error while contacting AI service. Please retry.",
                detail=str(exc.reason),
            ) from exc

        try:
            parsed_response = json.loads(body)
            return parsed_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIFormattingError(
                "AI service returned an unexpected response format.",
                detail=str(exc),
            ) from exc

    def _build_user_prompt(
        self,
        source: IssueSource,
        metadata: IssueMetadata,
        note_text: str | None,
        image_filename: str | None,
        image_bytes: bytes | None,
    ) -> str:
        note_block = note_text if note_text else "[none provided]"
        image_name = image_filename if image_filename else "[none provided]"
        image_size = len(image_bytes) if image_bytes else 0
        area = metadata.area if metadata.area else "Unknown"

        return (
            "Create a structured Issue Report for property operations.\n"
            "Preserve factual entities exactly as reported.\n"
            "If facts are missing, use Unknown and set needs_followup=true with questions.\n\n"
            "Submission Facts (must preserve):\n"
            f"- source: {source.value}\n"
            f"- property_name: {metadata.property_name}\n"
            f"- building: {metadata.building}\n"
            f"- unit_number: {metadata.unit_number}\n"
            f"- area: {area}\n"
            f"- note_text: {note_block}\n"
            f"- image_filename: {image_name}\n"
            f"- image_bytes_length: {image_size}\n\n"
            "When source is photo and note_text is empty, rely on filename/metadata only "
            "and ask follow-up questions as needed."
        )
