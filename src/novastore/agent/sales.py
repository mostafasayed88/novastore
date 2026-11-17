"""B2B lead qualification flow (Sprint 09-10).

A sales inquiry like "I want 30 Dell laptops for my company" cannot be
answered from documents - it needs facts only the customer knows. So the
agent runs a small, explicit slot-filling state machine:

    company -> contact -> email -> product -> quantity -> budget -> timeline -> confirm

State lives in ``session_state`` (persisted, survives restarts). The flow
can be aborted any time by saying "no" / "cancel", or overridden by an
explicit human-handoff request. Only at ``confirm`` is ``create_lead``
called - a lead record, never a fake discount (brief rule).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from novastore.db import repository as repo
from novastore.logging_setup import get_logger
from novastore.safety.confirmation import is_affirmative, is_negative
from novastore.schemas.customer_turn import CustomerTurn

logger = get_logger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_QTY_RE = re.compile(r"\d{1,5}")

# (key, question, kind) - kind decides how the raw answer is parsed.
_STAGES: list[tuple[str, str, str]] = [
    ("company", "Great - I can arrange a business quote. What is your company name?", "text"),
    ("contact", "Who should we address the quote to (your name)?", "text"),
    ("email", "What email should we send the quotation to?", "email"),
    ("product_interest", "Which product are you interested in?", "text"),
    ("quantity", "How many units do you need?", "number"),
    ("budget", "Do you have a budget range in mind? (you can say 'not sure')", "text"),
    ("timeline", "When do you need the units? (e.g. 'this month')", "text"),
]

_FLOW_KEY = "flow"


class SalesFlow:
    """Multi-turn lead qualification. One instance per agent; state is
    per-session and persisted, so it is safe across HTTP requests."""

    def __init__(self, conn_provider, memory):
        self.conn_provider = conn_provider
        self.memory = memory

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def start(self, turn: CustomerTurn, session_id: str) -> str:
        """Enter the flow, prefilled with whatever slots already exist."""
        data: dict[str, Any] = {}
        if turn.slots.product_name:
            data["product_interest"] = turn.slots.product_name
        if turn.slots.quantity:
            data["quantity"] = turn.slots.quantity
        self._save(session_id, {"stage": self._next_stage(data), "data": data})

        known = []
        if "product_interest" in data:
            known.append(f"{data['product_interest']}")
        if "quantity" in data:
            known.append(f"{data['quantity']} units")
        opener = f"Got it - {', '.join(known)}. " if known else ""
        first_stage = self._next_stage(data)
        question = next(q for key, q, _ in _STAGES if key == first_stage)
        return opener + question

    def advance(self, message: str, session_id: str) -> tuple[str, Optional[int]]:
        """Feed one customer message into the flow.

        Returns (reply_text, lead_id_or_None). The lead id is set only on
        the final confirm, when the record is actually saved.
        """
        state = self.memory.recall(session_id).get(_FLOW_KEY) or {}
        stage = state.get("stage")
        data: dict[str, Any] = state.get("data", {})

        # Abort words work at ANY stage.
        if is_negative(message) and stage != "confirm":
            self.abort(session_id)
            return "No problem - I've discarded the business inquiry. Is there anything else I can help with?", None

        # 'confirm' stage: explicit yes/no on the collected summary.
        if stage == "confirm":
            if is_affirmative(message):
                lead_id = self._save_lead(data)
                self.abort(session_id)
                summary = self._summary(data)
                return (
                    f"Perfect - I've saved your inquiry ({summary}). "
                    "Our B2B team will email your quotation within one business day. "
                    f"Reference: lead #{lead_id}.",
                    lead_id,
                )
            if is_negative(message):
                self.abort(session_id)
                return (
                    "Understood - I won't save the inquiry. "
                    "If something was wrong in the summary, just tell me the correct details "
                    "and I'll start again.",
                    None,
                )
            return ("Please reply 'yes' to save this inquiry, or 'no' to discard it.", None)

        # Normal stages: parse the answer for the current field.
        stage_info = next((s for s in _STAGES if s[0] == stage), None)
        if stage_info is None:  # corrupted state - restart cleanly
            self.abort(session_id)
            return "Something went wrong with the inquiry - let's start over. What product do you need?", None

        key, _, kind = stage_info
        parsed = self._parse(message, kind)
        if parsed is None:
            if kind == "email":
                return ("That doesn't look like a valid email - could you type it again?", None)
            if kind == "number":
                return ("Please tell me the number of units (for example 30).", None)
            return ("Could you give me a short answer for that one?", None)

        data[key] = parsed
        next_stage = self._next_stage(data)
        self._save(session_id, {"stage": next_stage, "data": data})

        if next_stage == "confirm":
            return (
                "Here is what I have:\n" + self._summary(data) +
                "\nShall I save this inquiry for our B2B team? (yes / no)",
                None,
            )
        question = next(q for k, q, _ in _STAGES if k == next_stage)
        return question, None

    def abort(self, session_id: str) -> None:
        self.memory.remember(session_id, flow=None)

    def is_active(self, session_id: str) -> bool:
        return bool(self.memory.recall(session_id).get(_FLOW_KEY))

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _save(self, session_id: str, flow: dict[str, Any]) -> None:
        self.memory.remember(session_id, **{_FLOW_KEY: flow})

    def _next_stage(self, data: dict[str, Any]) -> str:
        for key, _, _ in _STAGES:
            if key not in data:
                return key
        return "confirm"

    def _parse(self, message: str, kind: str) -> Optional[Any]:
        text = message.strip()
        if kind == "email":
            match = _EMAIL_RE.search(text)
            return match.group(0) if match else None
        if kind == "number":
            match = _QTY_RE.search(text)
            return int(match.group(0)) if match else None
        # text stage: reject absurdly long or empty answers
        if not text or len(text) > 200:
            return None
        return text

    def _summary(self, data: dict[str, Any]) -> str:
        label = {
            "company": "Company", "contact": "Contact", "email": "Email",
            "product_interest": "Product", "quantity": "Quantity",
            "budget": "Budget", "timeline": "Timeline",
        }
        return "\n".join(f"- {label.get(k, k)}: {v}" for k, v in data.items() if v is not None)

    def _save_lead(self, data: dict[str, Any]) -> int:
        with self.conn_provider() as conn:
            result = repo.create_lead(
                conn,
                company=str(data.get("company", "Unknown company")),
                contact_name=data.get("contact"),
                email=data.get("email"),
                product_interest=data.get("product_interest"),
                quantity=data.get("quantity"),
                budget=data.get("budget"),
                timeline=data.get("timeline"),
                notes="Captured via chat assistant (B2B flow)",
            )
        logger.info("B2B lead #%d saved: %s", result, data.get("company"))
        return result
