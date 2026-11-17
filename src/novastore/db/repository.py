"""Repositories - the ONLY place that runs SQL for business data.

Handlers and tools never write SQL themselves; they call these methods.
That keeps queries in one file, makes them testable, and mirrors how a
real codebase separates persistence from logic.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# customers / products / orders
# ---------------------------------------------------------------------------

def get_customer(conn: sqlite3.Connection, customer_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()


def list_customers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM customers ORDER BY id").fetchall()


def get_product(conn: sqlite3.Connection, sku: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()


def list_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM products ORDER BY name").fetchall()


def get_order(conn: sqlite3.Connection, order_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", (str(order_id),)).fetchone()


def get_order_items(conn: sqlite3.Connection, order_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT oi.qty, oi.unit_price, p.name, p.sku
           FROM order_items oi JOIN products p ON p.sku = oi.sku
           WHERE oi.order_id = ?""",
        (str(order_id),),
    ).fetchall()


def list_orders(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM orders ORDER BY placed_at DESC LIMIT ?", (limit,)).fetchall()


def set_order_status(conn: sqlite3.Connection, order_id: str, status: str) -> None:
    conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, str(order_id)))


# ---------------------------------------------------------------------------
# tickets
# ---------------------------------------------------------------------------

def create_ticket(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    subject: str,
    priority: str = "normal",
    reason: str = "support",
    session_id: Optional[str] = None,
    status: str = "open",
) -> int:
    cur = conn.execute(
        """INSERT INTO tickets (customer_id, session_id, subject, priority, status, reason, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, session_id, subject, priority, status, reason, _now(), _now()),
    )
    return int(cur.lastrowid or 0)


def list_tickets(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()


# ---------------------------------------------------------------------------
# leads
# ---------------------------------------------------------------------------

def create_lead(
    conn: sqlite3.Connection,
    *,
    company: str,
    contact_name: Optional[str] = None,
    email: Optional[str] = None,
    product_interest: Optional[str] = None,
    quantity: Optional[int] = None,
    budget: Optional[str] = None,
    timeline: Optional[str] = None,
    notes: Optional[str] = None,
    status: str = "new",
) -> int:
    cur = conn.execute(
        """INSERT INTO leads
               (company, contact_name, email, product_interest, quantity,
                budget, timeline, status, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (company, contact_name, email, product_interest, quantity, budget, timeline, status, notes, _now()),
    )
    return int(cur.lastrowid or 0)


def list_leads(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()


# ---------------------------------------------------------------------------
# conversations (transcript)
# ---------------------------------------------------------------------------

def add_conversation(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    customer_id: str,
    role: str,
    content: str,
    intent: Optional[str] = None,
    confidence: Optional[float] = None,
) -> None:
    conn.execute(
        """INSERT INTO conversations (session_id, customer_id, role, content, intent, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, customer_id, role, content, intent, confidence, _now()),
    )


def get_conversation(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM conversations WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()


def list_sessions(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    """One row per session with a preview and timestamps for the admin UI."""
    return conn.execute(
        """SELECT session_id,
                  MAX(customer_id) AS customer_id,
                  COUNT(*) AS turns,
                  MIN(created_at) AS started_at,
                  MAX(created_at) AS last_at,
                  (SELECT content FROM conversations c2
                    WHERE c2.session_id = c1.session_id AND c2.role = 'customer'
                    ORDER BY c2.id LIMIT 1) AS first_message
           FROM conversations c1
           GROUP BY session_id
           ORDER BY MAX(c1.id) DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def count_recent_messages(conn: sqlite3.Connection, hours: int = 24) -> int:
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM conversations
           WHERE created_at >= datetime('now', ?)""",
        (f"-{hours} hours",),
    ).fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# pending actions (confirmation state) & session state (memory)
# ---------------------------------------------------------------------------

def set_pending(conn: sqlite3.Connection, *, session_id: str, action: str, payload: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO pending_actions (session_id, action, payload_json, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET action = excluded.action,
                                                 payload_json = excluded.payload_json,
                                                 created_at = excluded.created_at""",
        (session_id, action, json.dumps(payload, ensure_ascii=False), _now()),
    )


def get_pending(conn: sqlite3.Connection, session_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM pending_actions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        payload = {}
    return {"action": row["action"], "payload": payload}


def clear_pending(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM pending_actions WHERE session_id = ?", (session_id,))


def set_session_state(conn: sqlite3.Connection, *, session_id: str, data: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO session_state (session_id, data_json) VALUES (?, ?)
           ON CONFLICT(session_id) DO UPDATE SET data_json = excluded.data_json""",
        (session_id, json.dumps(data, ensure_ascii=False)),
    )


def get_session_state(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT data_json FROM session_state WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["data_json"])
    except json.JSONDecodeError:
        return {}


def update_session_state(conn: sqlite3.Connection, *, session_id: str, **updates: Any) -> dict[str, Any]:
    """Read-modify-write helper for session_state."""
    data = get_session_state(conn, session_id)
    data.update(updates)
    set_session_state(conn, session_id=session_id, data=data)
    return data


def clear_session_state(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM session_state WHERE session_id = ?", (session_id,))


# ---------------------------------------------------------------------------
# admin overview
# ---------------------------------------------------------------------------

def admin_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    def one(sql: str) -> int:
        row = conn.execute(sql).fetchone()
        return int(row[0]) if row else 0

    orders_by_status = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status").fetchall()
    }
    return {
        "customers": one("SELECT COUNT(*) FROM customers"),
        "products": one("SELECT COUNT(*) FROM products"),
        "orders": one("SELECT COUNT(*) FROM orders"),
        "orders_by_status": orders_by_status,
        "open_tickets": one("SELECT COUNT(*) FROM tickets WHERE status != 'resolved'"),
        "leads": one("SELECT COUNT(*) FROM leads"),
        "sessions": one("SELECT COUNT(DISTINCT session_id) FROM conversations"),
        "messages_last_24h": count_recent_messages(conn, hours=24),
    }
