"""MCP output persistence middleware — saves full tool outputs to disk.

Uses a contextvars.ContextVar to pass persistence context (tool_name, request_id)
into tool handlers so that truncate_output() and inline truncation in execute_bash
can persist the FULL output BEFORE truncation happens.

The middleware also does a fallback persist on the response path for outputs that
weren't truncated (>= MIN_PERSIST_SIZE) but still worth saving.
"""

import contextvars
import os

from fastmcp.server.middleware import Middleware, MiddlewareContext
from plugins.tools.agent.logger import logger

MIN_PERSIST_SIZE = 1000
OUTPUT_DIR = "/root/.emergent/tool_outputs"

# Context var set by middleware, read by persist_full_output().
# Value is (tool_name, tool_call_id) or None.
_persist_ctx: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "_persist_ctx", default=None
)


def persist_full_output(text: str) -> None:
    """Persist full output to disk before truncation.

    Called from truncate_output() and execute_bash inline truncation.
    Only writes if the persistence middleware set _persist_ctx and len(text) >= MIN_PERSIST_SIZE.
    """
    ctx = _persist_ctx.get()
    if ctx is None:
        return
    tool_name, tool_call_id = ctx
    if not tool_call_id or not text or len(text) < MIN_PERSIST_SIZE:
        return
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = f"{OUTPUT_DIR}/{tool_name}-{tool_call_id}.output"
        with open(path, "w") as f:
            f.write(text)
        logger.info(f"Persisted full tool output ({len(text)} chars): {path}")
    except Exception:
        logger.warning("Failed to persist full tool output", exc_info=True)


class MCPOutputPersistenceMiddleware(Middleware):
    """Persist full tool outputs to disk before truncation.

    Writes every tool call's untruncated output to:
        /root/.emergent/tool_outputs/{tool_name}-{tool_call_id}.output

    Two persistence paths:
    1. PRE-TRUNCATION (preferred): Sets _persist_ctx before tool executes.
       truncate_output() and execute_bash call persist_full_output() with the
       full text before truncating. This captures the truly full output.
    2. FALLBACK: After tool returns, persists structured_content["output"] if
       >= MIN_PERSIST_SIZE and no file was already written by path 1.

    Pod death = natural cleanup.
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
        # Capture request_id before idempotency middleware pops it
        tool_call_id = (context.message.arguments or {}).get("request_id")

        # Set context var so persist_full_output() can write pre-truncation output
        token = _persist_ctx.set((tool_name, tool_call_id) if tool_call_id else None)
        try:
            result = await call_next(context)
        finally:
            _persist_ctx.reset(token)

        # Fallback: persist from structured_content if no file was written yet
        try:
            if not tool_call_id:
                return result

            path = f"{OUTPUT_DIR}/{tool_name}-{tool_call_id}.output"
            if os.path.exists(path):
                # Already persisted by persist_full_output() — skip
                return result

            output = ""
            if result.structured_content and isinstance(
                result.structured_content, dict
            ):
                output = result.structured_content.get("output", "")

            if output and len(output) >= MIN_PERSIST_SIZE:
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                with open(path, "w") as f:
                    f.write(output)
                logger.info(
                    f"Persisted tool output fallback ({len(output)} chars): {path}"
                )
        except Exception:
            logger.warning("Failed to persist tool output", exc_info=True)

        return result
