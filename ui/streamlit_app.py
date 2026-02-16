from __future__ import annotations

from datetime import datetime

import streamlit as st

from ai.formatter import OpenAIIssueFormatter
from config.settings import Settings, get_settings
from core.errors import UserVisibleError
from core.logging_utils import configure_logging, get_logger
from core.workflows import IssueWorkflowService
from services.router import IssueRouter
from storage.repository import JsonlIssueRepository


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
    )
    return settings, workflow


def _format_ts(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone().strftime("%b %d, %Y %I:%M %p")
    except Exception:  # noqa: BLE001
        return value


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
        st.caption(f"Working on {building}, Unit {unit_number}")
        st.caption(f"Max upload size: {settings.max_upload_mb} MB")

    quick_snap_tab, unit_notes_tab, community_feed_tab = st.tabs(
        ["Quick Snap", "Unit Notes", "Community Feed"]
    )

    with quick_snap_tab:
        st.subheader("Photo Upload")
        photo = st.file_uploader(
            "Upload unit photo",
            type=["jpg", "jpeg", "png", "webp"],
            key="quick_snap_upload",
        )
        quick_caption = st.text_input(
            "Photo note (optional)",
            placeholder="Example: Burn mark near outlet behind fridge",
        )

        oversized_upload = bool(photo and photo.size > settings.max_upload_bytes)
        if oversized_upload:
            st.error(
                f"Photo is larger than {settings.max_upload_mb} MB. "
                "Please upload a smaller file."
            )

        if photo and not oversized_upload:
            st.image(photo, use_container_width=True)

        if st.button("Save Snapshot", key="save_snapshot"):
            if not photo:
                st.warning("Add a photo before saving a snapshot.")
            elif oversized_upload:
                st.warning("Upload a smaller photo before saving.")
            else:
                try:
                    workflow.save_snapshot(
                        building=building,
                        unit_number=unit_number,
                        file_name=photo.name,
                        note=quick_caption,
                    )
                except UserVisibleError as exc:
                    logger.warning(
                        "Snapshot save failed",
                        extra={"context": {"detail": exc.detail}},
                    )
                    st.error(exc.user_message)
                except Exception:  # noqa: BLE001
                    logger.exception("Unexpected snapshot save failure")
                    st.error("Unexpected error while saving snapshot. Please retry.")
                else:
                    st.success("Snapshot saved and routed to community feed.")

    with unit_notes_tab:
        st.subheader("Unit Notes")
        raw_observations = st.text_area(
            "Raw Observations",
            placeholder=(
                "Ex: 2B dishwasher leaking from lower right corner, "
                "possible gasket issue, floor wet near sink."
            ),
            key="raw_observations",
        )

        if st.button("Format for Team", key="format_for_team"):
            with st.spinner("Formatting report..."):
                try:
                    report = workflow.submit_unit_notes(
                        building=building,
                        unit_number=unit_number,
                        raw_observations=raw_observations,
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
                    st.session_state["last_report"] = report.model_dump(mode="json")
                    st.success("Professional issue report generated.")

        if st.session_state.get("last_report"):
            report = st.session_state["last_report"]
            st.markdown("### Structured Report")
            st.markdown(f"**Issue**\n\n{report['issue']}")
            st.markdown(f"**Urgency**\n\n{report['urgency']}")
            st.markdown(f"**Recommended Action**\n\n{report['recommended_action']}")
            st.markdown(f"**Routing Recipients**\n\n{', '.join(report['recipients'])}")

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
            st.info("No entries yet. Add a snapshot or format notes to populate this feed.")
        else:
            for entry in activity:
                entry_type = entry.get("entry_type")
                payload = entry.get("payload", {})
                timestamp = _format_ts(entry.get("created_at", ""))

                st.markdown('<div class="feed-card">', unsafe_allow_html=True)
                st.markdown(
                    (
                        f"<div class='feed-meta'>{payload.get('building', '-')}"
                        f" · Unit {payload.get('unit_number', '-')}"
                        f" · {timestamp}</div>"
                    ),
                    unsafe_allow_html=True,
                )
                if entry_type == "issue_report":
                    st.markdown(f"**Issue:** {payload.get('issue', '')}")
                    st.markdown(f"**Urgency:** {payload.get('urgency', '')}")
                    st.markdown(f"**Category:** {payload.get('category', '')}")
                    st.markdown(
                        f"**Recommended Action:** {payload.get('recommended_action', '')}"
                    )
                    recipients = payload.get("recipients", [])
                    if recipients:
                        st.markdown(f"**Recipients:** {', '.join(recipients)}")
                else:
                    st.markdown(f"**Snapshot:** {payload.get('file_name', '')}")
                    if payload.get("note"):
                        st.markdown(f"**Note:** {payload['note']}")
                st.markdown("</div>", unsafe_allow_html=True)
