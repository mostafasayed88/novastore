"""Pydantic contracts for the agent layer (Sprint 07-10).

``AgentDecision`` is what the LLM is allowed to output on the Q&A path;
``AgentReply`` is what our HTTP API returns to any channel (web chat,
CLI, later WhatsApp). Channels only ever see ``AgentReply`` - that keeps
web, WhatsApp and future channels consistent.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentAction(str, Enum):
    """The agent loop's four possible moves, as defined in the brief:
    answer, ask a question, or escalate. (Tool use happens deterministically
    inside handlers, so the LLM never triggers side effects directly.)"""

    ANSWER = "answer"
    CLARIFY = "clarify"
    HANDOFF = "handoff"


class Citation(BaseModel):
    """Pointer to the store document a claim came from."""

    doc: str = Field(description="Document file name, e.g. 'returns.md'")
    title: str = Field(default="", description="Section heading inside the document")
    score: float = Field(default=0.0, ge=0.0, description="Retrieval similarity score")

    model_config = {"extra": "forbid"}


class AgentDecision(BaseModel):
    """Validated output of the LLM's 'compose an answer' step.

    Fail-closed policy: if the LLM returns JSON that does not fit this
    schema, the caller replaces it with a safe CLARIFY decision instead of
    guessing (see novastore/agent/agent.py).
    """

    action: AgentAction = AgentAction.CLARIFY
    answer: str = Field(default="", description="Customer-facing reply text (may be empty for clarify/handoff)")
    citations: list[Citation] = Field(default_factory=list)
    ask_user: Optional[str] = Field(default=None, description="Question to ask when action == clarify")

    model_config = {"extra": "forbid"}


class AgentReply(BaseModel):
    """The single response object every channel receives from POST /api/chat."""

    reply: str
    intent: str = "unknown"
    confidence: float = 0.0
    handoff: bool = Field(default=False, description="True when a human must take over")
    ticket_id: Optional[int] = None
    lead_id: Optional[int] = None
    citations: list[Citation] = Field(default_factory=list)
    # Structured facts for UIs (order status, product stock, ...). Free-form
    # on purpose: each intent returns its own small payload.
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    customer_id: str = Field(description="Identifies the customer (seeded demo ids like 'cust_001')")
    message: str = Field(min_length=1, max_length=2000)
    session_id: Optional[str] = Field(
        default=None,
        description="Conversation continuation id; omit to start a new conversation",
    )

    model_config = {"extra": "forbid"}
