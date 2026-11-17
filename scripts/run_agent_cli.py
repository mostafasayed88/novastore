#!/usr/bin/env python
"""Terminal demo of the NovaStore agent (no UI needed).

    python scripts/run_agent_cli.py

Type messages, press Enter; type 'quit' to exit. Uses the same NovaAgent
as the HTTP API, so everything you see here also works in the web chat.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novastore.config import get_settings
from novastore.db.database import connect_ctx, init_db
from novastore.db.seed import seed_demo
from novastore.llm.client import make_llm
from novastore.logging_setup import setup_logging
from novastore.rag.retriever import Retriever


def main() -> int:
    setup_logging("WARNING")  # keep the terminal clean for the conversation
    settings = get_settings()
    init_db(settings.db_path)
    with connect_ctx(settings.db_path) as conn:
        seed_demo(conn)

    retriever = Retriever(
        settings.knowledge_dir,
        top_k=settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )
    from novastore.agent.agent import NovaAgent

    agent = NovaAgent(settings, make_llm(settings), settings.db_path, retriever)

    session_id = "sess_cli_1"
    customer_id = "cust_001"  # Ahmed Hassan - has order 5482 (shipped)

    print("=" * 62)
    print("NovaStore CLI demo  |  customer: Ahmed (cust_001)  |  'quit' exits")
    print("Try: 'Where is order 5482?' or 'I want 30 laptops for my company'")
    print("=" * 62)

    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return 0
        if not message:
            continue
        if message.lower() in {"quit", "exit", "q"}:
            print("Bye!")
            return 0

        reply = agent.run(session_id, customer_id, message)
        print(f"\nAgent: {reply.reply}")
        extras = []
        if reply.ticket_id:
            extras.append(f"ticket #{reply.ticket_id}")
        if reply.lead_id:
            extras.append(f"lead #{reply.lead_id}")
        if reply.handoff:
            extras.append("HUMAN HANDOFF")
        if reply.citations:
            extras.append("sources: " + ", ".join(c.doc for c in reply.citations))
        if extras:
            print(f"       [{', '.join(extras)}]")


if __name__ == "__main__":
    raise SystemExit(main())
