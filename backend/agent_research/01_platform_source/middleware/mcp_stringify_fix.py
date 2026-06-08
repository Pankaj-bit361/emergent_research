"""MCP middleware to fix stringified JSON arguments.

When an LLM model sends tool arguments as JSON strings instead of dicts
(e.g. '{"path": "/root/file"}' instead of {"path": "/root/file"}),
FastMCP's Pydantic validation rejects them before our tool code runs.

This middleware intercepts on_call_tool and parses whitelisted string
arguments that are valid JSON dicts/lists back into their native types.

Only applies to fields that expect structured types (List, Dict, Union).
String-typed fields like file_text are left alone — otherwise JSON content
meant to be written as a file gets parsed into a dict.

See: https://github.com/anthropics/claude-code/issues/3084
"""

import json

from fastmcp.server.middleware import Middleware, MiddlewareContext
from plugins.tools.agent.logger import logger

# Fields that expect structured types (list/dict) and may arrive as
# stringified JSON from certain LLM providers.
_STRINGIFY_FIX_FIELDS = {
    "files",       # bulk_file_writer: List[BulkFileItem]
    "request",     # read: Union[ViewRequest, List[ViewRequest]]
    "edits",       # multi_search_replace: List[EditOperation]
}


class MCPStringifyFixMiddleware(Middleware):
    """Parse stringified JSON arguments before Pydantic validation."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        arguments = context.message.arguments
        if arguments:
            for key, value in arguments.items():
                if key not in _STRINGIFY_FIX_FIELDS:
                    continue
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, (dict, list)):
                            arguments[key] = parsed
                            logger.info(
                                f"Stringify fix: parsed string arg '{key}' "
                                f"for tool '{context.message.name}'"
                            )
                    except (json.JSONDecodeError, TypeError):
                        pass
        return await call_next(context)
