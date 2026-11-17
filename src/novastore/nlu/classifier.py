"""Intent classifier: message -> validated CustomerTurn (Sprint 03-04).

Pipeline for every message:

1. Build a JSON payload (message + recent history).
2. Ask the LLM for the classification contract (JSON mode).
3. Validate with Pydantic. ANY failure -> UNKNOWN / confidence 0.0.
   This is the brief's *fail-closed parse* rule: bad JSON never becomes a
   guess, it becomes "I don't know" + a clarifying question.
4. Hallucination guard: strip any order_id that does not literally appear
   in the customer's text. The model is allowed to forget, not to invent.
"""

from __future__ import annotations

import re
from typing import Optional

from novastore.config import Settings
from novastore.llm.client import LLMClient
from novastore.logging_setup import get_logger
from novastore.memory.conversation import ConversationMemory
from novastore.nlu.prompts import CLASSIFIER_SYSTEM, build_classify_user
from novastore.schemas.customer_turn import CustomerTurn, Intent, Slots

logger = get_logger(__name__)

# Digit sequences in the raw message (used by the hallucination guard).
_DIGITS_RE = re.compile(r"\d{3,6}")


class Classifier:
    """Turns one raw customer message into a structured CustomerTurn."""

    def __init__(self, llm: LLMClient, settings: Settings, memory: ConversationMemory | None = None):
        self.llm = llm
        self.settings = settings
        self.memory = memory

    def classify(self, message: str, session_id: str | None = None) -> CustomerTurn:
        history: list[dict[str, str]] = []
        if self.memory and session_id:
            history = self.memory.recent(session_id, limit=4)

        payload = build_classify_user(message, history)
        raw = self.llm.chat_json(
            system=CLASSIFIER_SYSTEM,
            user=payload,
            task="classify",
            temperature=0.0,  # classification wants determinism, not creativity
        )

        if raw is None:
            logger.warning("Classifier returned nothing for %r - failing closed.", message[:60])
            return CustomerTurn(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                raw_message=message,
                clarifying_question=(
                    "Sorry, I couldn't process that properly. Could you rephrase your request? "
                    "You can also ask for a human agent any time."
                ),
            )

        turn = self._validate(raw, message)
        self._guard_slots(turn, message)
        return turn

    # ------------------------------------------------------------------
    def _validate(self, raw: dict, message: str) -> CustomerTurn:
        """Map the LLM's dict onto CustomerTurn; catch every mismatch."""
        try:
            intent_raw = str(raw.get("intent", "unknown")).strip().lower()
            try:
                intent = Intent(intent_raw)
            except ValueError:
                logger.warning("Unknown intent %r - mapping to unknown.", intent_raw)
                intent = Intent.UNKNOWN

            confidence_raw = raw.get("confidence", 0.0)
            try:
                confidence = max(0.0, min(1.0, float(confidence_raw)))
            except (TypeError, ValueError):
                confidence = 0.0

            slots_raw = raw.get("slots") or {}
            slots = Slots(
                order_id=_clean_str(slots_raw.get("order_id")),
                product_name=_clean_str(slots_raw.get("product_name")),
                quantity=_clean_int(slots_raw.get("quantity")),
                issue=_clean_str(slots_raw.get("issue")),
            )
            language = _clean_str(raw.get("language"))
            if language not in {"en", "ar"}:
                language = None

            return CustomerTurn(
                intent=intent,
                confidence=confidence,
                slots=slots,
                language=language,
                clarifying_question=_clean_str(raw.get("clarifying_question")) or None,
                raw_message=message,
            )
        except Exception as exc:  # pydantic errors, weird types, ...
            logger.warning("Classifier output failed validation (%s) - failing closed.", exc)
            return CustomerTurn(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                raw_message=message,
                clarifying_question="Could you rephrase that for me?",
            )

    def _guard_slots(self, turn: CustomerTurn, message: str) -> None:
        """Remove facts the customer never wrote (anti-hallucination).

        Only ``order_id`` is dangerous enough to guard this strictly: acting
        on a made-up id could cancel a stranger's order.
        """
        claimed = turn.slots.order_id
        if claimed is None:
            return
        digits = re.sub(r"\D", "", str(claimed))
        if not digits:
            turn.slots.order_id = None
            return
        in_message = _DIGITS_RE.findall(message)
        if digits not in in_message:
            logger.warning(
                "Hallucination guard: model claimed order_id=%s but message %r does not contain it - dropping.",
                digits,
                message[:80],
            )
            turn.slots.order_id = None


def _clean_str(value) -> Optional[str]:
    """None/empty/whitespace -> None; else trimmed string."""
    if value is None:
        return None
    text = str(value).strip()
    # The model sometimes writes the JSON word 'null' or 'None' as text.
    if text.lower() in {"", "null", "none", "n/a", "-"}:
        return None
    return text


def _clean_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 1_000_000:
        return None
    return number
