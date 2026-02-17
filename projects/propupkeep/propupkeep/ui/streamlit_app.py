from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from propupkeep.ai.formatter import OpenAIIssueFormatter
from propupkeep.config.settings import Settings, get_settings
from propupkeep.core.errors import UserVisibleError
from propupkeep.core.logging_utils import configure_logging, get_logger
from propupkeep.core.workflows import IssueWorkflowService
from propupkeep.models.issue import COMMENT_AUTHOR_ROLES, IssueMetadata, IssueSource, Status
from propupkeep.services.exporter import export_issues_to_excel_bytes
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


def _format_ts(value: str | datetime | None) -> str:
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            raw = str(value or "").strip()
            if raw.endswith("Z"):
                raw = f"{raw[:-1]}+00:00"
            parsed = datetime.fromisoformat(raw)
        return parsed.astimezone().strftime("%b %d, %Y %I:%M %p")
    except Exception:  # noqa: BLE001
        return str(value or "")


def _date_sort_value(value: str | datetime | None) -> float:
    if not value:
        return float("-inf")
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            raw = str(value).strip()
            if not raw:
                return float("-inf")
            if raw.endswith("Z"):
                raw = f"{raw[:-1]}+00:00"
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


def _status_badge_html(status: str) -> str:
    palette = {
        Status.OPEN.value: ("#1f2937", "#e5e7eb"),
        Status.ACKNOWLEDGED.value: ("#1d4ed8", "#dbeafe"),
        Status.IN_PROGRESS.value: ("#92400e", "#fef3c7"),
        Status.MONITORING.value: ("#4338ca", "#e0e7ff"),
        Status.RESOLVED.value: ("#166534", "#dcfce7"),
    }
    text_color, bg_color = palette.get(status, ("#1f2937", "#e5e7eb"))
    return (
        "<span style='display:inline-block;padding:0.2rem 0.55rem;border-radius:999px;"
        f"font-size:0.78rem;font-weight:600;color:{text_color};background:{bg_color};'>"
        f"{status}</span>"
    )


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
            issues = workflow.list_issues(limit=100)
        except UserVisibleError as exc:
            logger.warning("Failed to load activity feed", extra={"context": {"detail": exc.detail}})
            st.error(exc.user_message)
            issues = []
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected activity feed failure")
            st.error("Unexpected error while loading activity feed.")
            issues = []

        if not issues:
            st.info("No entries yet. Submit from Quick Snap or Unit Notes to populate this feed.")
        else:
            category_options = sorted(
                {
                    str(issue.category.value).strip()
                    for issue in issues
                    if str(issue.category.value).strip()
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

            filtered_issues = issues
            if category_filter == "Maintenance View":
                filtered_issues = [
                    issue
                    for issue in filtered_issues
                    if _is_maintenance_routed(issue.recipients)
                ]
            elif category_filter != "All":
                filtered_issues = [
                    issue
                    for issue in filtered_issues
                    if str(issue.category.value).strip() == category_filter
                ]

            if source_filter != "All":
                filtered_issues = [
                    issue
                    for issue in filtered_issues
                    if str(issue.source.value).strip().lower() == source_filter
                ]

            if sort_by == "Date (Newest)":
                filtered_issues = sorted(
                    filtered_issues,
                    key=lambda issue: _date_sort_value(issue.created_at),
                    reverse=True,
                )
            elif sort_by == "Date (Oldest)":
                filtered_issues = sorted(
                    filtered_issues,
                    key=lambda issue: _date_sort_value(issue.created_at),
                )
            elif sort_by == "Urgency (High->Low)":
                filtered_issues = sorted(
                    filtered_issues,
                    key=lambda issue: (
                        _urgency_rank(issue.urgency.value),
                        _date_sort_value(issue.created_at),
                    ),
                    reverse=True,
                )
            else:  # Urgency (Low->High)
                filtered_issues = sorted(
                    filtered_issues,
                    key=lambda issue: (
                        _urgency_rank(issue.urgency.value),
                        _date_sort_value(issue.created_at),
                    ),
                )

            export_bytes = export_issues_to_excel_bytes(filtered_issues)
            st.download_button(
                label="Download Excel",
                data=export_bytes,
                file_name="propupkeep_reports.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                disabled=not filtered_issues,
                key="download_filtered_issues_excel",
            )

            if not filtered_issues:
                st.info("No feed items match the selected filters.")

            for issue_idx, issue in enumerate(filtered_issues):
                issue_id = str(issue.report_id or f"issue-{issue_idx}-{uuid4()}")
                issue_text = issue.issue
                urgency = issue.urgency.value
                category = issue.category.value
                action = issue.recommended_action
                recipients = issue.recipients
                source = issue.source.value
                timestamp = _format_ts(issue.created_at)
                updated_timestamp = _format_ts(issue.updated_at)
                location = (
                    f"{issue.property_name}"
                    f" · {issue.building}"
                    f" · Unit {issue.unit_number}"
                    f" · {issue.area or 'Unknown'}"
                )
                image_path = issue.image_path

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
                        st.markdown(
                            f"**Status:** {_status_badge_html(issue.status.value)}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**Issue:** {issue_text}")
                        st.markdown(f"**Urgency:** {urgency}")
                        st.markdown(f"**Category:** {category}")
                        st.markdown(f"**Recommended Action:** {action}")
                        st.markdown(
                            f"**Recipients:** {', '.join(recipients) if recipients else 'Unassigned'}"
                        )
                        st.markdown(f"**Source:** {source}")
                        st.markdown(f"**Timestamp:** {timestamp}")
                        st.markdown(f"**Updated:** {updated_timestamp}")
                        st.markdown(f"**Location:** {location}")
                        st.markdown(f"**Comments:** {len(issue.comments)}")
                        if issue.image_filename:
                            st.markdown(f"**Image Filename:** {issue.image_filename}")

                        status_options = [status.value for status in Status]
                        current_status = issue.status.value
                        status_index = (
                            status_options.index(current_status)
                            if current_status in status_options
                            else 0
                        )
                        selected_status = st.selectbox(
                            "Update Status",
                            options=status_options,
                            index=status_index,
                            key=f"status_select_{issue_id}",
                        )
                        if selected_status != current_status:
                            try:
                                workflow.update_issue_status(issue_id, Status(selected_status))
                            except UserVisibleError as exc:
                                st.error(exc.user_message)
                            except Exception:  # noqa: BLE001
                                logger.exception("Failed to update issue status")
                                st.error("Could not update issue status right now.")
                            else:
                                st.success("Status updated.")
                                st.rerun()

                        st.caption("Internal team comments")
                        with st.form(key=f"comment_form_{issue_id}", clear_on_submit=True):
                            author_col, role_col = st.columns([2, 2], gap="small")
                            with author_col:
                                comment_author = st.text_input(
                                    "Author Name",
                                    key=f"comment_author_{issue_id}",
                                    placeholder="Name",
                                )
                            with role_col:
                                comment_role = st.selectbox(
                                    "Author Role",
                                    options=list(COMMENT_AUTHOR_ROLES),
                                    key=f"comment_role_{issue_id}",
                                )
                            comment_message = st.text_area(
                                "Comment Message",
                                key=f"comment_message_{issue_id}",
                                height=90,
                                max_chars=800,
                                placeholder="Add an internal coordination note...",
                            )
                            submitted = st.form_submit_button("Post Comment")
                            if submitted:
                                if not comment_message.strip():
                                    st.warning("Please enter a comment message before posting.")
                                else:
                                    try:
                                        workflow.add_issue_comment(
                                            issue_id=issue_id,
                                            author_name=comment_author,
                                            author_role=comment_role,
                                            message=comment_message,
                                        )
                                    except UserVisibleError as exc:
                                        st.error(exc.user_message)
                                    except Exception:  # noqa: BLE001
                                        logger.exception("Failed to post issue comment")
                                        st.error("Could not post comment right now.")
                                    else:
                                        st.success("Comment posted.")
                                        st.rerun()

                        if issue.comments:
                            st.markdown("**Comment History**")
                            ordered_comments = sorted(
                                issue.comments,
                                key=lambda comment: _date_sort_value(comment.created_at),
                            )
                            for comment in ordered_comments:
                                st.markdown(
                                    (
                                        f"- **{comment.author_name}** ({comment.author_role}) "
                                        f"@ {_format_ts(comment.created_at)}  \n"
                                        f"  {comment.message}"
                                    )
                                )
                st.divider()
