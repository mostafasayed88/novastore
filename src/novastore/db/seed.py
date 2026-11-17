"""Demo seed data for NovaStore.

All names, emails, prices and order ids are FICTIONAL, created for this
learning project. Prices are in EGP to match a Cairo-based store.

``seed_demo`` is idempotent: calling it twice does not duplicate data.
Use ``force=True`` (or ``python scripts/seed_db.py --force``) to wipe and
reseed - handy while iterating on the demo data.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from novastore.logging_setup import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Reference "today" so relative dates in seed data stay stable-ish.
# ---------------------------------------------------------------------------
_TODAY = datetime(2026, 11, 15)


def _d(offset_days: int) -> str:
    return (_TODAY + timedelta(days=offset_days)).strftime("%Y-%m-%d")


CUSTOMERS = [
    ("cust_001", "Ahmed Hassan", "ahmed.hassan@example.com", "+20-100-111-0001", "retail"),
    ("cust_002", "Sara Ibrahim", "sara.ibrahim@example.com", "+20-100-111-0002", "retail"),
    ("cust_003", "Omar Khaled", "omar.khaled@nitetech.example.com", "+20-100-111-0003", "business"),
    ("cust_004", "Laila Mostafa", "laila.mostafa@example.com", "+20-100-111-0004", "retail"),
    ("cust_005", "Youssef Adel", "youssef.adel@deltafirms.example.com", "+20-100-111-0005", "business"),
    ("cust_006", "Mona Samir", "mona.samir@example.com", "+20-100-111-0006", "retail"),
]

PRODUCTS = [
    ("IP15-128", "iPhone 15", "Apple", "Smartphones", 32999.0, 7, 12, "Apple iPhone 15, 128GB, USB-C, A16 chip."),
    ("GS24-256", "Galaxy S24", "Samsung", "Smartphones", 27999.0, 12, 12, "Samsung Galaxy S24, 256GB, AI features."),
    ("XPS15-OLED", "Dell XPS 15", "Dell", "Laptops", 74999.0, 3, 24, "Dell XPS 15, Intel Core Ultra, OLED display, 32GB RAM."),
    ("MBA13-M3", "MacBook Air 13 M3", "Apple", "Laptops", 58999.0, 5, 12, 'Apple MacBook Air 13" with M3 chip, 16GB RAM.'),
    ("TPX1C-G11", "Lenovo ThinkPad X1 Carbon", "Lenovo", "Laptops", 66999.0, 9, 36, "Lenovo ThinkPad X1 Carbon Gen 11, business laptop."),
    ("SONYXM5", "Sony WH-1000XM5 Headphones", "Sony", "Audio", 13999.0, 0, 12, "Sony WH-1000XM5 noise-cancelling over-ear headphones."),
    ("JBLF6", "JBL Flip 6 Speaker", "JBL", "Audio", 5499.0, 22, 12, "JBL Flip 6 portable Bluetooth speaker, IP67."),
    ("LG27UG", 'LG 27" UltraGear Monitor', "LG", "Monitors", 11999.0, 14, 24, 'LG 27" UltraGear 144Hz gaming monitor.'),
]

# (order_id, customer_id, status, placed_offset_days, city, carrier, tracking, eta_offset_or_None, [(sku, qty)])
ORDERS = [
    ("5482", "cust_001", "shipped", -2, "Cairo", "Bosta", "BST-7741-CA", 2, [("IP15-128", 1)]),
    ("5103", "cust_002", "delivered", -9, "Giza", "Bosta", "BST-5120-GZ", None, [("JBLF6", 1)]),
    ("5391", "cust_003", "processing", -1, "Cairo", "Aramex", "ARX-2260-CA", None, [("TPX1C-G11", 3)]),
    ("5220", "cust_004", "pending_payment", -3, "Alexandria", "Mylerz", "MYL-9032-AL", None, [("SONYXM5", 1)]),
    ("5488", "cust_005", "shipped", -4, "Mansoura", "Aramex", "ARX-8817-MN", 1, [("XPS15-OLED", 1)]),
    ("5001", "cust_006", "delivered", -15, "Aswan", "Bosta", "BST-3305-AS", None, [("GS24-256", 1)]),
    ("5117", "cust_001", "cancelled", -20, "Cairo", None, None, None, [("GS24-256", 1)]),
    ("5304", "cust_002", "shipped", -6, "Giza", "Bosta", "BST-6623-GZ", 1, [("MBA13-M3", 1)]),
    ("5045", "cust_003", "delivered", -12, "Cairo", "Aramex", "ARX-1044-CA", None, [("LG27UG", 2)]),
    ("5460", "cust_004", "processing", -1, "Alexandria", "Mylerz", "MYL-7715-AL", None, [("IP15-128", 1)]),
]

TICKETS = [
    ("cust_002", "sess_demo_001", "Return request for order 5103 - box damaged", "normal", "in_progress", "return"),
    ("cust_005", "sess_demo_002", "Invoice needs company VAT details", "high", "open", "payment"),
]

LEADS = [
    ("Delta Firms Ltd.", "Youssef Adel", "youssef.adel@deltafirms.example.com",
     "Lenovo ThinkPad X1 Carbon", 25, "EGP 60k-70k per unit", "This quarter", "qualified"),
]


def seed_demo(conn: sqlite3.Connection, *, force: bool = False) -> bool:
    """Insert demo data. Returns True if seeding happened.

    Idempotent: skips when data already exists unless force=True.
    Expects a connection whose schema already exists (see scripts/seed_db.py).
    """
    has_data = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0
    if has_data and not force:
        logger.info("Database already seeded - skipping (use --force to reset).")
        return False

    # Wipe in FK-safe order so force reseeds cleanly.
    for table in ("conversations", "pending_actions", "session_state", "order_items", "orders",
                  "tickets", "leads", "products", "customers"):
        conn.execute(f"DELETE FROM {table};")

    conn.executemany(
        "INSERT INTO customers (id, name, email, phone, type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(cid, name, email, phone, ctype, _d(-180)) for cid, name, email, phone, ctype in CUSTOMERS],
    )
    conn.executemany(
        """INSERT INTO products
               (sku, name, brand, category, price_egp, stock, warranty_months, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        PRODUCTS,
    )

    for oid, cust, status, off, city, carrier, tracking, eta, items in ORDERS:
        total = 0.0
        for sku, qty in items:
            price = next(p[4] for p in PRODUCTS if p[0] == sku)
            total += price * qty
        conn.execute(
            """INSERT INTO orders
                   (order_id, customer_id, status, placed_at, shipping_city, carrier, tracking_code, eta, total_egp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (oid, cust, status, _d(off), city, carrier, tracking, _d(eta) if eta is not None else None, total),
        )
        for sku, qty in items:
            price = next(p[4] for p in PRODUCTS if p[0] == sku)
            conn.execute(
                "INSERT INTO order_items (order_id, sku, qty, unit_price) VALUES (?, ?, ?, ?)",
                (oid, sku, qty, price),
            )

    for cust, sess, subject, prio, status, reason in TICKETS:
        conn.execute(
            """INSERT INTO tickets (customer_id, session_id, subject, priority, status, reason, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cust, sess, subject, prio, status, reason, _d(-2), _d(-2)),
        )

    for company, name, email, product, qty, budget, timeline, status in LEADS:
        conn.execute(
            """INSERT INTO leads (company, contact_name, email, product_interest, quantity,
                                  budget, timeline, status, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company, name, email, product, qty, budget, timeline, status, "Seeded demo lead", _d(-5)),
        )

    logger.info("Seeded demo data: %d customers, %d products, %d orders.", len(CUSTOMERS), len(PRODUCTS), len(ORDERS))
    return True
