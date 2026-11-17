"""LLM provider layer.

The rest of the app NEVER talks to Groq directly. It talks to the small
``LLMClient`` protocol below, so the vendor can be swapped without touching
any other file (project brief: "wrapped behind a small client").

Two implementations ship:

* ``GroqClient`` - real HTTP calls to Groq's OpenAI-compatible chat API,
  using JSON mode (``response_format={"type": "json_object"}``).
* ``MockLLM`` - a tiny rule-based stand-in so tests, evals and offline
  demos run with zero API calls.

Fail-closed rule: ``chat_json`` returns ``None`` on ANY failure (network,
HTTP error, invalid JSON). Callers must treat ``None`` as "I don't know",
never as "make something up".
"""

from __future__ import annotations

import json
import re
from typing import Optional, Protocol

from novastore.config import Settings
from novastore.logging_setup import get_logger

logger = get_logger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


class LLMClient(Protocol):
    """Contract every provider must satisfy."""

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        task: str = "generic",
        temperature: Optional[float] = None,
    ) -> Optional[dict]:
        """Send one chat turn, expect a JSON object back.

        ``task`` is a semantic hint ("classify", "answer") used by the mock
        and useful for logs; real providers ignore it. Returns None on any
        failure - never raises for expected LLM hiccups.
        """
        ...


class GroqClient:
    """Minimal Groq chat-completions wrapper on plain httpx.

    Deliberately NOT the official SDK: Sprint 00-02 of this project teaches
    HTTP + JSON, and reading ~80 lines here teaches exactly how one LLM call
    works (auth header, payload, choices[0].message.content).
    """

    def __init__(self, api_key: str, model: str, default_temperature: float = 0.1, timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.default_temperature = default_temperature
        self.timeout = timeout

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        task: str = "generic",
        temperature: Optional[float] = None,
    ) -> Optional[dict]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.default_temperature if temperature is None else temperature,
            # JSON mode: the model must emit a JSON object. This is still a
            # *wish* - Pydantic validation downstream is the *constraint*.
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            import httpx

            response = httpx.post(GROQ_CHAT_URL, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                logger.warning("LLM task=%s returned non-object JSON; failing closed.", task)
                return None
            return parsed
        except json.JSONDecodeError:
            logger.warning("LLM task=%s returned invalid JSON; failing closed.", task)
            return None
        except Exception as exc:  # network, HTTP status, missing keys, ...
            logger.warning("LLM call failed (task=%s): %s", task, exc)
            return None

    def list_models(self) -> list[str]:
        """Live model list - used by scripts/list_models.py to debug 404s."""
        import httpx

        response = httpx.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return [m["id"] for m in response.json().get("data", [])]


class MockLLM:
    """Rule-based offline stand-in.

    It mimics the two call shapes the app really makes:

    * task="classify": keyword rules -> the same JSON the real classifier
      prompt asks for. This lets tests assert the FULL pipeline without a key.
    * task="answer": echoes the retrieved knowledge chunks into a plain
      answer, so the RAG path is exercised end-to-end offline.
    """

    # Ordered by priority: first keyword hit wins.
    _RULES: list[tuple[str, tuple[str, ...]]] = [
        ("human_handoff", ("human", "real person", "a person", "representative", "agent please", "موظف", "بشري")),
        ("cancel_order", ("cancel", "إلغاء", "الغي", "الغاء")),
        ("refund_request", ("refund", "money back", "استرداد", "استرجاع المبلغ")),
        ("return_request", ("return", "send it back", "send back", "exchange", "استبدال", "ارجاع", "إرجاع")),
        ("complaint", ("broken", "damaged", "terrible", "worst", "angry", "furious", "defective", "مكسور", "تالف")),
        ("tech_support", ("not working", "stopped working", "won't turn on", "wont turn on", "repair", "error", "install", "setup", "not connecting", "problem with", "issue with")),
        ("order_tracking", ("where is my order", "where is order", "track", "order status", "status of order", "delivery status", "when will my order", "has my order shipped", "طلبي", "وين طلبي")),
        ("availability_check", ("available", "in stock", "stock", "do you have", "متوفر", "متاح")),
        ("warranty_question", ("warranty", "guarantee", "ضمان")),
        ("shipping_info", ("how long does shipping", "shipping take", "delivery time", "delivery take", "how long to deliver", "how long does delivery", "ship to", "delivery to", "الشحن", "مدة التوصيل")),
        ("sales_inquiry", ("bulk", "wholesale", "for my company", "for my business", "our company", "quote", "b2b", "تسويق", "بالجملة")),
        ("product_question", ("price", "how much", "specs", "specifications", "features", "compare", "سعر", "كم")),
    ]

    _PRODUCT_KEYWORDS: dict[str, str] = {
        "iphone": "iPhone 15",
        "galaxy": "Galaxy S24",
        "xps": "Dell XPS 15",
        "macbook": "MacBook Air",
        "thinkpad": "Lenovo ThinkPad X1",
        "wh-1000": "Sony WH-1000XM5 Headphones",
        "headphone": "Sony WH-1000XM5 Headphones",
        "jbl": "JBL Flip 6 Speaker",
        "speaker": "JBL Flip 6 Speaker",
        "monitor": 'LG 27" UltraGear Monitor',
    }

    _ORDER_ID_RE = re.compile(r"order\s*(?:number|id|no\.?|#)?\s*#?\s*(\d{3,6})", re.IGNORECASE)
    _QTY_RE = re.compile(r"\b(\d{1,4})\s*(?:x\s+)?(?:units?|pieces?|pcs|laptops?|devices?)\b", re.IGNORECASE)
    # "30 Dell laptops" - a word can sit between the number and the noun.
    _QTY_RE2 = re.compile(r"\b(\d{1,4})\s+\w+\s+(?:units?|pieces?|pcs|laptops?|devices?)\b", re.IGNORECASE)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        task: str = "generic",
        temperature: Optional[float] = None,
    ) -> Optional[dict]:
        try:
            if task == "classify":
                return self._classify(user)
            if task == "answer":
                return self._answer(user)
            return {"action": "clarify", "answer": "", "ask_user": "Could you tell me a bit more about that?"}
        except Exception as exc:  # keep the same fail-closed contract
            logger.warning("MockLLM failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # classify
    # ------------------------------------------------------------------
    def _classify(self, user_payload: str) -> dict:
        # The real classifier embeds the raw message in a JSON payload;
        # recover it (fall back to the whole string).
        message = user_payload
        try:
            data = json.loads(user_payload)
            message = data.get("message", message)
            history = data.get("recent_history", [])
        except (json.JSONDecodeError, AttributeError):
            history = []

        lowered = message.lower()

        intent, confidence = "unknown", 0.2
        for name, keywords in self._RULES:
            if any(k in lowered for k in keywords):
                intent, confidence = name, 0.9
                break
        # Two-word pattern the flat keyword list cannot express: "send X back".
        if intent == "unknown" and "send" in lowered and re.search(r"\bback\b", lowered):
            intent, confidence = "return_request", 0.85

        slots: dict = {}
        m = self._ORDER_ID_RE.search(message)
        if m:
            slots["order_id"] = m.group(1)
        m = self._QTY_RE.search(message) or self._QTY_RE2.search(message)
        if m:
            slots["quantity"] = int(m.group(1))
        for keyword, product in self._PRODUCT_KEYWORDS.items():
            if keyword in lowered:
                slots["product_name"] = product
                break
        if intent in {"complaint", "tech_support"}:
            slots["issue"] = message[:80]

        # A bare order number with no other intent hit is almost always tracking.
        if intent == "unknown" and "order_id" in slots:
            intent, confidence = "order_tracking", 0.75

        # A quantity >= 5 with no better hit smells like B2B sales.
        if intent == "product_question" and slots.get("quantity", 0) and slots["quantity"] >= 5:
            intent, confidence = "sales_inquiry", 0.8

        result = {
            "intent": intent,
            "confidence": confidence,
            "slots": slots,
            "language": "ar" if re.search(r"[\u0600-\u06FF]", message) else "en",
        }
        if intent == "unknown":
            # Add a tiny bit of context awareness: if the last product is known,
            # a bare follow-up like "and the warranty?" still gets a real intent.
            if history:
                result["clarifying_question"] = (
                    "Just to make sure I understand - could you rephrase that? "
                    "For example: 'Where is my order?', 'Is iPhone 15 available?', "
                    "'What is the return policy?'"
                )
            else:
                result["clarifying_question"] = (
                    "I'm not sure I understood. Could you tell me what you need - "
                    "for example an order update, product info, or a human agent?"
                )
        return result

    # ------------------------------------------------------------------
    # answer
    # ------------------------------------------------------------------
    def _answer(self, user_payload: str) -> dict:
        try:
            data = json.loads(user_payload)
        except (json.JSONDecodeError, AttributeError):
            return {"action": "clarify", "answer": "", "ask_user": "Could you rephrase that?"}

        retrieved = data.get("store_docs") or data.get("retrieved") or []
        facts = data.get("product_facts") or {}

        parts: list[str] = []
        if facts:
            facts_line = ", ".join(f"{k}: {v}" for k, v in facts.items() if v is not None)
            parts.append(f"Product facts - {facts_line}.")
        if retrieved:
            chunk_text = str(retrieved[0].get("text", ""))[:400]
            parts.append(f"From our store docs ({retrieved[0].get('doc', 'knowledge base')}): {chunk_text}")
            return {
                "action": "answer",
                "answer": " ".join(parts),
                "citations": [{"doc": retrieved[0].get("doc", ""), "title": retrieved[0].get("title", "")}],
            }
        return {
            "action": "clarify",
            "answer": "",
            "ask_user": "I don't have that in my store knowledge yet - could you ask in a different way?",
        }


def make_llm(settings: Settings) -> LLMClient:
    """Factory used at startup (FastAPI lifespan, scripts, tests).

    Raises a clear, actionable error when a real key is required but absent,
    instead of failing later with an obscure 401.
    """
    if settings.use_mock_llm:
        logger.info("Using MockLLM (USE_MOCK_LLM=true) - no network calls will be made.")
        return MockLLM()
    if not settings.groq_api_key:
        raise RuntimeError(
            "No Groq API key found. Either set GROQ_API_KEY in your .env file "
            "(see SETUP.md, step 6) or set USE_MOCK_LLM=true to run offline."
        )
    logger.info("Using Groq model=%s", settings.groq_model)
    return GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        default_temperature=settings.llm_temperature,
    )
