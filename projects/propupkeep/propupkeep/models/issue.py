from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Urgency(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    UNKNOWN = "Unknown"


class IssueCategory(str, Enum):
    SAFETY = "Safety"
    PLUMBING = "Plumbing"
    ELECTRICAL = "Electrical"
    HVAC = "HVAC"
    APPLIANCE = "Appliance"
    COSMETIC = "Cosmetic"
    GENERAL = "General"
    UNKNOWN = "Unknown"


class IssueSource(str, Enum):
    NOTE = "note"
    PHOTO = "photo"


class Status(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"


COMMENT_AUTHOR_ROLES = ("Leasing", "Maintenance", "Safety", "PM", "Vendor", "Other")


class ExtractedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_terms: list[str] = Field(default_factory=list)
    people_terms: list[str] = Field(default_factory=list)
    asset_terms: list[str] = Field(default_factory=list)
    animal_terms: list[str] = Field(default_factory=list)
    quantity_terms: list[str] = Field(default_factory=list)

    @field_validator(
        "location_terms",
        "people_terms",
        "asset_terms",
        "animal_terms",
        "quantity_terms",
        mode="before",
    )
    @classmethod
    def normalize_terms(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        normalized: list[str] = []
        for term in value:
            cleaned = str(term).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class ConfidenceScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: float = Field(..., ge=0.0, le=1.0)
    urgency: float = Field(..., ge=0.0, le=1.0)


class IssueMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_name: str = Field(..., min_length=1, max_length=120)
    building: str = Field(..., min_length=1, max_length=120)
    unit_number: str = Field(..., min_length=1, max_length=30)
    area: str | None = Field(default=None, max_length=120)

    @field_validator("property_name", "building", "unit_number", "area", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class Comment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment_id: str = Field(default_factory=lambda: str(uuid4()))
    author_name: str = Field(..., min_length=1, max_length=80)
    author_role: str = Field(..., min_length=1, max_length=30)
    message: str = Field(..., min_length=1, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("author_name", "author_role", "message", mode="before")
    @classmethod
    def strip_comment_text(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("author_role")
    @classmethod
    def validate_author_role(cls, value: str) -> str:
        if value not in COMMENT_AUTHOR_ROLES:
            raise ValueError(f"author_role must be one of: {', '.join(COMMENT_AUTHOR_ROLES)}")
        return value


class AIFormattedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue: str = Field(..., min_length=3, max_length=500)
    reported_observation: str = Field(..., min_length=3, max_length=1000)
    urgency: Urgency
    category: IssueCategory
    recommended_action: str = Field(..., min_length=3, max_length=1200)
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    confidence: ConfidenceScores
    needs_followup: bool = False
    followup_questions: list[str] = Field(default_factory=list)
    photo_observation: str | None = Field(default=None, max_length=500)

    @field_validator("issue", "reported_observation", "recommended_action", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("urgency", mode="before")
    @classmethod
    def normalize_urgency(cls, value: Urgency | str) -> Urgency | str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            mapping = {
                "high": Urgency.HIGH,
                "medium": Urgency.MEDIUM,
                "low": Urgency.LOW,
                "unknown": Urgency.UNKNOWN,
            }
            return mapping.get(normalized, value.strip())
        return value

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: IssueCategory | str) -> IssueCategory | str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            mapping = {
                "safety": IssueCategory.SAFETY,
                "plumbing": IssueCategory.PLUMBING,
                "electrical": IssueCategory.ELECTRICAL,
                "hvac": IssueCategory.HVAC,
                "appliance": IssueCategory.APPLIANCE,
                "cosmetic": IssueCategory.COSMETIC,
                "general": IssueCategory.GENERAL,
                "unknown": IssueCategory.UNKNOWN,
            }
            return mapping.get(normalized, value.strip())
        return value

    @field_validator("followup_questions", mode="before")
    @classmethod
    def normalize_followups(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        questions: list[str] = []
        for question in value:
            cleaned = str(question).strip()
            if cleaned and cleaned not in questions:
                questions.append(cleaned)
        return questions

    @field_validator("photo_observation", mode="before")
    @classmethod
    def normalize_photo_observation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_followup_consistency(self) -> AIFormattedIssue:
        if self.needs_followup and not self.followup_questions:
            raise ValueError("followup_questions must be provided when needs_followup is true.")
        return self


class IssueReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=lambda: str(uuid4()))
    source: IssueSource
    property_name: str = Field(..., min_length=1, max_length=120)
    building: str = Field(..., min_length=1, max_length=120)
    unit_number: str = Field(..., min_length=1, max_length=30)
    area: str | None = Field(default=None, max_length=120)
    note_text: str | None = Field(default=None, max_length=3000)
    image_filename: str | None = Field(default=None, max_length=255)
    image_path: str | None = Field(default=None, max_length=500)
    image_mime: str | None = Field(default=None, max_length=50)
    raw_observations: str = Field(..., min_length=1, max_length=4000)
    reported_observation: str = Field(..., min_length=3, max_length=1000)
    issue: str = Field(..., min_length=3, max_length=500)
    urgency: Urgency
    category: IssueCategory
    recommended_action: str = Field(..., min_length=3, max_length=1200)
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    confidence: ConfidenceScores
    needs_followup: bool = False
    followup_questions: list[str] = Field(default_factory=list)
    photo_observation: str | None = Field(default=None, max_length=500)
    status: Status = Status.OPEN
    comments: list[Comment] = Field(default_factory=list)
    recipients: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "property_name",
        "building",
        "unit_number",
        "area",
        "note_text",
        "image_filename",
        "image_path",
        "image_mime",
        "raw_observations",
        "reported_observation",
        "issue",
        "recommended_action",
        "photo_observation",
        mode="before",
    )
    @classmethod
    def strip_input(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def validate_comment_timestamps(self) -> IssueReport:
        if not self.updated_at:
            self.updated_at = self.created_at
        return self

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("image_path must be a safe relative path.")
        return value

    @field_validator("image_mime")
    @classmethod
    def validate_image_mime(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"image/png", "image/jpeg", "image/jpg"}
        normalized = value.lower().strip()
        if normalized not in allowed:
            raise ValueError("image_mime must be one of image/png, image/jpeg, image/jpg.")
        return normalized
