"""Shared pytest fixtures.

The whole suite runs OFFLINE: the agent fixture uses MockLLM and a fresh
temporary SQLite database per test, so tests never touch your real DB or
spend API tokens.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make 'import novastore' work without pip install, and force the API test
# app (created later inside test functions) into mock mode with its own DB.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("USE_MOCK_LLM", "true")
_API_TMP = tempfile.mkdtemp(prefix="novastore_api_test_")
os.environ.setdefault("DB_PATH", str(Path(_API_TMP) / "api_test.db"))

import pytest  # noqa: E402

from novastore.config import PROJECT_ROOT, Settings  # noqa: E402
from novastore.db.database import connect_ctx, init_db  # noqa: E402
from novastore.db.seed import seed_demo  # noqa: E402
from novastore.llm.client import MockLLM  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path: Path):
    """A fresh, seeded database file for one test."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with connect_ctx(db_path) as conn:
        seed_demo(conn, force=True)
    return db_path


@pytest.fixture()
def settings(tmp_db) -> Settings:
    return Settings(
        use_mock_llm=True,
        db_path=tmp_db,
        knowledge_dir=PROJECT_ROOT / "data" / "knowledge",
    )


@pytest.fixture()
def agent(settings):
    """A full NovaAgent wired to MockLLM + temp DB + real knowledge docs."""
    from novastore.agent.agent import NovaAgent
    from novastore.rag.retriever import Retriever

    retriever = Retriever(
        settings.knowledge_dir,
        top_k=settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )
    return NovaAgent(settings, MockLLM(), settings.db_path, retriever)


class BrokenLLM:
    """Simulates the provider returning nothing at all."""

    def chat_json(self, *, system, user, task="generic", temperature=None):
        return None


class GarbageLLM:
    """Simulates the provider returning JSON that breaks the contract."""

    def chat_json(self, *, system, user, task="generic", temperature=None):
        return {"intent": "flying_pigs", "confidence": "very high", "slots": ["nope"]}
