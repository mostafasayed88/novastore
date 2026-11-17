"""HTTP routes (Sprint 11) + WhatsApp stub (Sprint 13, prepared).

Every channel (Streamlit chat, CLI, later WhatsApp) uses the SAME endpoint:
POST /api/chat. That is the whole point of having an agent core - channels
are thin shells around it.

Admin endpoints read the database directly (read-only) for the dashboard.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from novastore.config import PROJECT_ROOT, Settings
from novastore.db.database import connect_ctx
from novastore.db import repository as repo
from novastore.logging_setup import get_logger
from novastore.schemas.agent import AgentReply, ChatRequest

logger = get_logger(__name__)
router = APIRouter()


def get_settings_from(request: Request) -> Settings:
    return request.app.state.settings


def get_agent(request: Request):
    return request.app.state.agent


# ---------------------------------------------------------------------------
# chat (the one endpoint every channel uses)
# ---------------------------------------------------------------------------
@router.post("/api/chat", response_model=AgentReply)
def chat(payload: ChatRequest, agent=Depends(get_agent)) -> AgentReply:
    session_id = payload.session_id or f"sess_{payload.customer_id}"
    try:
        return agent.run(session_id, payload.customer_id, payload.message)
    except Exception:
        logger.exception("Chat processing failed")
        raise HTTPException(status_code=500, detail="Agent error - see server logs.")


@router.get("/api/health")
def health(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "model": settings.groq_model,
        "mock_llm": settings.use_mock_llm,
    }


@router.get("/api/customers")
def customers(request: Request) -> list[dict]:
    """Demo helper: seeded customer identities for the chat UI picker."""
    settings: Settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        return [dict(row) for row in repo.list_customers(conn)]


# ---------------------------------------------------------------------------
# admin dashboard endpoints (read-only)
# ---------------------------------------------------------------------------
@router.get("/api/admin/overview")
def admin_overview(request: Request) -> dict:
    settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        return repo.admin_overview(conn)


@router.get("/api/admin/conversations")
def admin_sessions(request: Request, limit: int = 50) -> list[dict]:
    settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        return [dict(row) for row in repo.list_sessions(conn, limit=limit)]


@router.get("/api/admin/conversations/{session_id}")
def admin_transcript(session_id: str, request: Request) -> list[dict]:
    settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        rows = repo.get_conversation(conn, session_id)
        if not rows:
            raise HTTPException(status_code=404, detail="Unknown session id.")
        return [dict(row) for row in rows]


@router.get("/api/admin/orders")
def admin_orders(request: Request) -> list[dict]:
    settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        return [dict(row) for row in repo.list_orders(conn)]


@router.get("/api/admin/leads")
def admin_leads(request: Request) -> list[dict]:
    settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        return [dict(row) for row in repo.list_leads(conn)]


@router.get("/api/admin/tickets")
def admin_tickets(request: Request) -> list[dict]:
    settings = get_settings_from(request)
    with connect_ctx(settings.db_path) as conn:
        return [dict(row) for row in repo.list_tickets(conn)]


@router.get("/api/admin/evals")
def admin_evals(request: Request) -> JSONResponse:
    """Latest eval results written by scripts/run_evals.py."""
    path = PROJECT_ROOT / "evals" / "eval_results.json"
    if not path.exists():
        return JSONResponse(
            status_code=200,
            content={
                "available": False,
                "hint": "Run: python scripts/run_evals.py  (then refresh this page)",
            },
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["available"] = True
    return JSONResponse(status_code=200, content=data)


# ---------------------------------------------------------------------------
# WhatsApp webhook - STUB for Sprint 13 (see docs/whatsapp.md)
# ---------------------------------------------------------------------------
@router.get("/webhook/whatsapp")
def whatsapp_verify(
    request: Request,
    hub_mode: Optional[str] = None,
    hub_verify_token: Optional[str] = None,
    hub_challenge: Optional[str] = None,
):
    """Meta calls this once with GET to verify the webhook URL.

    It is real verification logic - it just does not have the Meta side
    configured yet. Set WHATSAPP_VERIFY_TOKEN in .env when you register
    the webhook in the Meta App Dashboard.
    """
    settings = get_settings_from(request)
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == settings.whatsapp_verify_token:
        return int(hub_challenge or 0)
    raise HTTPException(status_code=403, detail="Webhook verification failed.")


@router.post("/webhook/whatsapp")
def whatsapp_inbound(request: Request) -> JSONResponse:
    """Receives Meta Cloud API messages. NOT WIRED YET.

    Implementation plan lives in docs/whatsapp.md. The plumbing it needs
    (agent.run, the same as every other channel) already works - only the
    Meta-specific envelope parsing and reply sending are missing.
    """
    settings = get_settings_from(request)
    if not settings.whatsapp_phone_number_id:
        return JSONResponse(
            status_code=501,
            content={
                "detail": "WhatsApp channel not configured yet.",
                "how": "See docs/whatsapp.md for the Meta Cloud API setup steps.",
                "pipeline": "webhook -> parse inbound -> agent.run(...) -> Graph API reply",
            },
        )
    # Once Meta credentials exist, parse payload.entry[0].changes[0].value
    # and call agent.run(...) per message - see docs/whatsapp.md.
    return JSONResponse(status_code=501, content={"detail": "Parsing not implemented yet."})
