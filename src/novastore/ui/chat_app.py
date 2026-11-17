"""NovaStore customer chat UI (Streamlit, Sprint 11).

Thin shell over the API: it renders messages and calls POST /api/chat.
All intelligence lives in the agent - the same one WhatsApp will use later.

Run:  streamlit run src/novastore/ui/chat_app.py
Requires the FastAPI backend running on UI_API_URL (default 127.0.0.1:8000).
"""

from __future__ import annotations

import os
import uuid

import httpx
import streamlit as st

API_URL = os.getenv("UI_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="NovaStore Chat", page_icon="", layout="centered")
st.title("NovaStore - Customer Chat")
st.caption("Fictional electronics store demo. Every answer comes from store data - never invented.")

# ---------------------------------------------------------------------------
# Sidebar: identity + conversation controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Session")

    customers = []
    backend_ok = True
    try:
        response = httpx.get(f"{API_URL}/api/customers", timeout=5)
        response.raise_for_status()
        customers = response.json()
    except Exception:
        backend_ok = False

    if not backend_ok:
        st.error(
            f"Cannot reach the API at {API_URL}. Start it first:\n\n"
            "uvicorn novastore.api.app:app --reload --port 8000"
        )
        chosen = None
    else:
        labels = {c["id"]: f"{c['name']} ({c['id']}, {c['type']})" for c in customers}
        chosen = st.selectbox("You are:", list(labels.keys()), format_func=lambda k: labels[k])

        if st.button("Start new conversation"):
            st.session_state.session_id = f"sess_{uuid.uuid4().hex[:10]}"
            st.session_state.messages = []
            st.rerun()

        st.caption(
            "Tip: try 'Where is order 5482?', 'Is iPhone 15 available?', "
            "'Can I return opened headphones?', 'I want 30 Dell laptops for my company', "
            "or 'I want to talk to a person'."
        )

# ---------------------------------------------------------------------------
# Chat state
# ---------------------------------------------------------------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = f"sess_{uuid.uuid4().hex[:10]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------------------------------------------------------------------
# Render history
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        meta = msg.get("meta") or {}
        if msg["role"] == "assistant" and meta:
            chips = f"intent: {meta.get('intent', 'unknown')} | confidence: {meta.get('confidence', 0):.0%}"
            if meta.get("handoff"):
                chips += " | handed to a human"
            if meta.get("ticket_id"):
                chips += f" | ticket #{meta['ticket_id']}"
            if meta.get("lead_id"):
                chips += f" | lead #{meta['lead_id']}"
            st.caption(chips)
            citations = meta.get("citations") or []
            if citations:
                lines = [f"- {c['doc']}" + (f" - {c['title']}" if c.get("title") else "") for c in citations]
                with st.expander("Sources"):
                    st.markdown("\n".join(lines))

# ---------------------------------------------------------------------------
# Input + API call
# ---------------------------------------------------------------------------
if prompt := st.chat_input("Type your message...", disabled=not backend_ok):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("NovaStore agent is thinking..."):
            try:
                response = httpx.post(
                    f"{API_URL}/api/chat",
                    json={
                        "customer_id": chosen,
                        "message": prompt,
                        "session_id": st.session_state.session_id,
                    },
                    timeout=60,
                )
                response.raise_for_status()
                reply = response.json()
            except Exception as exc:
                reply = {"reply": f"Connection problem: {exc}", "intent": "error", "confidence": 0.0}

        st.write(reply.get("reply", ""))
        meta = {
            "intent": reply.get("intent"),
            "confidence": reply.get("confidence", 0.0),
            "handoff": reply.get("handoff", False),
            "ticket_id": reply.get("ticket_id"),
            "lead_id": reply.get("lead_id"),
            "citations": reply.get("citations", []),
        }
        chips = f"intent: {meta['intent']} | confidence: {meta['confidence']:.0%}"
        if meta["handoff"]:
            chips += " | handed to a human"
        if meta["ticket_id"]:
            chips += f" | ticket #{meta['ticket_id']}"
        if meta["lead_id"]:
            chips += f" | lead #{meta['lead_id']}"
        st.caption(chips)
        if meta["citations"]:
            lines = [f"- {c['doc']}" + (f" - {c['title']}" if c.get("title") else "") for c in meta["citations"]]
            with st.expander("Sources"):
                st.markdown("\n".join(lines))

    st.session_state.messages.append({"role": "assistant", "content": reply.get("reply", ""), "meta": meta})
