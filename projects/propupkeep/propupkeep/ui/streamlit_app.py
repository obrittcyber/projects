from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from propupkeep.ai.formatter import OpenAIIssueFormatter
from propupkeep.config.settings import Settings, get_settings
from propupkeep.core.errors import UserVisibleError
from propupkeep.core.logging_utils import configure_logging, get_logger
from propupkeep.core.workflows import IssueWorkflowService
from propupkeep.models.issue import IssueMetadata, IssueSource
from propupkeep.services.router import IssueRouter
from propupkeep.storage.repository import JsonlIssueRepository


def _render_base_styles() -> None:
    st.markdown(
        """
        <style>
          .main .block-container {
            max-width: 520px;
            padding-top: 1rem;
            padding-bottom: 2rem;
          }
          @media (min-width: 960px) {
            .main .block-container { max-width: 760px; }
          }
          .stButton > button {
            width: 100%;
            border-radius: 999px;
            font-weight: 600;
            padding: 0.55rem 1rem;
          }
          .stTextArea textarea {
            min-height: 190px;
          }
          .feed-card {
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 0.8rem;
            margin-bottom: 0.7rem;
          }
          .feed-meta {
            color: #6b7280;
            font-size: 0.85rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def _build_workflow() -> tuple[Settings, IssueWorkflowService]:
    settings = get_settings()
    configure_logging(settings.log_level)

    repository = JsonlIssueRepository(settings.data_file)
    formatter = OpenAIIssueFormatter(settings=settings)
    router = IssueRouter()
    workflow = IssueWorkflowService(
        formatter=formatter,
        router=router,
        repository=repository,
        max_input_chars=settings.max_input_chars,
        max_upload_bytes=settings.max_upload_bytes,
        uploads_dir=settings.uploads_dir,
        project_root=settings.project_root,
    )
    return settings, workflow


def _format_ts(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone().strftime("%b %d, %Y %I:%M %p")
    except Exception:  # noqa: BLE001
        return value


def _date_sort_value(value: str | None) -> float:
    if not value:
        return float("-inf")
    raw = str(value).strip()
    if not raw:
        return float("-inf")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.timestamp()
    except Exception:  # noqa: BLE001
        return float("-inf")


def _urgency_rank(value: str | None) -> int:
    ranking = {
        "emergency": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
        "unknown": 0,
    }
    normalized = (value or "").strip().lower()
    return ranking.get(normalized, 0)


def _is_maintenance_routed(recipients: list[str] | None) -> bool:
    if not recipients:
        return False
    return any("maintenance" in str(item).lower() for item in recipients)


def _resolve_image_path(project_root: Path, image_path: str) -> Path | None:
    try:
        raw_path = Path(image_path)
        resolved = raw_path.resolve() if raw_path.is_absolute() else (project_root / raw_path).resolve()
    except OSError:
        return None

    root = project_root.resolve()
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


def _render_structured_report(report: dict, heading: str = "Structured Report") -> None:
    st.markdown(f"### {heading}")
    st.markdown(f"**Source**\n\n{report.get('source', 'unknown')}")
    st.markdown(f"**Reported Observation (verbatim style)**\n\n{report.get('reported_observation', '')}")
    st.markdown(f"**Issue**\n\n{report.get('issue', '')}")
    st.markdown(f"**Urgency**\n\n{report.get('urgency', '')}")
    st.markdown(f"**Category**\n\n{report.get('category', '')}")
    st.markdown(f"**Recommended Action**\n\n{report.get('recommended_action', '')}")

    confidence = report.get("confidence") or {}
    st.markdown(
        "**Confidence**\n\n"
        f"- Category: {confidence.get('category', 'n/a')}\n"
        f"- Urgency: {confidence.get('urgency', 'n/a')}"
    )

    recipients = report.get("recipients", [])
    if recipients:
        st.markdown(f"**Routing Recipients**\n\n{', '.join(recipients)}")

    extracted = report.get("extracted_entities") or {}
    non_empty_entities = {
        key: values for key, values in extracted.items() if isinstance(values, list) and values
    }
    if non_empty_entities:
        entity_lines = [
            f"- {key}: {', '.join(values)}" for key, values in non_empty_entities.items()
        ]
        st.markdown("**Extracted Entities**\n\n" + "\n".join(entity_lines))

    if report.get("photo_observation"):
        st.markdown(f"**Photo Observation**\n\n{report['photo_observation']}")

    if report.get("needs_followup"):
        questions = report.get("followup_questions", [])
        if questions:
            st.markdown("**Follow-up Questions Needed**\n\n" + "\n".join(f"- {q}" for q in questions))
        else:
            st.markdown("**Follow-up Questions Needed**\n\n- Please provide additional details.")

    if report.get("image_filename"):
        st.markdown(f"**Image Filename**\n\n{report['image_filename']}")


def run_app() -> None:
    st.set_page_config(
        page_title="PropUpkeep Mobile",
        page_icon=":building_construction:",
        layout="centered",
    )
    _render_base_styles()

    logger = get_logger(__name__)
    settings, workflow = _build_workflow()

    st.title("PropUpkeep — AI-Powered Operational Visibility")
    st.caption("Turn field observations into structured, routable work items with an audit trail.")
    st.caption("Not for emergencies; call 911/management.")

    with st.sidebar:
        st.header("Property Selector")
        property_name = st.selectbox(
            "Property",
            options=[
                "Oak Ridge Apartments",
                "Maple Court Homes",
                "Riverstone Commons",
            ],
            index=0,
        )
        building = st.selectbox(
            "Building",
            options=["Building A", "Building B", "Building C", "Townhomes"],
            index=0,
        )
        unit_number = st.selectbox(
            "Unit Number",
            options=[
                "101",
                "102",
                "103",
                "104",
                "201",
                "202",
                "203",
                "204",
            ],
            index=0,
        )
        area_choice = st.selectbox(
            "Area",
            options=[
                "Unknown",
                "Kitchen",
                "Bathroom",
                "Living Room",
                "Bedroom",
                "Laundry",
                "Exterior",
                "Hallway",
                "Other",
            ],
            index=0,
        )
        custom_area = ""
        if area_choice == "Other":
            custom_area = st.text_input("Custom Area", placeholder="Ex: stairwell near Unit 204")
        area = custom_area.strip() if area_choice == "Other" else area_choice

        st.caption(f"Working on {property_name} · {building} · Unit {unit_number}")
        st.caption(f"Max upload size: {settings.max_upload_mb} MB")

    def _build_metadata() -> IssueMetadata:
        return IssueMetadata(
            property_name=property_name,
            building=building,
            unit_number=unit_number,
            area=None if area == "Unknown" else area,
        )

    quick_snap_tab, unit_notes_tab, community_feed_tab = st.tabs(
        ["Quick Snap", "Unit Notes", "Community Feed"]
    )

    with quick_snap_tab:
        st.subheader("Quick Snap")
        photo = st.file_uploader(
            "Upload unit photo",
            type=["jpg", "jpeg", "png"],
            key="quick_snap_upload",
        )
        quick_note_text = st.text_area(
            "Quick Note (optional)",
            placeholder="Example: Burn mark near outlet behind fridge",
            key="quick_snap_note",
        )

        oversized_upload = bool(photo and photo.size > settings.max_upload_bytes)
        invalid_mime = bool(
            photo and (photo.type or "").lower() not in {"image/png", "image/jpeg", "image/jpg"}
        )
        if oversized_upload:
            st.error(
                f"Photo is larger than {settings.max_upload_mb} MB. "
                "Please upload a smaller file."
            )
        if invalid_mime:
            st.error("Unsupported image type. Please upload a PNG or JPEG image.")

        if photo and not oversized_upload and not invalid_mime:
            st.image(photo, use_container_width=True)

        if st.button("Format for Team", key="format_for_team_photo"):
            has_note = bool(quick_note_text.strip())
            has_photo = bool(photo)

            if not has_note and not has_photo:
                st.warning("Add a note or upload a photo before formatting for the team.")
            elif oversized_upload:
                st.warning("Upload a smaller photo before submitting.")
            elif invalid_mime:
                st.warning("Unsupported image type. Please upload PNG or JPEG.")
            else:
                image_bytes = photo.getvalue() if photo else None
                image_filename = photo.name if photo else None
                image_mime = (photo.type or "").lower() if photo else None
                with st.spinner("Formatting report..."):
                    try:
                        report = workflow.submit_issue(
                            source=IssueSource.PHOTO,
                            note_text=quick_note_text,
                            metadata=_build_metadata(),
                            image_bytes=image_bytes,
                            image_filename=image_filename,
                            image_mime=image_mime,
                        )
                    except UserVisibleError as exc:
                        logger.warning(
                            "Photo submission failed",
                            extra={"context": {"detail": exc.detail}},
                        )
                        st.error(exc.user_message)
                    except Exception:  # noqa: BLE001
                        logger.exception("Unexpected photo submission failure")
                        st.error("Unexpected error while formatting photo submission. Please retry.")
                    else:
                        st.session_state["last_photo_report"] = report.model_dump(mode="json")
                        st.success("Structured issue report generated from quick snap.")

        if st.session_state.get("last_photo_report"):
            _render_structured_report(st.session_state["last_photo_report"])

    with unit_notes_tab:
        st.subheader("Unit Notes")
        note_text = st.text_area(
            "Raw Observations",
            placeholder=(
                "Ex: 2B dishwasher leaking from lower right corner, "
                "possible gasket issue, floor wet near sink."
            ),
            key="unit_note_text",
        )

        if st.button("Format for Team", key="format_for_team"):
            with st.spinner("Formatting report..."):
                try:
                    report = workflow.submit_issue(
                        source=IssueSource.NOTE,
                        note_text=note_text,
                        metadata=_build_metadata(),
                    )
                except UserVisibleError as exc:
                    logger.warning(
                        "Issue formatting failed",
                        extra={"context": {"detail": exc.detail}},
                    )
                    st.error(exc.user_message)
                except Exception:  # noqa: BLE001
                    logger.exception("Unexpected issue formatting failure")
                    st.error(
                        "Something went wrong while formatting. "
                        "Please try again in a moment."
                    )
                else:
                    st.session_state["last_note_report"] = report.model_dump(mode="json")
                    st.success("Professional issue report generated.")

        if st.session_state.get("last_note_report"):
            _render_structured_report(st.session_state["last_note_report"])

    with community_feed_tab:
        st.subheader("Reviewing Logs")
        try:
            activity = workflow.list_recent_activity(limit=100)
        except UserVisibleError as exc:
            logger.warning("Failed to load activity feed", extra={"context": {"detail": exc.detail}})
            st.error(exc.user_message)
            activity = []
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected activity feed failure")
            st.error("Unexpected error while loading activity feed.")
            activity = []

        if not activity:
            st.info("No entries yet. Submit from Quick Snap or Unit Notes to populate this feed.")
        else:
            issue_records = [
                entry
                for entry in activity
                if entry.get("entry_type") == "issue_report" and isinstance(entry.get("payload"), dict)
            ]

            category_options = sorted(
                {
                    str(record["payload"].get("category", "")).strip()
                    for record in issue_records
                    if str(record["payload"].get("category", "")).strip()
                }
            )
            category_filter_options = ["All", "Maintenance View", *category_options]

            filter_col_1, filter_col_2, filter_col_3 = st.columns([2, 1, 2], gap="small")
            with filter_col_1:
                category_filter = st.selectbox(
                    "Category / Department",
                    options=category_filter_options,
                    index=0,
                    key="feed_category_department_filter",
                )
            with filter_col_2:
                source_filter = st.selectbox(
                    "Source",
                    options=["All", "note", "photo"],
                    index=0,
                    key="feed_source_filter",
                )
            with filter_col_3:
                sort_by = st.selectbox(
                    "Sort by",
                    options=[
                        "Date (Newest)",
                        "Date (Oldest)",
                        "Urgency (High->Low)",
                        "Urgency (Low->High)",
                    ],
                    index=0,
                    key="feed_sort_by",
                )

            filtered_records = issue_records
            if category_filter == "Maintenance View":
                filtered_records = [
                    record
                    for record in filtered_records
                    if _is_maintenance_routed(record["payload"].get("recipients", []))
                ]
            elif category_filter != "All":
                filtered_records = [
                    record
                    for record in filtered_records
                    if str(record["payload"].get("category", "")).strip() == category_filter
                ]

            if source_filter != "All":
                filtered_records = [
                    record
                    for record in filtered_records
                    if str(record["payload"].get("source", "")).strip().lower() == source_filter
                ]

            if sort_by == "Date (Newest)":
                filtered_records = sorted(
                    filtered_records,
                    key=lambda record: _date_sort_value(record.get("created_at")),
                    reverse=True,
                )
            elif sort_by == "Date (Oldest)":
                filtered_records = sorted(
                    filtered_records,
                    key=lambda record: _date_sort_value(record.get("created_at")),
                )
            elif sort_by == "Urgency (High->Low)":
                filtered_records = sorted(
                    filtered_records,
                    key=lambda record: (
                        _urgency_rank(record["payload"].get("urgency")),
                        _date_sort_value(record.get("created_at")),
                    ),
                    reverse=True,
                )
            else:  # Urgency (Low->High)
                filtered_records = sorted(
                    filtered_records,
                    key=lambda record: (
                        _urgency_rank(record["payload"].get("urgency")),
                        _date_sort_value(record.get("created_at")),
                    ),
                )

            if not filtered_records:
                st.info("No feed items match the selected filters.")

            for record in filtered_records:
                payload = record["payload"]
                issue_text = payload.get("issue", "")
                urgency = payload.get("urgency", "Unknown")
                category = payload.get("category", "Unknown")
                action = payload.get("recommended_action", "")
                recipients = payload.get("recipients", [])
                source = payload.get("source", "unknown")
                timestamp = _format_ts(str(record.get("created_at", "")))
                location = (
                    f"{payload.get('property_name', '-')}"
                    f" · {payload.get('building', '-')}"
                    f" · Unit {payload.get('unit_number', '-')}"
                    f" · {payload.get('area', 'Unknown') or 'Unknown'}"
                )
                image_path = payload.get("image_path")

                with st.container():
                    thumb_col, detail_col = st.columns([1, 3], gap="small")
                    with thumb_col:
                        if image_path:
                            resolved_path = _resolve_image_path(settings.project_root, str(image_path))
                            if resolved_path and resolved_path.exists():
                                st.image(str(resolved_path), width=160)
                            else:
                                st.caption("Image not available")
                        else:
                            st.caption("No image")

                    with detail_col:
                        st.markdown(f"**Issue:** {issue_text}")
                        st.markdown(f"**Urgency:** {urgency}")
                        st.markdown(f"**Category:** {category}")
                        st.markdown(f"**Recommended Action:** {action}")
                        st.markdown(
                            f"**Recipients:** {', '.join(recipients) if recipients else 'Unassigned'}"
                        )
                        st.markdown(f"**Source:** {source}")
                        st.markdown(f"**Timestamp:** {timestamp}")
                        st.markdown(f"**Location:** {location}")
                st.divider()
