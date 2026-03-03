from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from propupkeep.core.logging_utils import get_logger


class TranscriptionError(Exception):
    """Controlled transcription failure."""


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    if not audio_bytes:
        raise TranscriptionError("No audio provided for transcription.")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TranscriptionError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"))
    endpoint = os.getenv("OPENAI_TRANSCRIPTION_URL", "https://api.openai.com/v1/audio/transcriptions")
    boundary = f"----PropUpkeepBoundary{uuid4().hex}"
    file_name = f"voice_note{_mime_to_extension(mime_type)}"
    effective_mime = mime_type or "audio/wav"

    body = _build_multipart_body(
        boundary=boundary,
        model=model,
        file_name=file_name,
        mime_type=effective_mime,
        audio_bytes=audio_bytes,
    )
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        get_logger(__name__).warning(
            "Voice transcription HTTP error",
            extra={"context": {"status_code": exc.code, "detail": response_text}},
        )
        raise TranscriptionError("Transcription service is unavailable right now.") from exc
    except URLError as exc:
        get_logger(__name__).warning(
            "Voice transcription network error",
            extra={"context": {"detail": str(exc.reason)}},
        )
        raise TranscriptionError("Network error while transcribing audio.") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        get_logger(__name__).warning(
            "Voice transcription invalid JSON response",
            extra={"context": {"detail": str(exc)}},
        )
        raise TranscriptionError("Transcription response format was invalid.") from exc

    transcript = str(parsed.get("text", "")).strip()
    if not transcript:
        raise TranscriptionError("Transcription returned no text.")
    return transcript


def _build_multipart_body(
    boundary: str,
    model: str,
    file_name: str,
    mime_type: str,
    audio_bytes: bytes,
) -> bytes:
    line_break = b"\r\n"
    body = bytearray()

    body.extend(f"--{boundary}".encode("utf-8"))
    body.extend(line_break)
    body.extend(b'Content-Disposition: form-data; name="model"')
    body.extend(line_break)
    body.extend(line_break)
    body.extend(model.encode("utf-8"))
    body.extend(line_break)

    body.extend(f"--{boundary}".encode("utf-8"))
    body.extend(line_break)
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{file_name}"'.encode("utf-8"))
    body.extend(line_break)
    body.extend(f"Content-Type: {mime_type}".encode("utf-8"))
    body.extend(line_break)
    body.extend(line_break)
    body.extend(audio_bytes)
    body.extend(line_break)

    body.extend(f"--{boundary}--".encode("utf-8"))
    body.extend(line_break)
    return bytes(body)


def _mime_to_extension(mime_type: str) -> str:
    normalized = (mime_type or "").lower()
    if "mp3" in normalized or "mpeg" in normalized:
        return ".mp3"
    if "mp4" in normalized or "m4a" in normalized:
        return ".m4a"
    if "ogg" in normalized:
        return ".ogg"
    if "webm" in normalized:
        return ".webm"
    return ".wav"
