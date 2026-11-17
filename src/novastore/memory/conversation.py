"""Conversation memory (Sprint 05).

Two jobs, both persisted in SQLite (so memory survives restarts and the
admin dashboard can show the same transcript the agent saw):

1. Transcript: every customer + agent message, with intent and confidence.
2. Slot memory: last product / last order id mentioned, so a follow-up
   like "and the warranty?" resolves to what the customer meant.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from novastore.db import repository as repo
from novastore.logging_setup import get_logger

logger = get_logger(__name__)

RECENT_WINDOW = 6  # turns of history handed to the classifier / answer prompt


class ConversationMemory:
    """Thin, testable facade over the conversations + session_state tables."""

    def __init__(self, conn_provider):
        """``conn_provider`` is a callable returning an open sqlite3
        connection - the same pattern the API layer uses, so memory and
        handlers always observe a consistent database."""
        self._conn_provider = conn_provider

    # -- transcript -------------------------------------------------------
    def record(
        self,
        *,
        session_id: str,
        customer_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> None:
        with self._conn_provider() as conn:
            repo.add_conversation(
                conn,
                session_id=session_id,
                customer_id=customer_id,
                role=role,
                content=content,
                intent=intent,
                confidence=confidence,
            )

    def recent(self, session_id: str, limit: int = RECENT_WINDOW) -> list[dict[str, str]]:
        """Last ``limit`` turns as [{role, content}], oldest first."""
        with self._conn_provider() as conn:
            rows = repo.get_conversation(conn, session_id)
        recent = rows[-limit:]
        return [{"role": row["role"], "content": row["content"]} for row in recent]

    # -- slot memory -------------------------------------------------------
    def remember(self, session_id: str, **facts: Any) -> None:
        """Store/merge facts like last_product='iPhone 15'."""
        with self._conn_provider() as conn:
            repo.update_session_state(conn, session_id=session_id, **facts)
        logger.debug("Memory for %s updated with %s", session_id, list(facts))

    def recall(self, session_id: str) -> dict[str, Any]:
        with self._conn_provider() as conn:
            return repo.get_session_state(conn, session_id)

    def recall_product(self, session_id: str) -> Optional[str]:
        return self.recall(session_id).get("last_product")

    def forget(self, session_id: str) -> None:
        with self._conn_provider() as conn:
            repo.clear_session_state(conn, session_id)
