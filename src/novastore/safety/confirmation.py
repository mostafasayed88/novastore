"""Confirmation state machine for sensitive actions.

Rule from the brief: *confirm before cancel or refund*. The flow:

1. Handler decides an action is sensitive -> saves a ``pending_actions``
   row (what would be done, on which object) and ASKS the customer.
2. Next message goes through :func:`classify_confirmation` BEFORE normal
   routing:
     - affirmative  -> execute the stored action
     - negative     -> clear the pending action, do nothing
     - neither      -> treat the message as a fresh turn; a clear new
                       intent wins over the stale question, so customers
                       are never trapped in a yes/no loop.
"""

from __future__ import annotations

import re

# Spanish/Arabic/English affirmative and negative leads. Anchored at the
# start of the message so "yes" inside a longer sentence does not misfire.
_AFFIRMATIVE = re.compile(
    r"^\s*(yes|y|yeah|yep|yup|sure|ok(ay)?|confirmed?|please\s+do|go\s+ahead|"
    r"do\s+it|that'?s\s+correct|correct|نعم|اجل|أجل|ايوه|أيوه|تمام|اتفقنا|موافق)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"^\s*(no|n|nope|nah|don'?t|do\s*not|stop|abort|never\s*mind|forget\s*it|"
    r"cancel\s+that|keep\s+it|لا|لأ|الغاء|إلغاء|الغِ|لاشكرا)\b",
    re.IGNORECASE,
)


def is_affirmative(text: str) -> bool:
    return bool(_AFFIRMATIVE.match(text or ""))


def is_negative(text: str) -> bool:
    return bool(_NEGATIVE.match(text or ""))


def classify_confirmation(text: str) -> str:
    """Return 'affirmative' | 'negative' | 'unrelated'."""
    if is_affirmative(text):
        return "affirmative"
    if is_negative(text):
        return "negative"
    return "unrelated"
