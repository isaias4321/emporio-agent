"""Tool registry: schemas for the LLM + safe dispatcher."""
from __future__ import annotations

import json
from typing import Any

from src.tools.policy_tools import POLICY_TOOL_SCHEMAS, POLICY_TOOLS
from src.tools.store_tools import STORE_TOOL_SCHEMAS, STORE_TOOLS

TOOLS = {**STORE_TOOLS, **POLICY_TOOLS}
TOOL_SCHEMAS: list[dict[str, Any]] = STORE_TOOL_SCHEMAS + POLICY_TOOL_SCHEMAS


def execute_tool(name: str, arguments_json: str) -> str:
    """Run a tool by name; always returns a JSON string (errors included)."""
    fn = TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'."})
    try:
        args = json.loads(arguments_json or "{}")
        return json.dumps(fn(**args), ensure_ascii=False, default=str)
    except TypeError as exc:
        return json.dumps({"error": f"Invalid arguments: {exc}"})
    except Exception as exc:  # surfaced to the model so it can recover gracefully
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
