"""Application configuration.

Every tunable value lives here and comes from one of three places,
in order of priority:

1. Real environment variables (set in the shell, or by Docker)
2. A ``.env`` file at the project root (loaded by python-dotenv)
3. Sensible defaults defined in this module

Production rule from the project brief:
    *No API keys in source.* This module is the ONLY place that touches
    secrets, and it never prints or logs them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# The project root is two levels above this file:
#   <root>/src/novastore/config.py  ->  parents[2] == <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load .env once, if it exists. Real env vars still win.
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    """Read a string env var with a default."""
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of configuration for one process run."""

    # LLM provider
    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY") or None)
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "openai/gpt-oss-120b"))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.1))
    use_mock_llm: bool = field(default_factory=lambda: _env_bool("USE_MOCK_LLM", False))

    # Storage
    db_path: Path = field(default_factory=lambda: (PROJECT_ROOT / _env("DB_PATH", "data/novastore.db")).resolve())
    knowledge_dir: Path = field(
        default_factory=lambda: (PROJECT_ROOT / _env("KNOWLEDGE_DIR", "data/knowledge")).resolve()
    )

    # Retrieval
    retrieval_top_k: int = field(default_factory=lambda: _env_int("RETRIEVAL_TOP_K", 4))
    retrieval_min_score: float = field(default_factory=lambda: _env_float("RETRIEVAL_MIN_SCORE", 0.05))

    # Agent confidence policy
    confidence_clarify_below: float = field(default_factory=lambda: _env_float("CONFIDENCE_CLARIFY_BELOW", 0.45))
    confidence_handoff_below: float = field(default_factory=lambda: _env_float("CONFIDENCE_HANDOFF_BELOW", 0.25))

    # HTTP
    api_host: str = field(default_factory=lambda: _env("API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: _env_int("API_PORT", 8000))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # UIs
    ui_api_url: str = field(default_factory=lambda: _env("UI_API_URL", "http://127.0.0.1:8000"))

    # WhatsApp stub (see docs/whatsapp.md)
    whatsapp_verify_token: str = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN", ""))
    whatsapp_token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN", ""))
    whatsapp_phone_number_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID", ""))

    @property
    def logs_dir(self) -> Path:
        return PROJECT_ROOT / "logs"


def get_settings() -> Settings:
    """Build a Settings object. Kept as a function so callers can
    monkeypatch environment variables in tests."""
    return Settings()


def missing_api_key(settings: Settings) -> bool:
    """True when we would need an API key but do not have one.

    The app never *crashes* on this inside a request; the factory in
    ``novastore.llm.client`` turns it into a clear error early at startup.
    """
    return not settings.use_mock_llm and not settings.groq_api_key
