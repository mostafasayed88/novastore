"""FastAPI application factory (Sprint 11).

Startup sequence (lifespan):
    1. configure logging
    2. create/verify the SQLite schema, auto-seed demo data if empty
    3. build the RAG index from data/knowledge/*.md
    4. construct the LLM client (Groq or Mock) and the NovaAgent

The agent lives on ``app.state.agent``; routes pull it via Depends.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from novastore.config import get_settings
from novastore.db.database import connect_ctx, init_db, is_seeded
from novastore.db.seed import seed_demo
from novastore.logging_setup import get_logger, setup_logging
from novastore.rag.retriever import Retriever

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        init_db(settings.db_path)
        with connect_ctx(settings.db_path) as conn:
            if seed_demo(conn):
                logger.info("Auto-seeded demo data on startup.")
        retriever = Retriever(
            settings.knowledge_dir,
            top_k=settings.retrieval_top_k,
            min_score=settings.retrieval_min_score,
        )
        from novastore.agent.agent import NovaAgent
        from novastore.llm.client import make_llm

        llm = make_llm(settings)
        app.state.agent = NovaAgent(settings, llm, settings.db_path, retriever)
        app.state.settings = settings
        logger.info("NovaStore API ready (model=%s, mock=%s)", settings.groq_model, settings.use_mock_llm)
        yield
        logger.info("NovaStore API shutting down.")

    app = FastAPI(
        title="NovaStore AI Customer Support & Sales Agent",
        description="Learning project: a production-style support + sales agent for a fictional "
        "electronics store. Chat endpoint for any channel; admin endpoints for the dashboard.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Local dev convenience: Streamlit runs on another port.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from novastore.api.routes import router

    app.include_router(router)
    return app


app = create_app()
