#!/usr/bin/env python
"""Create and seed the NovaStore SQLite database.

Run this FIRST (or after changing the demo data):

    python scripts/seed_db.py            # seeds only if DB is empty
    python scripts/seed_db.py --force    # wipe and reseed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make 'import novastore' work even without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novastore.config import get_settings
from novastore.db.database import connect_ctx, init_db, is_seeded
from novastore.db.seed import seed_demo


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the NovaStore demo database.")
    parser.add_argument("--force", action="store_true", help="wipe existing data and reseed")
    args = parser.parse_args()

    settings = get_settings()
    init_db(settings.db_path)

    if is_seeded(settings.db_path) and not args.force:
        print(f"Database already seeded at {settings.db_path} (use --force to reset).")
        return 0

    with connect_ctx(settings.db_path) as conn:
        seed_demo(conn, force=args.force)

    print(f"Seeded: {settings.db_path}")
    print("  6 customers   (ids cust_001 ... cust_006)")
    print("  8 products    (iPhone 15, Galaxy S24, Dell XPS 15, ...)")
    print("  10 orders     (incl. 5482 = shipped iPhone order)")
    print("  2 tickets, 1 lead")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
