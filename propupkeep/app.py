import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st

from upkeep_mvp import TEAM_BRIEF_SYSTEM_PROMPT


st.set_page_config(
    page_title="PropUpkeep Mobile",
    page_icon=":building_construction:",
    layout="centered",
)


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


def _get_api_key() -> str:
    return st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))


def _get_model_name() -> str:
    return st.secrets.get("OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))


def _extract_json_payload(content: str) -> dict:
    """Parse model output and recover the first JSON object."""
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)

    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        raise ValueError("No JSON object was found in the model response.")
    return json.loads(match.group(0))


def format_observations_with_llm(raw_observations: str, building: str, unit_number: str) -> dict:
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it in environment variables or Streamlit secrets."
        )

    system_prompt = (
        f"{TEAM_BRIEF_SYSTEM_PROMPT}\n\n"
        "You must return ONLY JSON with these keys: "
        '"issue" (string), "urgency" (High|Medium|Low), '
        '"recommended_action" (string).'
    )
    user_prompt = (
        "Convert the following leasing consultant notes into a concise team-ready report.\n\n"
        f"Building: {building}\n"
        f"Unit: {unit_number}\n"
        f"Raw Observations: {raw_observations}"
    )

    payload = {
        "model": _get_model_name(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }

    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=45) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed ({exc.code}): {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error during LLM request: {exc.reason}") from exc

    data = json.loads(body)
    content = data["choices"][0]["message"]["content"]
    brief = _extract_json_payload(content)

    issue = str(brief.get("issue", "")).strip()
    urgency = str(brief.get("urgency", "")).strip().title()
    recommended_action = str(brief.get("recommended_action", "")).strip()

    if urgency not in {"High", "Medium", "Low"}:
        raise ValueError("Model returned invalid urgency rating.")
    if not issue or not recommended_action:
        raise ValueError("Model returned an incomplete report.")

    return {
        "issue": issue,
        "urgency": urgency,
        "recommended_action": recommended_action,
    }


if "community_feed" not in st.session_state:
    st.session_state.community_feed = []


st.title("PropUpkeep")
st.caption("Mobile-first intake for leasing and maintenance coordination")

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

    if photo:
        st.image(photo, use_container_width=True)

    if st.button("Save Snapshot", key="save_snapshot"):
        if not photo:
            st.warning("Add a photo before saving a snapshot.")
        else:
            st.session_state.community_feed.append(
                {
                    "type": "snapshot",
                    "building": building,
                    "unit": unit_number,
                    "file_name": photo.name,
                    "note": quick_caption.strip(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            st.success("Snapshot added to Community Feed.")


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
        if not raw_observations.strip():
            st.warning("Please enter observations before formatting.")
        else:
            with st.spinner("Formatting report..."):
                try:
                    report = format_observations_with_llm(
                        raw_observations=raw_observations,
                        building=building,
                        unit_number=unit_number,
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not format report: {exc}")
                else:
                    st.success("Professional report generated.")
                    st.markdown("### Structured Report")
                    st.markdown(f"**Issue**\n\n{report['issue']}")
                    st.markdown(f"**Urgency**\n\n{report['urgency']}")
                    st.markdown(
                        f"**Recommended Action**\n\n{report['recommended_action']}"
                    )

                    st.session_state.community_feed.append(
                        {
                            "type": "report",
                            "building": building,
                            "unit": unit_number,
                            "raw_observations": raw_observations.strip(),
                            "report": report,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )


with community_feed_tab:
    st.subheader("Reviewing Logs")
    if not st.session_state.community_feed:
        st.info("No entries yet. Add a snapshot or format notes to populate this feed.")
    else:
        for entry in reversed(st.session_state.community_feed):
            pretty_time = (
                datetime.fromisoformat(entry["timestamp"])
                .astimezone()
                .strftime("%b %d, %Y %I:%M %p")
            )
            if entry["type"] == "report":
                st.markdown('<div class="feed-card">', unsafe_allow_html=True)
                st.markdown(
                    f"<div class='feed-meta'>{entry['building']} · Unit {entry['unit']} · {pretty_time}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Issue:** {entry['report']['issue']}")
                st.markdown(f"**Urgency:** {entry['report']['urgency']}")
                st.markdown(
                    f"**Recommended Action:** {entry['report']['recommended_action']}"
                )
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.markdown('<div class="feed-card">', unsafe_allow_html=True)
                st.markdown(
                    f"<div class='feed-meta'>{entry['building']} · Unit {entry['unit']} · {pretty_time}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Snapshot:** {entry['file_name']}")
                if entry["note"]:
                    st.markdown(f"**Note:** {entry['note']}")
                st.markdown("</div>", unsafe_allow_html=True)
