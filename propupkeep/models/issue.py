from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Urgency(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class IssueCategory(str, Enum):
    SAFETY = "Safety"
    PLUMBING = "Plumbing"
    ELECTRICAL = "Electrical"
    HVAC = "HVAC"
    APPLIANCE = "Appliance"
    COSMETIC = "Cosmetic"
    GENERAL = "General"


class AIFormattedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue: str = Field(..., min_length=3, max_length=500)
    urgency: Urgency
    category: IssueCategory
    recommended_action: str = Field(..., min_length=3, max_length=1200)

    @field_validator("issue", "recommended_action")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("urgency", mode="before")
    @classmethod
    def normalize_urgency(cls, value: Urgency | str) -> Urgency | str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            mapping = {"high": Urgency.HIGH, "medium": Urgency.MEDIUM, "low": Urgency.LOW}
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
            }
            return mapping.get(normalized, value.strip())
        return value


class IssueReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    building: str = Field(..., min_length=1, max_length=120)
    unit_number: str = Field(..., min_length=1, max_length=30)
    raw_observations: str = Field(..., min_length=1, max_length=4000)
    issue: str = Field(..., min_length=3, max_length=500)
    urgency: Urgency
    category: IssueCategory
    recommended_action: str = Field(..., min_length=3, max_length=1200)
    recipients: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "building",
        "unit_number",
        "raw_observations",
        "issue",
        "recommended_action",
        mode="before",
    )
    @classmethod
    def strip_input(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value


class SnapshotRecord(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    building: str = Field(..., min_length=1, max_length=120)
    unit_number: str = Field(..., min_length=1, max_length=30)
    file_name: str = Field(..., min_length=1, max_length=255)
    note: str = Field(default="", max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("building", "unit_number", "file_name", "note", mode="before")
    @classmethod
    def strip_snapshot_fields(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value
