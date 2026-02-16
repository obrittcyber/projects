from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from ai.prompts import JSON_OUTPUT_INSTRUCTIONS, TEAM_BRIEF_SYSTEM_PROMPT
from config.settings import Settings
from core.errors import AIFormattingError, ConfigurationError
from core.logging_utils import get_logger
from models.issue import AIFormattedIssue


class OpenAIIssueFormatter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)

    def format_issue(self, raw_observations: str, building: str, unit_number: str) -> AIFormattedIssue:
        if not self._settings.openai_api_key:
            raise ConfigurationError(
                "AI formatting is unavailable. Set OPENAI_API_KEY to enable this feature."
            )

        user_prompt = (
            "Convert leasing consultant notes into a structured issue report.\n\n"
            f"Building: {building}\n"
            f"Unit Number: {unit_number}\n"
            f"Raw Observations: {raw_observations}\n"
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
                building=building,
                unit_number=unit_number,
                raw_observations=raw_observations,
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
        building: str,
        unit_number: str,
        raw_observations: str,
    ) -> str:
        repair_prompt = (
            "Your previous answer failed JSON validation.\n"
            "Repair the output to satisfy the exact schema requirements.\n"
            "Do not change the core meaning of the report.\n\n"
            f"Building: {building}\n"
            f"Unit Number: {unit_number}\n"
            f"Raw Observations: {raw_observations}\n\n"
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
