"""NovaStore's five tools.

Every tool follows the same contract:
* Takes a sqlite connection + typed arguments.
* Returns ToolResult(ok, message, data) - never raises for business errors.
* ``cancel_order`` is marked SENSITIVE: handlers must obtain explicit
  customer confirmation BEFORE calling it (enforced by safety/confirmation).

These are plain, readable functions on purpose: this is the layer that
would be replaced by a payments service in a real company.
"""

from __future__ import annotations

import difflib
import sqlite3
from typing import Optional

from novastore.db import repository as repo
from novastore.logging_setup import get_logger
from novastore.tools.base import ToolResult, ToolSpec, register

logger = get_logger(__name__)

# Statuses from which an order can still be cancelled.
CANCELLABLE_STATUSES = {"pending_payment", "processing"}


# ---------------------------------------------------------------------------
# check_order
# ---------------------------------------------------------------------------
def _check_order(conn: sqlite3.Connection, order_id: str, customer_id: Optional[str] = None) -> ToolResult:
    """Look up one order and return its live status + items."""
    order_id = str(order_id).strip()
    order = repo.get_order(conn, order_id)
    if order is None:
        return ToolResult(ok=False, message=f"I couldn't find any order with number {order_id}.")
    # Privacy: a customer may only see their own orders. Never leak another
    # customer's data even if the id exists.
    if customer_id is not None and order["customer_id"] != customer_id:
        return ToolResult(
            ok=False,
            message=f"I couldn't find an order {order_id} under your account. "
            "Please double-check the number.",
        )
    items = repo.get_order_items(conn, order_id)
    item_names = ", ".join(f"{row['qty']}x {row['name']}" for row in items) or "no items"
    eta = order["eta"] or "not scheduled yet"
    carrier = order["carrier"] or "no carrier assigned yet"
    data = {
        "order_id": order_id,
        "status": order["status"],
        "placed_at": order["placed_at"],
        "shipping_city": order["shipping_city"],
        "carrier": carrier,
        "tracking_code": order["tracking_code"],
        "eta": eta,
        "items": [dict(row) for row in items],
        "total_egp": order["total_egp"],
    }
    message = (
        f"Order {order_id} ({item_names}) is currently '{order['status']}'. "
        f"Carrier: {carrier}, tracking {order['tracking_code'] or 'n/a'}, estimated delivery: {eta}."
    )
    return ToolResult(ok=True, message=message, data=data)


# ---------------------------------------------------------------------------
# cancel_order  (SENSITIVE)
# ---------------------------------------------------------------------------
def _cancel_order(conn: sqlite3.Connection, order_id: str, customer_id: Optional[str] = None) -> ToolResult:
    """Cancel an order - only after explicit customer confirmation."""
    order_id = str(order_id).strip()
    order = repo.get_order(conn, order_id)
    if order is None:
        return ToolResult(ok=False, message=f"I couldn't find any order with number {order_id}.")
    if customer_id is not None and order["customer_id"] != customer_id:
        return ToolResult(ok=False, message=f"Order {order_id} is not registered under your account.")
    if order["status"] not in CANCELLABLE_STATUSES:
        return ToolResult(
            ok=False,
            message=(
                f"Order {order_id} is '{order['status']}', so it can no longer be cancelled. "
                "Shipped orders can be refused at delivery or returned within 14 days - "
                "I can explain the return process if you'd like."
            ),
            data={"order_id": order_id, "status": order["status"]},
        )
    repo.set_order_status(conn, order_id, "cancelled")
    logger.info("Order %s cancelled for %s", order_id, customer_id)
    return ToolResult(
        ok=True,
        message=f"Done - order {order_id} has been cancelled. If you already paid, "
        "the refund is issued within 3-7 business days.",
        data={"order_id": order_id, "status": "cancelled"},
    )


# ---------------------------------------------------------------------------
# find_product
# ---------------------------------------------------------------------------
def _find_product(conn: sqlite3.Connection, query: str) -> ToolResult:
    """Fuzzy-match a customer's product words against the catalog."""
    query = str(query).strip()
    if not query:
        return ToolResult(ok=False, message="Please tell me which product you mean.")
    products = repo.list_products(conn)
    lowered = query.lower()

    # Pass 1: substring hit on name / sku / brand (fast, precise).
    for product in products:
        hay = f"{product['sku']} {product['name']} {product['brand']}".lower()
        if lowered in hay or any(word in hay for word in lowered.split() if len(word) > 2):
            return _product_result(product)

    # Pass 2: fuzzy closest match (handles typos like 'iphone 5' -> 'iPhone 15').
    names = [p["name"] for p in products]
    close = difflib.get_close_matches(query, names, n=1, cutoff=0.45)
    if close:
        product = next(p for p in products if p["name"] == close[0])
        return _product_result(product)

    suggestions = ", ".join(p["name"] for p in products[:6])
    return ToolResult(
        ok=False,
        message=f"I couldn't find a product matching '{query}'. Products we carry: {suggestions}.",
    )


def _product_result(product: sqlite3.Row) -> ToolResult:
    stock = product["stock"]
    if stock > 0:
        availability = f"in stock ({stock} units)"
    else:
        availability = "currently out of stock - restock is usually 2-3 weeks"
    data = {
        "sku": product["sku"],
        "name": product["name"],
        "brand": product["brand"],
        "category": product["category"],
        "price_egp": product["price_egp"],
        "stock": stock,
        "warranty_months": product["warranty_months"],
        "description": product["description"],
        "availability": availability,
    }
    message = (
        f"{product['name']} by {product['brand']} - {product['price_egp']:.0f} EGP, "
        f"{product['warranty_months']} months warranty, {availability}."
    )
    return ToolResult(ok=True, message=message, data=data)


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------
def _create_ticket(
    conn: sqlite3.Connection,
    customer_id: str,
    subject: str,
    priority: str = "normal",
    reason: str = "support",
    session_id: Optional[str] = None,
) -> ToolResult:
    """Open a human-support ticket (complaints, returns, handoffs, ...)."""
    if not customer_id:
        return ToolResult(ok=False, message="I need to know who you are before opening a ticket.")
    ticket_id = repo.create_ticket(
        conn,
        customer_id=customer_id,
        subject=subject[:200],
        priority=priority,
        reason=reason,
        session_id=session_id,
    )
    logger.info("Ticket #%d created (%s) for %s", ticket_id, reason, customer_id)
    return ToolResult(
        ok=True,
        message=f"I've opened ticket #{ticket_id} for you.",
        data={"ticket_id": ticket_id, "priority": priority, "reason": reason},
    )


# ---------------------------------------------------------------------------
# create_lead
# ---------------------------------------------------------------------------
def _create_lead(
    conn: sqlite3.Connection,
    company: str,
    contact_name: Optional[str] = None,
    email: Optional[str] = None,
    product_interest: Optional[str] = None,
    quantity: Optional[int] = None,
    budget: Optional[str] = None,
    timeline: Optional[str] = None,
    notes: Optional[str] = None,
) -> ToolResult:
    """Store a qualified B2B lead - the sales team takes it from here."""
    if not company:
        return ToolResult(ok=False, message="A company name is required to save a business inquiry.")
    lead_id = repo.create_lead(
        conn,
        company=company[:200],
        contact_name=contact_name,
        email=email,
        product_interest=product_interest,
        quantity=quantity,
        budget=budget,
        timeline=timeline,
        notes=notes,
    )
    logger.info("Lead #%d created for %s (qty=%s)", lead_id, company, quantity)
    return ToolResult(
        ok=True,
        message=f"Thank you - I've saved your inquiry as lead #{lead_id}. Our B2B team will "
        "send a quotation within one business day.",
        data={"lead_id": lead_id, "company": company, "quantity": quantity},
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
register(ToolSpec(
    name="check_order",
    description="Look up an order's status, carrier, ETA and items by order id.",
    sensitive=False,
    params={"order_id": "numeric order id from the customer message", "customer_id": "session customer, for privacy check"},
    fn=_check_order,
))
register(ToolSpec(
    name="cancel_order",
    description="Cancel an order (only pending_payment/processing). SENSITIVE: confirm with the customer first.",
    sensitive=True,
    params={"order_id": "numeric order id", "customer_id": "session customer, for privacy check"},
    fn=_cancel_order,
))
register(ToolSpec(
    name="find_product",
    description="Fuzzy product lookup by name/brand; returns price, stock and warranty.",
    sensitive=False,
    params={"query": "product words as the customer said them"},
    fn=_find_product,
))
register(ToolSpec(
    name="create_ticket",
    description="Open a human support ticket (complaint, return, handoff, payment).",
    sensitive=False,
    params={"customer_id": "customer", "subject": "short summary", "priority": "low|normal|high", "reason": "category"},
    fn=_create_ticket,
))
register(ToolSpec(
    name="create_lead",
    description="Save a qualified B2B sales lead with company, contact, product and quantity.",
    sensitive=False,
    params={"company": "company name", "contact_name": "person", "email": "email", "product_interest": "product", "quantity": "units"},
    fn=_create_lead,
))
