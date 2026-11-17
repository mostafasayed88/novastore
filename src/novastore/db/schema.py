"""SQLite schema - the source of truth for everything the store owns.

Plain sqlite3 on purpose (no ORM): every query is visible, which is the
point of a learning product. Tables:

* customers    - who talks to the agent
* products     - catalog with stock + warranty months
* orders       - one row per order, with items in ``order_items``
* tickets      - human handoffs, complaints, tech support cases
* leads        - B2B sales qualification results
* conversations- full transcript (admin dashboard reads this)
* pending_actions - confirmation state for money-moving intents
* session_state   - per-session memory (last product, active lead flow)
"""

CUSTOMERS = """
CREATE TABLE IF NOT EXISTS customers (
    id          TEXT PRIMARY KEY,          -- 'cust_001', ...
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    phone       TEXT,
    type        TEXT NOT NULL DEFAULT 'retail',   -- 'retail' | 'business'
    created_at  TEXT NOT NULL
);
"""

PRODUCTS = """
CREATE TABLE IF NOT EXISTS products (
    sku             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL,
    category        TEXT NOT NULL,
    price_egp       REAL NOT NULL,
    stock           INTEGER NOT NULL DEFAULT 0,
    warranty_months INTEGER NOT NULL DEFAULT 12,
    description     TEXT NOT NULL DEFAULT ''
);
"""

ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    order_id      TEXT PRIMARY KEY,        -- '5482', ...
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    status        TEXT NOT NULL,           -- pending_payment|processing|shipped|delivered|cancelled|refund_requested
    placed_at     TEXT NOT NULL,
    shipping_city TEXT NOT NULL,
    carrier       TEXT,
    tracking_code TEXT,
    eta           TEXT,
    total_egp     REAL NOT NULL
);
"""

ORDER_ITEMS = """
CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   TEXT NOT NULL REFERENCES orders(order_id),
    sku        TEXT NOT NULL REFERENCES products(sku),
    qty        INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
"""

TICKETS = """
CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    session_id  TEXT,
    subject     TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal',   -- low|normal|high
    status      TEXT NOT NULL DEFAULT 'open',     -- open|in_progress|resolved
    reason      TEXT NOT NULL DEFAULT 'support',  -- complaint|tech_support|handoff|return|refund|payment|legal
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

LEADS = """
CREATE TABLE IF NOT EXISTS leads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company          TEXT NOT NULL,
    contact_name     TEXT,
    email            TEXT,
    product_interest TEXT,
    quantity         INTEGER,
    budget           TEXT,
    timeline         TEXT,
    status           TEXT NOT NULL DEFAULT 'new',  -- new|qualified|won|lost
    notes            TEXT,
    created_at       TEXT NOT NULL
);
"""

CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    role        TEXT NOT NULL,           -- 'customer' | 'agent'
    content     TEXT NOT NULL,
    intent      TEXT,
    confidence  REAL,
    created_at  TEXT NOT NULL
);
"""

CONVERSATIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
"""

PENDING_ACTIONS = """
CREATE TABLE IF NOT EXISTS pending_actions (
    session_id   TEXT PRIMARY KEY,
    action       TEXT NOT NULL,          -- 'confirm_cancel' | 'confirm_refund' | 'ticket_offer'
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
"""

SESSION_STATE = """
CREATE TABLE IF NOT EXISTS session_state (
    session_id TEXT PRIMARY KEY,
    data_json  TEXT NOT NULL            -- {'last_product': ..., 'flow': {...}}
);
"""

ALL_TABLES = [
    CUSTOMERS,
    PRODUCTS,
    ORDERS,
    ORDER_ITEMS,
    TICKETS,
    LEADS,
    CONVERSATIONS,
    CONVERSATIONS_INDEX,
    PENDING_ACTIONS,
    SESSION_STATE,
]
