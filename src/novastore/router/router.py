"""The intent router (Sprint 04).

Deliberately boring: classification already did the hard work, so routing
is a dict lookup - Intent -> handler method. Adding a new intent means
adding it to the enum, the classifier prompt, and this map (tests keep the
three in sync).
"""

from __future__ import annotations

from novastore.schemas.agent import AgentReply
from novastore.schemas.customer_turn import CustomerTurn, Intent


class IntentRouter:
    """Dispatches a validated CustomerTurn to its handler."""

    def __init__(self, handlers):
        self._map = {intent: handlers.method_for(intent) for intent in Intent}

    def dispatch(self, turn: CustomerTurn, session_id: str, customer_id: str) -> AgentReply:
        handler = self._map[turn.intent]
        return handler(turn, session_id, customer_id)

    @property
    def known_intents(self) -> list[str]:
        return [i.value for i in self._map]
