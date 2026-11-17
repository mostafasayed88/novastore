#!/usr/bin/env python
"""List the models your Groq API key can currently use.

Run this when you see a model-not-found error from Groq, then put one of
the printed ids into GROQ_MODEL in .env:

    python scripts/list_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novastore.config import get_settings
from novastore.llm.client import GroqClient


def main() -> int:
    settings = get_settings()
    if not settings.groq_api_key:
        print("No GROQ_API_KEY found in .env - add it first (see SETUP.md step 6).")
        return 1

    client = GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)
    try:
        models = client.list_models()
    except Exception as exc:
        print(f"Could not reach Groq: {exc}")
        return 1

    print(f"Models available to your key ({len(models)}):")
    for model_id in models:
        marker = "   <-- current GROQ_MODEL" if model_id == settings.groq_model else ""
        print(f"  - {model_id}{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
