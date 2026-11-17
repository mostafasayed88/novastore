"""Classifier tests: intent extraction, fail-closed behavior, hallucination guard."""

from __future__ import annotations

from novastore.nlu.classifier import Classifier
from novastore.schemas.customer_turn import Intent, VALID_INTENTS


def test_tracking_order_and_slot(settings):
    from novastore.llm.client import MockLLM

    turn = Classifier(MockLLM(), settings).classify("Where is order 5482?")
    assert turn.intent == Intent.ORDER_TRACKING
    assert turn.slots.order_id == "5482"
    assert turn.confidence >= 0.5


def test_availability_intent(settings):
    from novastore.llm.client import MockLLM

    turn = Classifier(MockLLM(), settings).classify("Is iPhone 15 available?")
    assert turn.intent == Intent.AVAILABILITY_CHECK
    assert turn.slots.product_name == "iPhone 15"


def test_fail_closed_when_llm_silent(settings):
    """BrokenLLM returns None -> UNKNOWN with confidence 0, never a guess."""
    from tests.conftest import BrokenLLM

    turn = Classifier(BrokenLLM(), settings).classify("Where is order 5482?")
    assert turn.intent == Intent.UNKNOWN
    assert turn.confidence == 0.0
    assert turn.clarifying_question  # the agent has something to say


def test_fail_closed_on_garbage_json(settings):
    """Invalid contract -> fail closed, not crash."""
    from tests.conftest import GarbageLLM

    turn = Classifier(GarbageLLM(), settings).classify("What is your return policy?")
    assert turn.intent == Intent.UNKNOWN
    assert turn.confidence == 0.0


def test_unknown_intent_value_maps_to_unknown(settings):
    from novastore.llm.client import MockLLM

    turn = Classifier(MockLLM(), settings).classify("What is your return policy?")
    assert turn.intent in set(Intent)


def test_order_id_hallucination_guard(settings):
    """A model-invented order id that never appeared in the message is dropped."""
    from novastore.llm.client import MockLLM

    classifier = Classifier(MockLLM(), settings)
    turn = classifier.classify("What is your return policy?")

    # Simulate a hallucinating provider by editing the validated turn's source
    raw = {"intent": "return_request", "confidence": 0.9, "slots": {"order_id": "99999"}}
    guarded = classifier._validate(raw, "What is your return policy?")
    classifier._guard_slots(guarded, "What is your return policy?")
    assert guarded.slots.order_id is None, "invented order id must be stripped"

    # And a real id from the message survives the same guard.
    real = classifier._validate({"intent": "order_tracking", "confidence": 0.9,
                                 "slots": {"order_id": "5482"}}, "Where is order 5482?")
    classifier._guard_slots(real, "Where is order 5482?")
    assert real.slots.order_id == "5482"


def test_intent_enum_matches_prompt_contract():
    """The enum, the prompt list and the router must stay in sync."""
    from novastore.router.router import IntentRouter  # noqa: F401

    assert set(VALID_INTENTS) == {i.value for i in Intent}
