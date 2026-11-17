"""The agent loop - NovaStore's brain (Sprint 09-10).

One customer turn, in order:

    1. TRANSCRIPT      save the customer message (admin sees the same truth)
    2. SAFETY          screen for prompt injection -> refuse if flagged
    3. CLASSIFY        message -> validated CustomerTurn (fail closed)
    4. FLOW STATE      an active B2B sales flow captures the next field
    5. CONFIRMATION    a pending sensitive action is confirmed / declined
    6. ROUTE           IntentRouter -> handler -> AgentReply
    7. TRANSCRIPT      save the agent reply with intent + confidence

Why classify BEFORE checking pending actions? Because a fresh, clear
message ("where is my order 5001") must win over a stale yes/no question -
but a bare "yes" only ever confirms what was pending. That ordering is what
keeps confirmations safe AND conversations natural.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from novastore.config import Settings
from novastore.db import repository as repo
from novastore.db.database import connect_ctx
from novastore.llm.client import LLMClient
from novastore.logging_setup import get_logger
from novastore.memory.conversation import ConversationMemory
from novastore.nlu.classifier import Classifier
from novastore.rag.retriever import Retriever
from novastore.router.router import IntentRouter
from novastore.safety.confirmation import classify_confirmation
from novastore.safety.injection import REFUSAL_TEXT, detect_injection
from novastore.schemas.agent import AgentReply
from novastore.schemas.customer_turn import Intent
from novastore.tools.base import run_tool

logger = get_logger(__name__)


class NovaAgent:
    """Facade the HTTP layer (and the CLI) talk to. One instance per process."""

    def __init__(self, settings: Settings, llm: LLMClient, db_path: Path, retriever: Retriever):
        self.settings = settings
        self.db_path = db_path
        self.conn_provider = lambda: connect_ctx(db_path)
        self.memory = ConversationMemory(self.conn_provider)
        self.classifier = Classifier(llm, settings, memory=self.memory)
        from novastore.agent.handlers import IntentHandlers

        self.handlers = IntentHandlers(
            settings=settings, llm=llm,
            conn_provider=self.conn_provider,
            retriever=retriever, memory=self.memory,
        )
        self.router = IntentRouter(self.handlers)
        self.retriever = retriever

    # ------------------------------------------------------------------
    def run(self, session_id: str, customer_id: str, message: str) -> AgentReply:
        """Process one customer message and return the agent's reply."""
        message = (message or "").strip()
        self.memory.record(
            session_id=session_id, customer_id=customer_id,
            role="customer", content=message,
        )

        # 2. safety ------------------------------------------------------
        verdict = detect_injection(message)
        if verdict.is_suspicious:
            reply = AgentReply(
                reply=REFUSAL_TEXT,
                intent="unknown",
                confidence=1.0,
                data={"injection": verdict.reason},
            )
            self._save_reply(session_id, customer_id, reply)
            return reply

        # 3. classify ----------------------------------------------------
        turn = self.classifier.classify(message, session_id=session_id)
        logger.info("Turn session=%s intent=%s conf=%.2f", session_id, turn.intent.value, turn.confidence)

        # 4. active B2B flow ----------------------------------------------
        if self.handlers.sales.is_active(session_id):
            if turn.intent == Intent.HUMAN_HANDOFF:
                self.handlers.sales.abort(session_id)  # human overrides the flow
            else:
                text, lead_id = self.handlers.sales.advance(message, session_id)
                reply = AgentReply(reply=text, intent="sales_inquiry", confidence=turn.confidence)
                if lead_id is not None:
                    reply.lead_id = lead_id
                self._save_reply(session_id, customer_id, reply)
                return reply

        # 5. pending confirmation -----------------------------------------
        reply = self._handle_pending(message, session_id, customer_id, turn)
        if reply is not None:
            self._save_reply(session_id, customer_id, reply)
            return reply

        # 6. route --------------------------------------------------------
        reply = self.router.dispatch(turn, session_id, customer_id)
        self._save_reply(session_id, customer_id, reply)
        return reply

    # ------------------------------------------------------------------
    def _handle_pending(
        self, message: str, session_id: str, customer_id: str, turn
    ) -> Optional[AgentReply]:
        """Confirm / decline a pending sensitive action, or clear it when the
        customer moved on to a different, clearly-new request."""
        with self.conn_provider() as conn:
            pending = repo.get_pending(conn, session_id)
        if pending is None:
            return None

        action = pending["action"]
        payload = pending["payload"]
        verdict = classify_confirmation(message)

        if verdict == "affirmative":
            return self._execute_pending(action, payload, session_id, customer_id, turn)
        if verdict == "negative":
            with self.conn_provider() as conn:
                repo.clear_pending(conn, session_id)
            return AgentReply(
                reply="No problem - I won't do that. Is there anything else I can help with?",
                intent=turn.intent.value,
                confidence=turn.confidence,
            )
        # Unrelated message: a new clear intent wins; drop the stale question
        # so a later stray "yes" can never fire an old dangerous action.
        if turn.intent != Intent.UNKNOWN or turn.confidence >= self.settings.confidence_clarify_below:
            with self.conn_provider() as conn:
                repo.clear_pending(conn, session_id)
            logger.info("Pending action '%s' cleared - customer moved on.", action)
        return None  # fall through to normal routing

    def _execute_pending(
        self, action: str, payload: dict, session_id: str, customer_id: str, turn
    ) -> AgentReply:
        """Run the action the customer just confirmed - and only now.

        NOTE: this method holds one write transaction for the whole action.
        Never call self.memory (it opens a second connection) from inside
        the ``with`` block - SQLite allows a single writer at a time.
        """
        reply: AgentReply | None = None
        remember_last_order: str | None = None

        with self.conn_provider() as conn:
            repo.clear_pending(conn, session_id)

            if action == "confirm_cancel":
                result = run_tool(
                    "cancel_order", conn,
                    order_id=payload.get("order_id"), customer_id=customer_id,
                )
                reply = AgentReply(
                    reply=result.message,
                    intent="cancel_order",
                    confidence=1.0,
                    data=result.data,
                )
                if result.ok:
                    remember_last_order = str(payload.get("order_id"))

            elif action == "confirm_refund":
                order_id = payload.get("order_id")
                repo.set_order_status(conn, order_id, "refund_requested")
                ticket_id = repo.create_ticket(
                    conn,
                    customer_id=customer_id,
                    subject=f"Refund request for order {order_id}",
                    priority="normal",
                    reason="refund",
                    session_id=session_id,
                )
                reply = AgentReply(
                    reply=(
                        f"Done - your refund request for order {order_id} is in, ticket #{ticket_id}. "
                        "After the item is inspected, the refund goes back to your original "
                        "payment method within 3-7 business days."
                    ),
                    intent="refund_request",
                    confidence=1.0,
                    ticket_id=ticket_id,
                    data={"order_id": order_id, "status": "refund_requested"},
                )

            elif action == "ticket_offer":
                result = run_tool(
                    "create_ticket", conn,
                    customer_id=payload.get("customer_id") or customer_id,
                    subject=payload.get("subject", "Support request"),
                    priority=payload.get("priority", "normal"),
                    reason=payload.get("reason", "support"),
                    session_id=session_id,
                )
                reply = AgentReply(
                    reply=(
                        result.message + " Our team will follow up with you. "
                        "Anything else I can help with?"
                        if result.ok
                        else result.message
                    ),
                    intent=turn.intent.value,
                    confidence=turn.confidence,
                    ticket_id=result.data.get("ticket_id") if result.ok else None,
                    data=result.data,
                )

        if remember_last_order:
            self.memory.remember(session_id, last_order_id=remember_last_order)
        if reply is not None:
            return reply

        logger.warning("Unknown pending action '%s' - ignoring.", action)
        return AgentReply(
            reply="Sorry, something went wrong with that confirmation. Could you start again?",
            intent="unknown",
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    def _save_reply(self, session_id: str, customer_id: str, reply: AgentReply) -> None:
        self.memory.record(
            session_id=session_id, customer_id=customer_id,
            role="agent", content=reply.reply,
            intent=reply.intent, confidence=reply.confidence,
        )
