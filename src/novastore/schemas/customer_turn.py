"""Pydantic contracts for the NLU layer.

``CustomerTurn`` is the heart of Sprint 03-04: it is the *structured*
representation of one customer message. A free-form paragraph goes in,
a validated object comes out - or nothing comes out at all (fail closed).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# NOTE: this list mirrors the project brief exactly. When you add an intent,
# update: this enum, the classifier prompt, and the router. Three places -
# a test in tests/test_classifier.py keeps them in sync.
VALID_INTENTS = [
    "order_tracking",
    "cancel_order",
    "return_request",
    "refund_request",
    "product_question",
    "availability_check",
    "shipping_info",
    "warranty_question",
    "complaint",
    "tech_support",
    "sales_inquiry",
    "human_handoff",
    "unknown",
]


class Intent(str, Enum):
    """What the customer wants, as a closed set the code can act on."""

    ORDER_TRACKING = "order_tracking"
    CANCEL_ORDER = "cancel_order"
    RETURN_REQUEST = "return_request"
    REFUND_REQUEST = "refund_request"
    PRODUCT_QUESTION = "product_question"
    AVAILABILITY_CHECK = "availability_check"
    SHIPPING_INFO = "shipping_info"
    WARRANTY_QUESTION = "warranty_question"
    COMPLAINT = "complaint"
    TECH_SUPPORT = "tech_support"
    SALES_INQUIRY = "sales_inquiry"
    HUMAN_HANDOFF = "human_handoff"
    UNKNOWN = "unknown"


class Slots(BaseModel):
    """Facts explicitly present in the message - never invented.

    Inventing an order ID is forbidden (project brief). The classifier is
    allowed to fill these ONLY from text that literally appears in the
    message; ``Classifier`` applies a regex guard as a second line of defense.
    """

    order_id: Optional[str] = Field(default=None, description="Numeric order id, only if present in the message")
    product_name: Optional[str] = Field(default=None, description="Product as the customer named it")
    quantity: Optional[int] = Field(default=None, ge=1, description="Number of units requested (sales)")
    issue: Optional[str] = Field(default=None, description="Short summary of a problem the customer reports")

    model_config = {"extra": "forbid"}


class CustomerTurn(BaseModel):
    """One classified customer message.

    Invariants enforced here and in the classifier:
    * ``confidence`` is always a float in [0, 1].
    * ``raw_message`` is the untouched original text (audit trail).
    * A turn is never silently "best effort": if parsing failed, the
      classifier constructs UNKNOWN with confidence 0.0 (fail closed).
    """

    intent: Intent = Intent.UNKNOWN
    slots: Slots = Field(default_factory=Slots)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    language: Optional[str] = Field(default=None, description="'en', 'ar', ... when detectable")
    clarifying_question: Optional[str] = Field(
        default=None, description="Question to ask the customer when the model is unsure"
    )
    raw_message: str = ""

    @field_validator("raw_message")
    @classmethod
    def _raw_required(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("raw_message must be a string")
        return v

    model_config = {"extra": "forbid"}
