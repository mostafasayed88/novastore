"""Confirmation state machine + pending-action flows through the agent."""

from __future__ import annotations

from novastore.db import repository as repo
from novastore.safety.confirmation import classify_confirmation, is_affirmative, is_negative


def test_affirmatives():
    assert classify_confirmation("yes") == "affirmative"
    assert classify_confirmation("Yes please") == "affirmative"
    assert classify_confirmation("ok") == "affirmative"
    assert classify_confirmation("نعم") == "affirmative"


def test_negatives():
    assert classify_confirmation("no") == "negative"
    assert classify_confirmation("no thanks") == "negative"
    assert classify_confirmation("cancel that") == "negative"


def test_lookalike_words_are_not_confirmations():
    """'Nile...' must not match the bare 'n', 'Your company' must not match 'y'."""
    assert classify_confirmation("Nile Tech Solutions") == "unrelated"
    assert classify_confirmation("Your company name is X") == "unrelated"
    assert classify_confirmation("maybe") == "unrelated"


def test_pending_cancel_execute(agent):
    session = "sess_conf_ok"
    agent.run(session, "cust_003", "Cancel order 5391")  # arms confirmation
    with agent.conn_provider() as conn:
        pending = repo.get_pending(conn, session)
    assert pending and pending["action"] == "confirm_cancel"

    reply = agent.run(session, "cust_003", "yes")  # customer confirms
    assert "cancelled" in reply.reply.lower()
    with agent.conn_provider() as conn:
        assert repo.get_order(conn, "5391")["status"] == "cancelled"
        assert repo.get_pending(conn, session) is None  # consumed


def test_pending_cancel_declined(agent):
    session = "sess_conf_no"
    agent.run(session, "cust_003", "Cancel order 5391")
    reply = agent.run(session, "cust_003", "no")
    assert "won't do that" in reply.reply.lower()
    with agent.conn_provider() as conn:
        assert repo.get_order(conn, "5391")["status"] == "processing"
        assert repo.get_pending(conn, session) is None


def test_pending_cleared_by_new_intent(agent):
    """A fresh, clear question must NOT leave a stale armed 'yes' trap."""
    session = "sess_conf_mixed"
    agent.run(session, "cust_003", "Cancel order 5391")
    agent.run(session, "cust_003", "Where is order 5103?")  # new intent wins
    with agent.conn_provider() as conn:
        assert repo.get_pending(conn, session) is None
    # A late 'yes' must now be harmless.
    reply = agent.run(session, "cust_003", "yes")
    assert "cancelled" not in reply.reply.lower()
    with agent.conn_provider() as conn:
        assert repo.get_order(conn, "5391")["status"] == "processing"
