"""Runner for the `browser-use` MCP tool.

Drives the ``browser-use`` agent against a target URL with a list of
plain-English test cases, routing all LLM calls through an OpenAI-compatible
endpoint (e.g. the integration-proxy). Returns a structured result per test
case, parsed from a ``<verdict>...</verdict>`` tag the agent is instructed to
emit.

This module is imported lazily by `mcp_tools.run_browser_use` so the heavy
`browser_use` import does not slow down MCP server startup.

Ported/adapted from
``harbor-harness/services/browser-verifier/browser_runner.py``. The Gemini
pricing / ``ChatGoogle`` / CDP / Playwright-binary-hunting bits have been
dropped — callers own the LLM selection via ``llm_api_key`` + ``llm_base_url``
+ ``llm_model``, and the browser is always a local headless Chromium launched
by browser-use itself (matching the local-playwright-only posture of the other
plugin_library browser tools).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Where to find a Chromium binary inside the plugin_library image. Playwright's
# default resolution hunts for a bundled binary under PLAYWRIGHT_BROWSERS_PATH
# (e.g. /pw-browsers/chromium-1208/...) but the cloud images only ship the
# headless-shell variant plus the Debian /usr/bin/chromium package, so we must
# pass an explicit executable_path to BrowserSession or playwright will wait
# 30s for a process that never launches.
_CHROMIUM_CANDIDATES = (
    "PLAYWRIGHT_CHROME_EXECUTABLE_PATH",
    "CHROME_PATH",
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
)
_CHROMIUM_FALLBACKS = (
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
)


def _resolve_chromium_executable() -> Optional[str]:
    for env_var in _CHROMIUM_CANDIDATES:
        path = os.environ.get(env_var)
        if path and os.path.exists(path):
            return path
    for path in _CHROMIUM_FALLBACKS:
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Prompt / verdict helpers (verbatim port from browser_runner.py, minus the
# granular_scoring path — the MCP tool v1 uses the simple pass/fail format)
# ---------------------------------------------------------------------------


def create_test_prompt(
    preview_url: str,
    test_case: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Build the instructions the browser-use agent will execute.

    Matches the template used by harbor-harness so agents trained on that
    format keep emitting ``<verdict>...</verdict>`` the same way. An optional
    ``system_prompt`` is prepended verbatim so the caller can inject extra
    constraints (persona, stop conditions, auth steps, …).
    """

    verdict_instructions = (
        "IMPORTANT: After completing all steps, return your final verdict in "
        "this exact format:\n"
        '<verdict>{"status": "pass", "details": "what you validated"}</verdict>\n'
        "or\n"
        '<verdict>{"status": "fail", "details": "what went wrong"}</verdict>\n'
        "\n"
        'Use "pass" only if ALL validation steps succeeded. Use "fail" if ANY '
        "step failed or if the expected behavior was not observed."
    )

    base = (
        f"You are a testing agent. Your job is to follow these instructions "
        f"and validate the results. The application is available at "
        f"{preview_url}.\n\n"
        f"{test_case}\n\n"
        f"{verdict_instructions}"
    )

    if system_prompt:
        return f"{system_prompt.strip()}\n\n{base}"
    return base


def _extract_verdict(result_str: str) -> tuple[Optional[str], Optional[str]]:
    """Parse ``(status, details)`` from an agent output string.

    The agent is instructed to emit ``<verdict>{"status":..,"details":..}</verdict>``
    — we accept that form and a bare JSON object with the same shape as a
    fallback, and nothing else. Earlier versions of this function also matched
    a bare ``"status":"pass"`` key anywhere in the string, but that pattern
    fires on internal browser-use action state (e.g. successful navigate
    events with ``status: "pass"`` fields) and produces false-positive passes
    when the agent never actually emits a verdict. Returning ``(None, None)``
    here is intentional — the caller treats that as ``status="error"``.
    """

    # Priority 1: explicit <verdict>...</verdict> XML tag
    try:
        m = re.search(
            r"<verdict>\s*(\{.*?\})\s*</verdict>",
            result_str,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            parsed = json.loads(m.group(1))
            status = str(parsed.get("status", "")).lower()
            if status in ("pass", "fail"):
                return status, parsed.get("details", "")
    except Exception:
        pass

    # Priority 2: bare JSON object with "status": "pass|fail"
    try:
        for pattern in (
            r'\{\s*"status"\s*:\s*"(pass|fail)"[^}]*\}',
            r'\{[^{}]*"status"\s*:\s*"(pass|fail)"[^{}]*\}',
        ):
            m = re.search(pattern, result_str, re.DOTALL | re.IGNORECASE)
            if m:
                parsed = json.loads(m.group(0))
                status = str(parsed.get("status", "")).lower()
                if status in ("pass", "fail"):
                    return status, parsed.get("details", "")
    except Exception:
        pass

    return None, None


def _collect_result_string(agent: Any, history: Any) -> str:
    """Best-effort extraction of the agent's final output as a string.

    Only looks at documented agent/history getters that return the agent's
    reasoning output or final answer. Deliberately does NOT scan
    ``history.all_results[*].extracted_content`` (that's page-scraped content
    from browser actions, not the agent's verdict) and does NOT fall back to
    a recursive scrape of ``history.__dict__`` (too broad — picks up random
    internal strings that happen to match the verdict regex). When none of
    the documented paths return anything, we return an empty string and the
    caller treats the test as ``status="error"``, which is safer than
    fabricating a pass.
    """

    # Try agent attributes that return the final text.
    for attr in ("result", "final_result", "task_result", "last_result", "output"):
        if hasattr(agent, attr):
            val = getattr(agent, attr)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    continue
            if val:
                return str(val)

    # Try history.final_result() — the documented browser-use API.
    if hasattr(history, "final_result"):
        try:
            final = history.final_result()
            if final:
                return str(final)
        except Exception:
            pass

    # Try plain history attributes that might hold the final text.
    for attr in ("result", "output", "final_output", "response"):
        if hasattr(history, attr):
            val = getattr(history, attr)
            if val:
                return str(val)

    # As a last resort, check the last model output. This is the final LLM
    # response text, which *should* contain the verdict tag when the agent
    # followed the prompt. It's scoped tightly enough that it won't pick up
    # per-action telemetry.
    if history is not None and hasattr(history, "all_model_outputs"):
        try:
            outputs = history.all_model_outputs()
            if outputs:
                return str(outputs[-1])
        except Exception:
            pass

    return ""


def _extract_step_count(history: Any) -> int:
    """Pull a best-effort step count out of browser-use history."""
    for attr in ("number_of_steps", "n_steps", "steps"):
        if hasattr(history, attr):
            val = getattr(history, attr)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    continue
            try:
                return int(val) if val is not None else 0
            except (TypeError, ValueError):
                continue
    # Fall back to counting history.history entries
    if hasattr(history, "history"):
        try:
            return len(history.history)
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def execute_browser_use_tests(
    *,
    page_url: str,
    test_cases: list[str],
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str,
    system_prompt: Optional[str],
    timeout_per_test_s: int,
    max_steps_per_test: int,
    headless: bool,
) -> dict:
    """Run ``test_cases`` against ``page_url`` with one shared browser session.

    All LLM calls are routed through ``llm_base_url`` (OpenAI-compat) using
    ``llm_api_key``. The caller is fully responsible for supplying those — we
    never read environment variables here.

    Returns the same dict shape ``qabot_script_handler`` /
    ``ts_playwright_runner`` use so the MCP tool layer can stay uniform:

        {
          "status": "success" | "error",
          "data": {
            "results": [ {test_name, status, details, steps}, ... ],
            "pass_count": int,
            "fail_count": int,
            "error": Optional[str],
            "print_logs": list[str],
          },
        }
    """

    result: dict[str, Any] = {
        "status": "success",
        "data": {
            "results": [],
            "pass_count": 0,
            "fail_count": 0,
            "error": None,
            "print_logs": [],
        },
    }

    if not test_cases:
        result["status"] = "error"
        result["data"]["error"] = "test_cases must not be empty"
        return result

    if not llm_api_key:
        result["status"] = "error"
        result["data"]["error"] = "llm_api_key is required"
        return result

    # Lazy import so MCP server startup doesn't pay the browser-use cost.
    try:
        from browser_use import Agent, ChatOpenAI
        from browser_use.browser.session import BrowserSession
    except ImportError as e:
        result["status"] = "error"
        result["data"]["error"] = (
            f"browser-use package is not installed: {e}. "
            "Add 'browser-use' to the plugin_library dependencies."
        )
        return result

    logs: list[str] = result["data"]["print_logs"]

    def log(msg: str) -> None:
        logger.info(msg)
        logs.append(msg)

    log(f"browser-use tool: url={page_url} tests={len(test_cases)} model={llm_model}")

    llm = ChatOpenAI(
        model=llm_model,
        api_key=llm_api_key,
        base_url=llm_base_url,
    )

    chromium_executable = _resolve_chromium_executable()
    if chromium_executable:
        log(f"browser-use chromium executable: {chromium_executable}")
    else:
        log(
            "browser-use chromium executable: <none found> "
            "(falling back to playwright default — likely to time out)"
        )

    browser_session = BrowserSession(
        headless=headless,
        keep_alive=True,
        executable_path=chromium_executable,
        chromium_sandbox=False,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    try:
        await browser_session.start()
    except Exception as e:
        result["status"] = "error"
        result["data"]["error"] = f"Failed to launch browser: {e}"
        return result

    try:
        for idx, test_case in enumerate(test_cases, 1):
            log(f"[{idx}/{len(test_cases)}] running: {test_case[:120]}")
            task = create_test_prompt(page_url, test_case, system_prompt=system_prompt)

            try:
                agent = Agent(
                    task=task,
                    llm=llm,
                    browser_session=browser_session,
                )
                history = await asyncio.wait_for(
                    agent.run(max_steps=max_steps_per_test),
                    timeout=timeout_per_test_s,
                )
            except asyncio.TimeoutError:
                result["data"]["results"].append(
                    {
                        "test_name": test_case[:200],
                        "status": "error",
                        "details": (
                            f"Test timed out after {timeout_per_test_s}s"
                        ),
                        "steps": 0,
                    }
                )
                log(f"[{idx}/{len(test_cases)}] TIMEOUT")
                continue
            except Exception as e:
                logger.exception("browser-use agent raised")
                result["data"]["results"].append(
                    {
                        "test_name": test_case[:200],
                        "status": "error",
                        "details": f"Agent error: {e}",
                        "steps": 0,
                    }
                )
                log(f"[{idx}/{len(test_cases)}] ERROR: {e}")
                continue

            result_str = _collect_result_string(agent, history)
            status, details = _extract_verdict(result_str)
            steps = _extract_step_count(history)

            if status == "pass":
                result["data"]["pass_count"] += 1
            elif status == "fail":
                result["data"]["fail_count"] += 1

            result["data"]["results"].append(
                {
                    "test_name": test_case[:200],
                    "status": status or "error",
                    "details": (
                        details
                        or (result_str[:500] if result_str else "No verdict produced")
                    ),
                    "steps": steps,
                }
            )
            log(
                f"[{idx}/{len(test_cases)}] {status or 'no-verdict'} "
                f"(steps={steps})"
            )
    finally:
        try:
            await browser_session.stop()
        except Exception as e:
            logger.warning("browser session stop failed: %s", e)

    return result
