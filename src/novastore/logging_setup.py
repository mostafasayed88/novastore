"""Central logging setup.

Principles:
* One formatter, two sinks: console + rotating file (logs/novastore.log).
* Never log secrets: only this module configures handlers, and no module
  is allowed to log settings values.
* Libraries (httpx, uvicorn) stay noisier than us; we raise their level.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

_CONFIGURED = False

FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging exactly once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    from novastore.config import PROJECT_ROOT

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    try:
        logs_dir = PROJECT_ROOT / "logs"
        logs_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / "novastore.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(file_handler)
    except OSError:
        # Read-only filesystem (some deployments) - console logging still works.
        root.warning("Could not open log file; logging to console only.")

    # Third-party noise control
    for noisy in ("httpx", "httpcore", "urllib3", "streamlit"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper so modules can just call get_logger(__name__)."""
    return logging.getLogger(name)
