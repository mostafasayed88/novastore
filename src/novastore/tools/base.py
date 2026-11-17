"""Tool infrastructure.

A "tool" is a Python function that reads or changes real store state.
The LLM NEVER calls tools directly (brief: "Tools do the side effects;
the LLM does not") - handlers call them after deciding that's what the
intent requires. This module defines the shared result type and registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import sqlite3


@dataclass(frozen=True)
class ToolSpec:
    """Documentation + behavior for one tool."""

    name: str
    description: str
    sensitive: bool  # True = money/state-changing: needs customer confirmation first
    params: dict[str, str]  # param name -> short description
    fn: Callable[..., "ToolResult"]


@dataclass
class ToolResult:
    """What every tool returns. ``ok=False`` is a normal, expected outcome -
    handlers turn it into an honest "I couldn't do that" message."""

    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    """Add a tool to the registry (called at import time in store_tools)."""
    REGISTRY[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec:
    if name not in REGISTRY:
        raise KeyError(f"Unknown tool '{name}'. Registered: {sorted(REGISTRY)}")
    return REGISTRY[name]


def run_tool(name: str, conn: sqlite3.Connection, **kwargs: Any) -> ToolResult:
    """Execute a tool by name with keyword arguments. Returns ToolResult;
    unexpected exceptions become ok=False instead of crashing the chat."""
    spec = get_tool(name)
    try:
        return spec.fn(conn, **kwargs)
    except Exception as exc:  # noqa: BLE001 - tools must never crash the agent
        from novastore.logging_setup import get_logger

        get_logger(__name__).exception("Tool %s crashed", name)
        return ToolResult(ok=False, message=f"Tool '{name}' failed: {exc}")
