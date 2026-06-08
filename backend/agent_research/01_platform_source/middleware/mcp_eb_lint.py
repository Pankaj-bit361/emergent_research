"""MCP middleware for running Python linters on file-mutating tool results.

Each file-mutating tool pushes its touched file paths into a ContextVar via
``register_touched_path(path)``. After the tool completes, the middleware
reads the paths, runs Ruff + EB001/EB002 on matching Python files, and writes
findings to ``lint_violations`` in the tool result's structured_content —
never touching ``output``.

JS/TS lint is intentionally not run here; agents call the dedicated
``lint_javascript`` tool when they want it.
"""

from __future__ import annotations

import asyncio
import re
from contextvars import ContextVar
from typing import List

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

from plugins.tools.agent.logger import logger
from linters.output import (
    assemble_lint_payload,
    sort_key_blocking,
)

# Only these rules surface to the agent on every file write. Per-file channel
# is Python-only (EB001 + EB002); JS lint runs via the dedicated lint_javascript
# tool, not middleware.
PER_FILE_RULE_NAMES: frozenset[str] = frozenset({"EB001", "EB002"})

# Ruff/EB-style codes (e.g. "F401", "EB001").
_RULE_CODE_GENERIC_RE = re.compile(r"\b([A-Z]+\d+)\b")


def _violation_rule_code(violation: str) -> str | None:
    """Extract the rule code from one Python lint violation line.

    Recognized prefix shapes (middleware is Python-only):
      * ``[ruff] file:l:c: F401 msg`` → ``F401`` via ``_RULE_CODE_GENERIC_RE``.
      * ``[eb] file:l:c: EB001 msg`` → ``EB001`` via ``_RULE_CODE_GENERIC_RE``.

    Not handled here:
      * ``[oxlint] ...`` — JS lint never runs in middleware (see lint_javascript
        MCP tool); any oxlint line that slips in falls through to ``None``.

    Returns ``None`` if no recognizable Python-lint code is present.
    """
    if violation.startswith("[ruff] ") or violation.startswith("[eb] "):
        m = _RULE_CODE_GENERIC_RE.search(violation)
        return m.group(1) if m else None
    return None


def _filter_to_per_file(lines: list[str]) -> list[str]:
    """Keep only violations whose rule code is in ``PER_FILE_RULE_NAMES``."""
    out: list[str] = []
    for line in lines:
        code = _violation_rule_code(line)
        if code is not None and code in PER_FILE_RULE_NAMES:
            out.append(line)
    return out

# ---------------------------------------------------------------------------
# ContextVar: tools push paths here, middleware reads them
# ---------------------------------------------------------------------------

_touched_paths: ContextVar[List[str] | None] = ContextVar(
    "eb_touched_paths", default=None
)


def register_touched_path(path: str) -> None:
    """Register a file path that was just created or modified.

    Call this from any file-mutating tool after a successful write.
    """
    paths = _touched_paths.get(None)
    if paths is None:
        paths = []
        _touched_paths.set(paths)
    paths.append(path)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_and_reset_touched_paths() -> List[str] | None:
    """Read the current touched paths and reset for the next invocation."""
    paths = _touched_paths.get(None)
    _touched_paths.set(None)
    return paths


def _append_warnings(
    result: ToolResult, warnings: List[str], field: str,
) -> ToolResult:
    """Write warnings to a dedicated field in structured_content."""
    if warnings and result.structured_content and isinstance(result.structured_content, dict):
        existing = result.structured_content.get(field, [])
        result.structured_content[field] = existing + warnings
    return result


async def _run_middleware_lint(paths: List[str]) -> dict:
    """Run Python lint (Ruff + EB001/EB002) on *paths* and return a structured result.

    Returned dict keys:
      ``blocking``: ordered list of error-severity violations.
      ``advisory``: ordered list of warning-severity violations.
      ``blocking_count``/``advisory_count``: convenience integers.
    """
    from linters.lint_utils import partition_lint_paths
    from linters.lint_tools import run_python_linter

    py_paths, _js_paths = partition_lint_paths(paths)

    py_errors: List[str] = []
    py_warnings: List[str] = []

    if py_paths:
        logger.info(
            "[LINT_PATH] python lint n_files=%d files=%s",
            len(py_paths), py_paths,
        )
        try:
            py_result = await asyncio.to_thread(
                run_python_linter, py_paths, "middleware", None, False,
            )
            py_errors = list(py_result.errors)
            py_warnings = list(py_result.warnings)
        except Exception:
            logger.exception("Unified lint middleware: Python linting failed")

    blocking: List[str] = list(py_errors)
    blocking.sort(key=sort_key_blocking)
    advisory: List[str] = list(py_warnings)

    logger.info(
        "Unified lint middleware: %d blocking + %d advisory across %d file(s)",
        len(blocking), len(advisory), len(paths),
    )
    return {
        "blocking": blocking,
        "advisory": advisory,
        "blocking_count": len(blocking),
        "advisory_count": len(advisory),
    }


# ---------------------------------------------------------------------------
# Unified middleware
# ---------------------------------------------------------------------------

class MCPUnifiedLintMiddleware(Middleware):
    """Lint touched Python files when ``run_lint=true``: runs Ruff + EB001/EB002
    but filters to ``PER_FILE_RULE_NAMES`` (EB001/EB002 only) before surfacing —
    Ruff is dropped mid-run; full set still gates at pre-completion. Writes to ``structured_content['lint_violations']``."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
        arguments = context.message.arguments or {}

        # Opt-in: skip unless an upstream caller explicitly sets run_lint=true.
        if arguments.pop("run_lint", False) is not True:
            logger.info("[LINT_PATH] skipped (run_lint not opted in) tool=%s", tool_name)
            return await call_next(context)

        logger.info("[LINT_PATH] middleware invoked tool=%s", tool_name)

        _touched_paths.set(None)  # reset before tool runs

        result = await call_next(context)

        paths = _get_and_reset_touched_paths()
        if not paths:
            logger.info("[LINT_PATH] no files touched tool=%s — lint SKIPPED", tool_name)
            return result

        logger.info(
            "[LINT_PATH] running lint tool=%s n_files=%d files=%s",
            tool_name, len(paths), paths,
        )

        try:
            lint = await _run_middleware_lint(paths)
        except Exception:
            logger.exception(
                "Unified lint middleware: full lint check failed for tool '%s'",
                tool_name,
            )
            return result

        # Hybrid architecture: per-file emits only the curated subset
        # (PER_FILE_RULE_NAMES). The full set still runs (the linters can't
        # be selectively configured per call without a config explosion); we
        # filter post-lint so the agent sees a focused, low-noise stream
        # mid-run while the pre-terminal stage retains the full gate.
        blocking = _filter_to_per_file(lint["blocking"])
        advisory = _filter_to_per_file(lint["advisory"])
        bcount = len(blocking)
        acount = len(advisory)

        logger.info(
            "Unified lint middleware: %d blocking + %d advisory after tool '%s' "
            "(filtered from %d/%d to per-file curated set)",
            bcount, acount, tool_name,
            lint["blocking_count"], lint["advisory_count"],
        )

        if not blocking and not advisory:
            return result

        # Mid-run (per_file) stage: the directive's consequence framing and the
        # fenced BLOCKING/ADVISORY layout are owned by assemble_lint_payload so
        # this path and the finalize path stay byte-identical in structure.
        payload = assemble_lint_payload(blocking, advisory, stage="per_file")
        return _append_warnings(result, payload, "lint_violations")
