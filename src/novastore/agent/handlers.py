"""Intent handlers (Sprint 04, 07-10).

One handler per intent. Two kinds of handler live here:

* Transactional (tracking, cancel, availability): deterministic code runs
  tools and formats facts. The LLM is NOT asked for opinions about an
  order status - facts come from the database.
* Policy / knowledge (returns, warranty, shipping, product info): the RAG
  retriever fetches store docs first, then the LLM composes the wording
  grounded in those docs only. No retrieval -> "I don't know" + ticket,
  never invented policy.

Handlers NEVER call the LLM for side effects; they call tools for those.
Sensitive actions (cancel, refund) go through a confirmation round-trip
stored in ``pending_actions`` - see safety/confirmation.py.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from novastore.config import Settings
from novastore.db import repository as repo
from novastore.llm.client import LLMClient
from novastore.logging_setup import get_logger
from novastore.memory.conversation import ConversationMemory
from novastore.nlu.prompts import ANSWER_SYSTEM, build_answer_user
from novastore.rag.retriever import Retriever
from novastore.schemas.agent import AgentAction, AgentDecision, AgentReply, Citation
from novastore.schemas.customer_turn import CustomerTurn, Intent
from novastore.tools.base import run_tool
from novastore.tools.store_tools import CANCELLABLE_STATUSES

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lightweight heuristics (kept transparent on purpose)
# ---------------------------------------------------------------------------
_ANGRY_WORDS = {
    "furious", "angry", "worst", "terrible", "unacceptable", "scam",
    "lawyer", "sue", "report you", "هيجامل", "غاضب", "تعامل سيء",
}
_GREETING_RE = re.compile(
    r"^\s*(hi|hii+|hello+|hey|good\s*(morning|evening|afternoon)|ahlan|azayak|"
    r"ازيك|السلام\s+عليكم|مرحبا|أهلا|صباح\s+الخير)[\s!.,]*$",
    re.IGNORECASE,
)

EMPATHY = "I'm really sorry about that - let's get it sorted out."

WELCOME_TEXT = (
    "Hello! Welcome to NovaStore. I can help with:\n"
    "- Order status (give me your order number)\n"
    "- Product info, prices, stock and warranty\n"
    "- Shipping, returns and refunds\n"
    "- Business / bulk orders\n"
    "What do you need today?"
)


class IntentHandlers:
    """All intent handlers, wired to shared dependencies."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        conn_provider: Callable[[], Any],
        retriever: Retriever,
        memory: ConversationMemory,
    ):
        self.settings = settings
        self.llm = llm
        self.conn = conn_provider  # context manager yielding a sqlite connection
        self.retriever = retriever
        self.memory = memory
        from novastore.agent.sales import SalesFlow  # local import avoids a cycle

        self.sales = SalesFlow(conn_provider, memory)

    # ==================================================================
    # shared helpers
    # ==================================================================
    def _reply(
        self,
        text: str,
        turn: CustomerTurn,
        *,
        citations: list[Citation] | None = None,
        data: dict[str, Any] | None = None,
        handoff: bool = False,
        ticket_id: int | None = None,
        lead_id: int | None = None,
    ) -> AgentReply:
        return AgentReply(
            reply=text,
            intent=turn.intent.value,
            confidence=turn.confidence,
            citations=citations or [],
            data=data or {},
            handoff=handoff,
            ticket_id=ticket_id,
            lead_id=lead_id,
        )

    def _grounded_answer(
        self,
        question: str,
        session_id: str,
        product_facts: dict[str, Any] | None = None,
        extra_query: str | None = None,
        intent: str = "unknown",
    ) -> AgentReply:
        """RAG answer path: retrieve store docs -> LLM composes the wording.

        Enforces the brief's rules at one choke point:
        * retrieval found nothing -> honest 'I don't know' (+ ticket offer)
        * LLM output failed validation -> fail closed, offer a human
        """
        chunks = self.retriever.retrieve(extra_query or question)
        if not chunks:
            return AgentReply(
                reply=(
                    "I don't have that in our store knowledge yet, and I won't guess. "
                    "Would you like me to open a ticket so a human colleague answers you?"
                ),
                intent=intent,
                confidence=0.0,
                data={"retrieval_miss": True},
            )

        docs = [{"doc": c.doc, "title": c.title, "text": c.text, "score": c.score} for c in chunks]
        history = self.memory.recent(session_id, limit=4)
        raw = self.llm.chat_json(
            system=ANSWER_SYSTEM,
            user=build_answer_user(question, docs, product_facts, history),
            task="answer",
        )

        decision: AgentDecision | None = None
        if raw is not None:
            try:
                decision = AgentDecision.model_validate(raw)
            except Exception:
                decision = None
        if decision is None:
            logger.warning("Answer step failed validation - failing closed.")
            return AgentReply(
                reply=(
                    "I found related store information but couldn't verify the details "
                    "properly. Let me connect you with a human colleague to be sure."
                ),
                intent=intent,
                confidence=0.0,
                data={"retrieval_miss": True},
            )

        citations = [Citation(doc=c.doc, title=c.title, score=c.score) for c in chunks[:2]]
        if decision.action == AgentAction.ANSWER and decision.answer.strip():
            return AgentReply(reply=decision.answer.strip(), citations=citations, intent=intent)
        if decision.action == AgentAction.CLARIFY and (decision.ask_user or decision.answer).strip():
            return AgentReply(reply=(decision.ask_user or decision.answer).strip(), intent=intent)
        # handoff (or an empty answer) -> a human takes it from here
        return AgentReply(
            reply="This one is better handled by a human colleague - I'll open a ticket for you right away.",
            intent=intent,
            handoff=True,
        )

    def _is_angry(self, message: str) -> bool:
        lowered = message.lower()
        if any(word in lowered for word in _ANGRY_WORDS):
            return True
        bangs = message.count("!")
        letters = [c for c in message if c.isalpha()]
        if letters and bangs >= 3:
            return True
        caps = sum(1 for c in letters if c.isupper())
        if len(letters) > 20 and caps / len(letters) > 0.6:
            return True
        return False

    def _create_ticket_reply(
        self,
        turn: CustomerTurn,
        *,
        customer_id: str,
        session_id: str,
        subject: str,
        priority: str,
        reason: str,
        prefix: str,
    ) -> AgentReply:
        with self.conn() as conn:
            result = run_tool(
                "create_ticket", conn,
                customer_id=customer_id, subject=subject,
                priority=priority, reason=reason, session_id=session_id,
            )
        if not result.ok:
            return self._reply(prefix + " " + result.message, turn)
        ticket_id = result.data["ticket_id"]
        return self._reply(
            f"{prefix} I've opened ticket #{ticket_id}; our team follows up within one business day.",
            turn,
            ticket_id=ticket_id,
            handoff=(reason == "handoff"),
            data=result.data,
        )

    # ==================================================================
    # order_tracking
    # ==================================================================
    def order_tracking(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        order_id = turn.slots.order_id or self.memory.recall(session_id).get("last_order_id")
        if not order_id:
            return self._reply(
                "Sure - which order number should I look up? You'll find it in your "
                "confirmation SMS or email (for example: 5482).",
                turn,
            )
        with self.conn() as conn:
            result = run_tool("check_order", conn, order_id=order_id, customer_id=customer_id)
        if not result.ok:
            return self._reply(result.message, turn, data={"order_id": order_id})
        self.memory.remember(session_id, last_order_id=order_id)
        return self._reply(result.message, turn, data=result.data)

    # ==================================================================
    # cancel_order  (sensitive: needs confirmation)
    # ==================================================================
    def cancel_order(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        order_id = turn.slots.order_id or self.memory.recall(session_id).get("last_order_id")
        if not order_id:
            return self._reply(
                "I can help cancel an order. Which order number is it? "
                "(You can also ask 'where is my order' first if you're not sure.)",
                turn,
            )
        with self.conn() as conn:
            check = run_tool("check_order", conn, order_id=order_id, customer_id=customer_id)
        if not check.ok:
            return self._reply(check.message, turn, data={"order_id": order_id})

        status = check.data.get("status")
        if status not in CANCELLABLE_STATUSES:
            return self._reply(
                f"Order {order_id} is '{status}', so it can no longer be cancelled directly. "
                "Shipped orders can be refused at the door or returned within 14 days - "
                "just ask me about returns.",
                turn,
                data=check.data,
            )

        # Arm the confirmation round-trip. The actual cancel_order tool runs
        # ONLY after the customer's next message confirms (agent.py).
        with self.conn() as conn:
            repo.set_pending(
                conn, session_id=session_id,
                action="confirm_cancel",
                payload={"order_id": order_id, "customer_id": customer_id},
            )
        return self._reply(
            f"Just to be safe: do you want me to cancel order {order_id} "
            f"({', '.join(i['name'] for i in check.data.get('items', [])) or 'your items'})? "
            "Please reply yes or no.",
            turn,
            data=check.data,
        )

    # ==================================================================
    # return_request
    # ==================================================================
    def return_request(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        answer = self._grounded_answer(
            turn.raw_message, session_id, extra_query=f"{turn.raw_message} return policy",
            intent=turn.intent.value,
        )
        offers_ticket = answer.data.get("retrieval_miss") is not True
        if offers_ticket:
            subject = f"Return request{f' for order {turn.slots.order_id}' if turn.slots.order_id else ''}"
            with self.conn() as conn:
                repo.set_pending(
                    conn, session_id=session_id,
                    action="ticket_offer",
                    payload={"subject": subject, "reason": "return", "priority": "normal",
                             "customer_id": customer_id, "session_id": session_id},
                )
            answer.reply += "\n\nWould you like me to open a return ticket for you? (yes / no)"
        return answer

    # ==================================================================
    # refund_request  (sensitive: needs confirmation)
    # ==================================================================
    def refund_request(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        order_id = turn.slots.order_id or self.memory.recall(session_id).get("last_order_id")
        if not order_id:
            return self._reply(
                "I can start a refund request. Which order number is the refund for?",
                turn,
            )
        with self.conn() as conn:
            check = run_tool("check_order", conn, order_id=order_id, customer_id=customer_id)
        if not check.ok:
            return self._reply(check.message, turn)

        with self.conn() as conn:
            repo.set_pending(
                conn, session_id=session_id,
                action="confirm_refund",
                payload={"order_id": order_id, "customer_id": customer_id},
            )
        return self._reply(
            f"To confirm: you want to request a refund for order {order_id} "
            f"({check.data.get('status')}). Refunds go back to the original payment method "
            "within 3-7 business days after inspection. Shall I open the request? (yes / no)",
            turn,
            data=check.data,
        )

    # ==================================================================
    # product_question / availability_check / warranty_question
    # ==================================================================
    def product_question(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        product_name = turn.slots.product_name or self.memory.recall_product(session_id)
        facts: dict[str, Any] | None = None
        if product_name:
            with self.conn() as conn:
                found = run_tool("find_product", conn, query=product_name)
            if found.ok:
                facts = found.data
                self.memory.remember(session_id, last_product=found.data["name"])
            elif turn.slots.product_name:
                # Customer named something we don't carry - trust the tool's suggestions.
                return self._reply(found.message, turn)
        answer = self._grounded_answer(
            turn.raw_message, session_id, product_facts=facts,
            extra_query=f"{turn.raw_message} {product_name or ''}".strip(),
            intent=turn.intent.value,
        )
        return answer

    def availability_check(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        product_name = turn.slots.product_name or self.memory.recall_product(session_id)
        if not product_name:
            return self._reply("Which product should I check? (for example: iPhone 15)", turn)
        with self.conn() as conn:
            found = run_tool("find_product", conn, query=product_name)
        if not found.ok:
            return self._reply(found.message, turn)
        self.memory.remember(session_id, last_product=found.data["name"])
        text = found.message
        if found.data.get("stock", 0) == 0:
            with self.conn() as conn:
                repo.set_pending(
                    conn, session_id=session_id,
                    action="ticket_offer",
                    payload={
                        "subject": f"Notify me when {found.data['name']} is back in stock",
                        "reason": "support", "priority": "low",
                        "customer_id": customer_id, "session_id": session_id,
                    },
                )
            text += " Want me to open a ticket so we email you when it's back? (yes / no)"
        return self._reply(text, turn, data=found.data)

    def warranty_question(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        product_name = turn.slots.product_name or self.memory.recall_product(session_id)
        facts: dict[str, Any] | None = None
        if product_name:
            with self.conn() as conn:
                found = run_tool("find_product", conn, query=product_name)
            if found.ok:
                facts = found.data
                self.memory.remember(session_id, last_product=found.data["name"])
        answer = self._grounded_answer(
            turn.raw_message, session_id, product_facts=facts,
            extra_query=f"{turn.raw_message} warranty {product_name or ''}".strip(),
            intent=turn.intent.value,
        )
        return answer

    # ==================================================================
    # shipping_info
    # ==================================================================
    def shipping_info(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        answer = self._grounded_answer(
            turn.raw_message, session_id, extra_query=f"{turn.raw_message} shipping",
            intent=turn.intent.value,
        )
        # "How long does shipping take to Cairo" with an order id is really tracking.
        if turn.slots.order_id:
            with self.conn() as conn:
                check = run_tool("check_order", conn, order_id=turn.slots.order_id, customer_id=customer_id)
            if check.ok:
                self.memory.remember(session_id, last_order_id=turn.slots.order_id)
                answer.reply = f"About your order: {check.message}\n\n" + answer.reply
        return answer

    # ==================================================================
    # complaint / tech_support
    # ==================================================================
    def complaint(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        angry = self._is_angry(turn.raw_message)
        priority = "high" if angry else "normal"
        subject = turn.slots.issue or turn.raw_message[:120]
        if angry:
            with self.conn() as conn:
                result = run_tool(
                    "create_ticket", conn, customer_id=customer_id,
                    subject=f"COMPLAINT: {subject}", priority="high",
                    reason="complaint", session_id=session_id,
                )
            if result.ok:
                return self._reply(
                    f"{EMPATHY} This is important, so I'm bringing in a human colleague right now - "
                    f"ticket #{result.data['ticket_id']} is marked high priority and someone will "
                    "contact you directly. I won't try to fix this myself.",
                    turn, ticket_id=result.data["ticket_id"], handoff=True, data=result.data,
                )
            return self._reply(EMPATHY + " " + result.message, turn, handoff=True)

        return self._create_ticket_reply(
            turn,
            customer_id=customer_id, session_id=session_id,
            subject=subject, priority=priority, reason="complaint",
            prefix=EMPATHY,
        )

    def tech_support(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        subject = turn.slots.issue or turn.raw_message[:120]
        reply = self._create_ticket_reply(
            turn,
            customer_id=customer_id, session_id=session_id,
            subject=subject, priority="normal", reason="tech_support",
            prefix="I can help with that.",
        )
        reply.reply += (
            " While you wait: which device model is it, and what exactly happens "
            "(any lights, sounds, or error messages)?"
        )
        return reply

    # ==================================================================
    # sales_inquiry
    # ==================================================================
    def sales_inquiry(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        quantity = turn.slots.quantity
        if quantity is not None and quantity < 10:
            answer = self._grounded_answer(
                turn.raw_message, session_id,
                extra_query=f"{turn.raw_message} discount tiers units minimum",
            )
            return self._reply(answer.reply, turn, citations=answer.citations)
        # 10+ units (or unknown quantity) -> start the qualification flow.
        question = self.sales.start(turn, session_id)
        return self._reply(question, turn)

    # ==================================================================
    # human_handoff
    # ==================================================================
    def human_handoff(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        if self.sales.is_active(session_id):
            self.sales.abort(session_id)
        return self._create_ticket_reply(
            turn,
            customer_id=customer_id, session_id=session_id,
            subject="Customer asked for a human agent", priority="high", reason="handoff",
            prefix="Of course - connecting you with a human colleague.",
        )

    # ==================================================================
    # unknown
    # ==================================================================
    def unknown(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        if _GREETING_RE.match(turn.raw_message.strip()):
            return self._reply(WELCOME_TEXT, turn)
        if turn.confidence < self.settings.confidence_handoff_below:
            return self._reply(
                "I'm not sure I understood that one. Could you rephrase it? "
                "Or say 'I want to talk to a person' and a human colleague will jump in.",
                turn,
            )
        question = turn.clarifying_question or (
            "Could you tell me a bit more about what you need - an order update, "
            "product info, or something else?"
        )
        return self._reply(question, turn)

    # ==================================================================
    # routing map
    # ==================================================================
    def method_for(self, intent: Intent) -> Callable[[CustomerTurn, str, str], AgentReply]:
        """The intent router's table: Intent -> handler method."""
        return {
            Intent.ORDER_TRACKING: self.order_tracking,
            Intent.CANCEL_ORDER: self.cancel_order,
            Intent.RETURN_REQUEST: self.return_request,
            Intent.REFUND_REQUEST: self.refund_request,
            Intent.PRODUCT_QUESTION: self.product_question,
            Intent.AVAILABILITY_CHECK: self.availability_check,
            Intent.SHIPPING_INFO: self.shipping_info,
            Intent.WARRANTY_QUESTION: self.warranty_question,
            Intent.COMPLAINT: self.complaint,
            Intent.TECH_SUPPORT: self.tech_support,
            Intent.SALES_INQUIRY: self.sales_inquiry,
            Intent.HUMAN_HANDOFF: self.human_handoff,
            Intent.UNKNOWN: self.unknown,
        }[intent]
