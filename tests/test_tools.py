"""Tool tests: order lookup, privacy, cancellation rules, fuzzy product search."""

from __future__ import annotations

from novastore.db.database import connect_ctx
from novastore.db import repository as repo
from novastore.tools.base import run_tool


def test_check_order_found(agent):
    with agent.conn_provider() as conn:
        result = run_tool("check_order", conn, order_id="5482", customer_id="cust_001")
    assert result.ok
    assert result.data["status"] == "shipped"
    assert "5482" in result.message


def test_check_order_unknown_id(agent):
    with agent.conn_provider() as conn:
        result = run_tool("check_order", conn, order_id="9999", customer_id="cust_001")
    assert not result.ok
    assert "couldn't find" in result.message.lower()


def test_check_order_privacy(agent):
    """cust_002 must NOT see cust_001's order, even though the id exists."""
    with agent.conn_provider() as conn:
        result = run_tool("check_order", conn, order_id="5482", customer_id="cust_002")
    assert not result.ok
    assert "under your account" in result.message.lower()


def test_cancel_cancellable_order(agent):
    with agent.conn_provider() as conn:
        result = run_tool("cancel_order", conn, order_id="5391", customer_id="cust_003")
    assert result.ok
    with agent.conn_provider() as conn:
        assert repo.get_order(conn, "5391")["status"] == "cancelled"


def test_cancel_shipped_order_refused(agent):
    with agent.conn_provider() as conn:
        result = run_tool("cancel_order", conn, order_id="5482", customer_id="cust_001")
    assert not result.ok
    assert "no longer" in result.message.lower()
    with agent.conn_provider() as conn:
        assert repo.get_order(conn, "5482")["status"] == "shipped"


def test_find_product_fuzzy(agent):
    with agent.conn_provider() as conn:
        result = run_tool("find_product", conn, query="iphone 15")
    assert result.ok
    assert result.data["name"] == "iPhone 15"
    assert result.data["price_egp"] > 0


def test_find_product_typo(agent):
    with agent.conn_provider() as conn:
        result = run_tool("find_product", conn, query="iphone 5")
    assert result.ok  # difflib rescues the typo
    assert "iPhone 15" in result.data["name"]


def test_find_product_unknown(agent):
    with agent.conn_provider() as conn:
        result = run_tool("find_product", conn, query="quantum flux capacitor")
    assert not result.ok
    assert "couldn't find" in result.message.lower()


def test_create_ticket_persists(agent):
    with agent.conn_provider() as conn:
        result = run_tool(
            "create_ticket", conn,
            customer_id="cust_001", subject="Test subject",
            priority="high", reason="complaint", session_id="sess_test",
        )
    assert result.ok
    with agent.conn_provider() as conn:
        ticket = repo.get_ticket(conn, result.data["ticket_id"])
    assert ticket is not None and ticket["priority"] == "high"
