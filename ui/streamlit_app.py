from __future__ import annotations

import hashlib
from datetime import datetime

import streamlit as st

from ai.formatter import OpenAIIssueFormatter
from config.settings import Settings, get_settings
from core.errors import UserVisibleError
from core.logging_utils import configure_logging, get_logger
from core.workflows import IssueWorkflowService
from services.router import IssueRouter
from services.transcription import TranscriptionError, transcribe_audio
from storage.repository import JsonlIssueRepository

try:
    from audio_recorder_streamlit import audio_recorder

    AUDIO_RECORDER_AVAILABLE = True
except Exception:  # noqa: BLE001
    audio_recorder = None
    AUDIO_RECORDER_AVAILABLE = False


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


def _render_structured_report(report: dict, heading: str = "Structured Report") -> None:
    st.markdown(f"### {heading}")
    st.markdown(f"**Issue**\n\n{report.get('issue', '')}")
    st.markdown(f"**Urgency**\n\n{report.get('urgency', '')}")
    st.markdown(f"**Category**\n\n{report.get('category', '')}")
    st.markdown(f"**Recommended Action**\n\n{report.get('recommended_action', '')}")
    recipients = report.get("recipients", [])
    if recipients:
        st.markdown(f"**Routing Recipients**\n\n{', '.join(recipients)}")


def _ensure_voice_state() -> None:
    defaults: dict[str, object] = {
        "voice_audio_bytes": b"",
        "voice_audio_hash": "",
        "voice_is_transcribing": False,
        "voice_transcript": "",
        "voice_context": "",
        "voice_formatted_output": None,
        "voice_audio_mime": "audio/wav",
        "voice_transcription_error": "",
        "voice_recorder_nonce": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_voice_state() -> None:
    st.session_state["voice_audio_bytes"] = b""
    st.session_state["voice_audio_hash"] = ""
    st.session_state["voice_is_transcribing"] = False
    st.session_state["voice_transcript"] = ""
    st.session_state["voice_context"] = ""
    st.session_state["voice_formatted_output"] = None
    st.session_state["voice_audio_mime"] = "audio/wav"
    st.session_state["voice_transcription_error"] = ""
    st.session_state["voice_recorder_nonce"] = int(st.session_state.get("voice_recorder_nonce", 0)) + 1


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

    quick_snap_tab, quick_voice_tab, unit_notes_tab, community_feed_tab = st.tabs(
        ["Quick Snap", "Quick Voice", "Unit Notes", "Community Feed"]
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

    with quick_voice_tab:
        _ensure_voice_state()
        st.subheader("Quick Voice")
        st.caption("Record a voice note and we'll convert it into a structured work item.")

        recorded_audio_bytes = b""
        recorded_audio_mime = "audio/wav"
        recorder_key = f"voice_recorder_{st.session_state['voice_recorder_nonce']}"

        if AUDIO_RECORDER_AVAILABLE and audio_recorder is not None:
            recorded_audio_bytes = audio_recorder(
                text="Tap to record",
                recording_color="#e45757",
                neutral_color="#6c757d",
                icon_name="microphone",
                icon_size="2x",
                key=recorder_key,
            )
            recorded_audio_mime = "audio/wav"
        else:
            st.warning("Voice recorder component unavailable; upload an audio clip as fallback.")
            uploaded_audio = st.file_uploader(
                "Upload voice clip",
                type=["wav", "mp3", "m4a", "ogg", "webm"],
                key=f"{recorder_key}_fallback_upload",
            )
            if uploaded_audio:
                recorded_audio_bytes = uploaded_audio.getvalue()
                recorded_audio_mime = uploaded_audio.type or "audio/wav"

        if recorded_audio_bytes:
            st.session_state["voice_audio_bytes"] = recorded_audio_bytes
            st.session_state["voice_audio_mime"] = recorded_audio_mime

        stored_audio = st.session_state.get("voice_audio_bytes", b"")
        if stored_audio:
            st.audio(stored_audio, format=st.session_state.get("voice_audio_mime", "audio/wav"))
            audio_hash = hashlib.sha256(stored_audio).hexdigest()
            if (
                audio_hash != st.session_state.get("voice_audio_hash")
                and not st.session_state.get("voice_is_transcribing", False)
            ):
                st.session_state["voice_is_transcribing"] = True
                try:
                    with st.spinner("Transcribing..."):
                        transcript = transcribe_audio(
                            audio_bytes=stored_audio,
                            mime_type=str(st.session_state.get("voice_audio_mime", "audio/wav")),
                        )
                except TranscriptionError as exc:
                    logger.warning(
                        "Voice transcription failed",
                        extra={"context": {"detail": str(exc)}},
                    )
                    st.session_state["voice_transcript"] = ""
                    st.session_state["voice_transcription_error"] = (
                        "Couldn’t transcribe that clip. Please try again."
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Unexpected voice transcription failure")
                    st.session_state["voice_transcript"] = ""
                    st.session_state["voice_transcription_error"] = (
                        "Couldn’t transcribe that clip. Please try again."
                    )
                else:
                    st.session_state["voice_transcript"] = transcript
                    st.session_state["voice_transcription_error"] = ""
                finally:
                    st.session_state["voice_audio_hash"] = audio_hash
                    st.session_state["voice_is_transcribing"] = False
                    st.rerun()
        else:
            st.info("Record a voice note to begin.")

        if st.session_state.get("voice_transcription_error"):
            st.warning(st.session_state["voice_transcription_error"])

        st.text_area(
            "Transcription (editable)",
            key="voice_transcript",
            height=160,
            placeholder="Your transcript will appear here.",
        )
        st.text_input(
            "Context (optional)",
            key="voice_context",
            placeholder="Unit #, location, priority, etc.",
        )

        action_col, clear_col = st.columns([2, 1], gap="small")
        with action_col:
            if st.button("Format for Team", key="voice_format_for_team"):
                transcript_text = str(st.session_state.get("voice_transcript", "")).strip()
                context_text = str(st.session_state.get("voice_context", "")).strip()
                if not transcript_text:
                    st.warning("Please record a voice note before formatting for the team.")
                else:
                    formatted_input = (
                        f"{context_text}\n\n{transcript_text}" if context_text else transcript_text
                    )
                    with st.spinner("Formatting report..."):
                        try:
                            report = workflow.submit_unit_notes(
                                building=building,
                                unit_number=unit_number,
                                raw_observations=formatted_input,
                            )
                        except UserVisibleError as exc:
                            logger.warning(
                                "Voice formatting failed",
                                extra={"context": {"detail": exc.detail}},
                            )
                            st.error(exc.user_message)
                        except Exception:  # noqa: BLE001
                            logger.exception("Unexpected voice formatting failure")
                            st.error("Unexpected error while formatting voice note. Please retry.")
                        else:
                            st.session_state["voice_formatted_output"] = report.model_dump(mode="json")
                            st.success("Structured work item generated from voice note.")
        with clear_col:
            if st.button("Re-record", key="voice_rerecord"):
                _clear_voice_state()
                st.rerun()

        if st.session_state.get("voice_formatted_output"):
            _render_structured_report(
                st.session_state["voice_formatted_output"],
                heading="Structured Work Item",
            )

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
            _render_structured_report(st.session_state["last_report"])

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
