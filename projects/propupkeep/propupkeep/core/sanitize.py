from __future__ import annotations

import re


CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
FILENAME_SAFE_CHARS_PATTERN = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_user_text(text: str, max_chars: int) -> str:
    cleaned = CONTROL_CHARS_PATTERN.sub(" ", text or "")
    cleaned = cleaned.replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned[:max_chars]


def sanitize_filename(filename: str) -> str:
    if not filename:
        return "upload"
    sanitized = FILENAME_SAFE_CHARS_PATTERN.sub("_", filename)
    return sanitized[:255]
