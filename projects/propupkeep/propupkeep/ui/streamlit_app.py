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
    if report.get("image_path"):
        st.markdown(f"**Image Path**\n\n{report['image_path']}")
    if report.get("image_mime"):
        st.markdown(f"**Image MIME**\n\n{report['image_mime']}")


def run_app() -> None:
    st.set_page_config(
        page_title="PropUpkeep Mobile",
        page_icon=":building_construction:",
        layout="centered",
    )
    _render_base_styles()

    logger = get_logger(__name__)
    settings, workflow = _build_workflow()

    st.title("PropUpkeep")
    st.caption("Mobile-first intake for leasing and maintenance coordination")
    st.warning("Not for emergencies; call 911/management.")

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
            for entry in activity:
                entry_type = entry.get("entry_type")
                payload = entry.get("payload", {})
                timestamp = _format_ts(entry.get("created_at", ""))
                source_label = payload.get("source", entry_type)
                property_label = payload.get("property_name", "-")
                area_label = payload.get("area", "Unknown")

                st.markdown('<div class="feed-card">', unsafe_allow_html=True)
                st.markdown(
                    (
                        f"<div class='feed-meta'>{property_label}"
                        f" · {payload.get('building', '-')}"
                        f" · Unit {payload.get('unit_number', '-')}"
                        f" · {area_label}"
                        f" · {source_label}"
                        f" · {timestamp}</div>"
                    ),
                    unsafe_allow_html=True,
                )
                if entry_type == "issue_report":
                    source = payload.get("source", "unknown")
                    image_path = payload.get("image_path")
                    detail_col = st.container()
                    if image_path:
                        thumb_col, content_col = st.columns([1, 3], gap="small")
                        with thumb_col:
                            resolved_path = _resolve_image_path(settings.project_root, image_path)
                            if resolved_path and resolved_path.exists():
                                st.image(str(resolved_path), width=160)
                            else:
                                st.caption("Image not available")
                        detail_col = content_col

                    with detail_col:
                        st.markdown(f"**Issue:** {payload.get('issue', '')}")
                        st.markdown(f"**Source:** {source}")
                        st.markdown(f"**Urgency:** {payload.get('urgency', '')}")
                        st.markdown(f"**Category:** {payload.get('category', '')}")
                        st.markdown(
                            f"**Recommended Action:** {payload.get('recommended_action', '')}"
                        )
                        st.markdown(
                            f"**Reported Observation:** {payload.get('reported_observation', '')}"
                        )
                        recipients = payload.get("recipients", [])
                        if recipients:
                            st.markdown(f"**Recipients:** {', '.join(recipients)}")
                        if payload.get("image_filename"):
                            st.markdown(f"**Image Filename:** {payload.get('image_filename')}")
                        if payload.get("image_mime"):
                            st.markdown(f"**Image MIME:** {payload.get('image_mime')}")
                        if payload.get("needs_followup"):
                            questions = payload.get("followup_questions", [])
                            if questions:
                                st.markdown(
                                    "**Follow-up Questions:**\n\n" + "\n".join(f"- {q}" for q in questions)
                                )
                        extracted = payload.get("extracted_entities", {})
                        if extracted:
                            extracted_lines = []
                            for label, values in extracted.items():
                                if values:
                                    extracted_lines.append(f"- {label}: {', '.join(values)}")
                            if extracted_lines:
                                st.markdown("**Extracted Entities:**\n\n" + "\n".join(extracted_lines))
                else:  # Backward compatibility for older activity entries.
                    st.markdown(f"**Legacy Entry Type:** {entry_type}")
                    if payload:
                        st.json(payload)
                st.markdown("</div>", unsafe_allow_html=True)
