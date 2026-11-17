"""NovaStore admin dashboard (Streamlit, Sprint 11-13).

Read-only views over the same SQLite database the agent writes to:
overview metrics, conversation transcripts, orders, leads, tickets and
the latest eval scores (from scripts/run_evals.py).

Run:  streamlit run src/novastore/ui/admin_app.py
"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("UI_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="NovaStore Admin", page_icon="", layout="wide")
st.title("NovaStore - Admin Dashboard")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def fetch(path: str, default):
    try:
        response = httpx.get(f"{API_URL}{path}", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        st.error(
            f"Cannot reach the API at {API_URL} ({exc}). Start it first:\n\n"
            "uvicorn novastore.api.app:app --reload --port 8000"
        )
        return default


def to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


with st.sidebar:
    st.header("View")
    section = st.radio("Section", ["Overview", "Conversations", "Orders", "Leads", "Tickets", "Evals"])
    if st.button("Refresh"):
        st.rerun()

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
if section == "Overview":
    data = fetch("/api/admin/overview", {})
    if data:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Customers", data.get("customers", 0))
        col2.metric("Orders", data.get("orders", 0))
        col3.metric("Open tickets", data.get("open_tickets", 0))
        col4.metric("Leads", data.get("leads", 0))
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Chat sessions", data.get("sessions", 0))
        col2.metric("Messages (24h)", data.get("messages_last_24h", 0))
        col3.metric("Products", data.get("products", 0))
        col4.metric(" ", " ")

        by_status = data.get("orders_by_status") or {}
        if by_status:
            st.subheader("Orders by status")
            status_df = pd.DataFrame(
                {"status": list(by_status.keys()), "orders": list(by_status.values())}
            ).set_index("status")
            st.bar_chart(status_df)

# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
elif section == "Conversations":
    sessions = fetch("/api/admin/conversations", [])
    if sessions:
        labels = {
            s["session_id"]: f"{s['session_id']} - {s.get('first_message', '')[:40]}... ({s['turns']} turns)"
            for s in sessions
        }
        chosen = st.selectbox("Conversation", list(labels.keys()), format_func=lambda k: labels[k])
        transcript = fetch(f"/api/admin/conversations/{chosen}", [])
        if transcript:
            for row in transcript:
                who = "customer" if row["role"] == "customer" else "agent"
                with st.chat_message(who):
                    st.write(row["content"])
                    if row.get("intent"):
                        st.caption(
                            f"{row['created_at']} | intent: {row['intent']}"
                            + (f" | confidence: {row['confidence']:.0%}" if row.get("confidence") else "")
                        )

# ---------------------------------------------------------------------------
# Orders / Leads / Tickets
# ---------------------------------------------------------------------------
elif section == "Orders":
    orders = fetch("/api/admin/orders", [])
    df = to_df(orders)
    if not df.empty:
        statuses = ["all"] + sorted(df["status"].unique().tolist())
        pick = st.selectbox("Filter by status", statuses)
        if pick != "all":
            df = df[df["status"] == pick]
    st.dataframe(df, use_container_width=True, hide_index=True)

elif section == "Leads":
    st.dataframe(to_df(fetch("/api/admin/leads", [])), use_container_width=True, hide_index=True)

elif section == "Tickets":
    tickets = fetch("/api/admin/tickets", [])
    df = to_df(tickets)
    if not df.empty:
        statuses = ["all"] + sorted(df["status"].unique().tolist())
        pick = st.selectbox("Filter by status", statuses)
        if pick != "all":
            df = df[df["status"] == pick]
    st.dataframe(df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Evals
# ---------------------------------------------------------------------------
elif section == "Evals":
    data = fetch("/api/admin/evals", {})
    if not data.get("available", False):
        st.info("No eval results yet. Run:  python scripts/run_evals.py")
    else:
        classifier = data.get("classifier") or {}
        behavior = data.get("behavior") or {}
        col1, col2, col3 = st.columns(3)
        col1.metric("Classifier accuracy", f"{classifier.get('accuracy', 0):.0%}")
        col2.metric("Behavior tests passed", f"{behavior.get('passed', 0)}/{behavior.get('total', 0)}")
        col3.metric("Model", data.get("model", "?"))

        per_intent = classifier.get("per_intent") or {}
        if per_intent:
            st.subheader("Per-intent accuracy")
            intent_df = pd.DataFrame(
                [{"intent": k, "accuracy": v.get("accuracy", 0.0)} for k, v in per_intent.items()]
            ).set_index("intent")
            st.bar_chart(intent_df)

        failures = (classifier.get("failures") or []) + (behavior.get("failures") or [])
        if failures:
            with st.expander(f"Failures ({len(failures)})"):
                st.json(failures)
