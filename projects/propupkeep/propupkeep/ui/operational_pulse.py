from __future__ import annotations

import json
from datetime import date, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

from propupkeep.models.issue import IssueSource, Status


def _normalize_source_value(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    source_map = {
        "quick_snap": IssueSource.QUICK_SNAP.value,
        "quick snap": IssueSource.QUICK_SNAP.value,
        "photo": IssueSource.QUICK_SNAP.value,
        "unit_notes": IssueSource.UNIT_NOTES.value,
        "unit notes": IssueSource.UNIT_NOTES.value,
        "note": IssueSource.UNIT_NOTES.value,
        "quick_voice": IssueSource.QUICK_VOICE.value,
        "quick voice": IssueSource.QUICK_VOICE.value,
        "voice": IssueSource.QUICK_VOICE.value,
        "unknown": IssueSource.UNKNOWN.value,
        "": IssueSource.UNKNOWN.value,
    }
    return source_map.get(normalized, IssueSource.UNKNOWN.value)


def _source_label(value: str | None) -> str:
    labels = {
        IssueSource.QUICK_SNAP.value: "Quick Snap",
        IssueSource.UNIT_NOTES.value: "Unit Notes",
        IssueSource.QUICK_VOICE.value: "Quick Voice",
        IssueSource.UNKNOWN.value: "Unknown",
    }
    return labels.get(_normalize_source_value(value), "Unknown")


def _normalize_status(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    return normalized or Status.OPEN.value


def _status_display(status_value: str) -> str:
    status_map = {
        Status.OPEN.value: "Open",
        Status.ACKNOWLEDGED.value: "Open",
        Status.IN_PROGRESS.value: "In Progress",
        Status.MONITORING.value: "Open",
        Status.RESOLVED.value: "Closed",
    }
    return status_map.get(status_value, "Open")


def _build_location(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for field_name in ("property_name", "building"):
        field_value = str(payload.get(field_name) or "").strip()
        if field_value:
            parts.append(field_value)

    unit_value = str(payload.get("unit_number") or "").strip()
    if unit_value:
        parts.append(f"Unit {unit_value}")

    area_value = str(payload.get("area") or "").strip()
    if area_value:
        parts.append(area_value)

    return " · ".join(parts)


def _build_summary(payload: dict[str, Any]) -> str:
    for field_name in ("issue", "reported_observation", "note_text", "raw_observations"):
        value = str(payload.get(field_name) or "").strip()
        if value:
            return value[:180]
    return "No summary available"


def _record_to_json(record: Any) -> str:
    if isinstance(record, dict):
        payload = record
    elif hasattr(record, "model_dump"):
        payload = record.model_dump(mode="json")
    else:
        payload = {}
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)


@st.cache_data(show_spinner=False)
def _normalize_records_to_df(records_json: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for raw_record in records_json:
        try:
            payload = json.loads(raw_record)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        created_at_dt = pd.to_datetime(payload.get("created_at"), utc=True, errors="coerce")
        status_value = _normalize_status(payload.get("status"))
        source_value = _normalize_source_value(payload.get("source"))
        category_value = str(payload.get("category") or "").strip() or "Unknown"
        location_value = _build_location(payload)

        rows.append(
            {
                "created_at_dt": created_at_dt,
                "created_date": created_at_dt.date() if not pd.isna(created_at_dt) else None,
                "created_at_display": (
                    created_at_dt.tz_convert(None).strftime("%Y-%m-%d %H:%M")
                    if not pd.isna(created_at_dt)
                    else ""
                ),
                "source_value": source_value,
                "source_label": _source_label(source_value),
                "status_value": status_value,
                "status_display": _status_display(status_value),
                "category": category_value,
                "location": location_value,
                "summary": _build_summary(payload),
                "is_open": status_value != Status.RESOLVED.value,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "created_at_dt",
                "created_date",
                "created_at_display",
                "source_value",
                "source_label",
                "status_value",
                "status_display",
                "category",
                "location",
                "summary",
                "is_open",
            ]
        )
    return pd.DataFrame(rows)


def _coerce_date_range(
    value: date | tuple[date, date] | list[date],
    default_start: date,
    default_end: date,
) -> tuple[date, date]:
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], value[1]
    if isinstance(value, list) and len(value) == 2:
        return value[0], value[1]
    if isinstance(value, date):
        return value, value
    return default_start, default_end


def render_operational_pulse(records: list[Any]) -> None:
    st.subheader("Operational Pulse")
    st.caption("Executive visibility snapshot built from current issue records.")

    records_json = tuple(_record_to_json(record) for record in records)
    pulse_df = _normalize_records_to_df(records_json)

    if pulse_df.empty:
        st.info("No records available yet. Submit items to see operational trends.")
        return

    today = pd.Timestamp.now(tz=timezone.utc).date()
    default_start = today - timedelta(days=30)
    default_end = today

    filter_col_1, filter_col_2, filter_col_3 = st.columns([2, 1, 1], gap="small")
    with filter_col_1:
        selected_range = st.date_input(
            "Date range",
            value=(default_start, default_end),
            max_value=default_end,
            key="pulse_date_range",
        )
    with filter_col_2:
        selected_status = st.selectbox(
            "Status",
            options=["All", "Open", "In Progress", "Closed"],
            index=0,
            key="pulse_status_filter",
        )
    with filter_col_3:
        selected_source = st.selectbox(
            "Source / Origin",
            options=["All", "Quick Snap", "Unit Notes", "Quick Voice"],
            index=0,
            key="pulse_source_filter",
        )

    filter_col_4, filter_col_5 = st.columns([2, 2], gap="small")
    available_categories = sorted(
        {
            str(value).strip()
            for value in pulse_df["category"].tolist()
            if str(value).strip() and str(value).strip().lower() != "unknown"
        }
    )
    selected_categories: list[str] = []
    with filter_col_4:
        if available_categories:
            selected_categories = st.multiselect(
                "Category",
                options=available_categories,
                default=[],
                key="pulse_category_filter",
                help="Leave empty to include all categories.",
            )

    available_locations = sorted(
        {str(value).strip() for value in pulse_df["location"].tolist() if str(value).strip()}
    )
    selected_location = "All"
    with filter_col_5:
        if available_locations:
            selected_location = st.selectbox(
                "Location / Building / Unit",
                options=["All", *available_locations],
                index=0,
                key="pulse_location_filter",
            )

    start_date, end_date = _coerce_date_range(selected_range, default_start, default_end)
    filtered_df = pulse_df.copy()
    filtered_df = filtered_df[
        filtered_df["created_date"].apply(lambda value: bool(value and start_date <= value <= end_date))
    ]

    if selected_status != "All":
        filtered_df = filtered_df[filtered_df["status_display"] == selected_status]

    if selected_source != "All":
        filtered_df = filtered_df[filtered_df["source_label"] == selected_source]

    if selected_categories:
        filtered_df = filtered_df[filtered_df["category"].isin(selected_categories)]

    if selected_location != "All":
        filtered_df = filtered_df[filtered_df["location"] == selected_location]

    now_ts = pd.Timestamp.now(tz=timezone.utc)
    seven_days_ago = now_ts - pd.Timedelta(days=7)
    open_mask = filtered_df["is_open"] == True  # noqa: E712
    new_last_7_mask = filtered_df["created_at_dt"] >= seven_days_ago
    overdue_mask = open_mask & (filtered_df["created_at_dt"] < seven_days_ago)

    open_items = int(open_mask.sum())
    new_last_7_days = int(new_last_7_mask.sum())
    overdue_items = int(overdue_mask.sum())
    open_age_days = (
        (now_ts - filtered_df.loc[open_mask, "created_at_dt"]).dt.total_seconds().div(86400).dropna()
    )
    avg_open_age_days = float(open_age_days.mean()) if not open_age_days.empty else 0.0

    metric_col_1, metric_col_2, metric_col_3, metric_col_4 = st.columns(4)
    metric_col_1.metric("Open items", open_items)
    metric_col_2.metric("New last 7 days", new_last_7_days)
    metric_col_3.metric("Overdue", overdue_items)
    metric_col_4.metric("Avg age (open, days)", f"{avg_open_age_days:.1f}")

    if filtered_df.empty:
        st.info("No records match the selected filters.")
        return

    chart_col_1, chart_col_2 = st.columns(2, gap="medium")

    with chart_col_1:
        open_by_category = (
            filtered_df[
                filtered_df["is_open"] & (filtered_df["category"].astype(str).str.lower() != "unknown")
            ]
            .groupby("category")
            .size()
            .sort_values(ascending=False)
            .rename("count")
        )
        if not open_by_category.empty:
            st.markdown("**Open items by Category**")
            st.bar_chart(open_by_category)

    with chart_col_2:
        items_by_source = (
            filtered_df.groupby("source_label")
            .size()
            .sort_values(ascending=False)
            .rename("count")
        )
        st.markdown("**Items by Source / Origin**")
        st.bar_chart(items_by_source)

    weekly_new_items = (
        filtered_df.dropna(subset=["created_at_dt"])
        .set_index("created_at_dt")
        .resample("W-MON")
        .size()
        .rename("new_items")
        .to_frame()
    )
    if not weekly_new_items.empty:
        weekly_new_items.index = weekly_new_items.index.tz_convert(None)
        st.markdown("**New items over time (weekly)**")
        st.line_chart(weekly_new_items)

    recent_items_df = filtered_df.sort_values("created_at_dt", ascending=False).copy()
    recent_items_table = recent_items_df[
        [
            "created_at_display",
            "source_label",
            "status_display",
            "category",
            "location",
            "summary",
        ]
    ].rename(
        columns={
            "created_at_display": "created_at",
            "source_label": "source",
            "status_display": "status",
            "category": "category",
            "location": "location",
            "summary": "summary",
        }
    )
    st.markdown("**Recent Items**")
    st.dataframe(recent_items_table, use_container_width=True, hide_index=True)
