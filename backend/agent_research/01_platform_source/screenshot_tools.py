"""TypeScript Playwright screenshot tool.

Accepts inline TypeScript Playwright script bodies (camelCase API), wraps them
into a test spec, and runs via the existing ts_playwright_runner. Same pattern
as bash_tools.py — own file, factory registration.
"""

import logging
from typing import Annotated, Optional

from fastmcp import Context, FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

TS_SCREENSHOT_SCRIPT_DESCRIPTION = """TypeScript Playwright script body to execute.

Write the body only — the tool wraps it in a Playwright test with `page` available. Navigate with `page.goto('/')` (resolves against `page_url` baseURL) or use full URLs.

Rules:
1. Use TypeScript Playwright syntax (camelCase): page.goto(), page.setViewportSize(), page.click(), page.screenshot()
2. Navigate with: await page.goto('/', { waitUntil: 'domcontentloaded' }) — resolves against page_url
3. Add proper waits between actions (page.waitForSelector, page.waitForLoadState)
4. For screenshots: use quality=20 and fullPage=false. Set viewport with page.setViewportSize({width: 1280, height: 720}) to minimise image size
5. Use force: true on click actions to bypass overlay issues
6. Use more specific selectors (page.getByRole, page.getByText with exact: true)
"""


def _wrap_script_as_spec(script: str) -> str:
    """Wrap a TS script body into a complete Playwright test spec.

    The agent writes all actions including page.goto() and this
    function adds the import and test block wrapper.
    """
    return f"""import {{ test, expect }} from '@playwright/test';

test('screenshot', async ({{ page }}) => {{
  {script}
}});
"""


async def _run_ts_screenshot(
    script: str,
    output_dir: str,
    capture_all_screenshots: bool,
    base_url: str = None,
) -> dict:
    """Build spec from script body and run via TS Playwright runner."""
    from plugins.tools.agent.ts_playwright_runner import execute_ts_playwright

    spec = _wrap_script_as_spec(script)

    return await execute_ts_playwright(
        spec_content=spec,
        base_url=base_url,
        output_dir=output_dir,
        capture_all_screenshots=capture_all_screenshots,
    )


def register_screenshot_tool_ts(mcp: FastMCP, browser_result_cls, build_image_fn):
    """Register screenshot_tool_ts on the provided FastMCP instance."""

    @mcp.tool(
        description=f"""Take screenshots of a webpage using inline TypeScript Playwright actions.

Write just the **script body** — the tool wraps it in a Playwright test with `page` available. Navigate with `page.goto('/')` (resolves against `page_url` baseURL) or use full URLs. Use this for quick visual checks while building (e.g. verify layout, capture current state).

Uses camelCase Playwright API: page.goto(), page.setViewportSize(), page.click(), page.screenshot().

{TS_SCREENSHOT_SCRIPT_DESCRIPTION}""",
        annotations={
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def screenshot_tool_ts(
        script: Annotated[str, Field(
            description=TS_SCREENSHOT_SCRIPT_DESCRIPTION
        )],
        page_url: Annotated[str, Field(
            description="Base URL of the app under test. Used as baseURL so page.goto('/') resolves against it."
        )] = "",
        output_dir: Annotated[str, Field(
            description="Directory for collected screenshots"
        )] = ".screenshots",
        ctx: Context = None,
    ):
        """Run TypeScript Playwright screenshot scripts."""
        if ctx:
            await ctx.info("Running TS screenshot script")

        try:
            result = await _run_ts_screenshot(
                script=script,
                output_dir=output_dir,
                capture_all_screenshots=False,
                base_url=page_url if page_url else None,
            )

            success = result.get("status") == "success"
            data = result.get("data", {})

            output_parts = data.get("print_logs", [])
            if data.get("error"):
                output_parts.append(f"Error: {data['error']}")
                success = False

            screenshot_images = build_image_fn(
                data.get("screenshots", []), max_images=5, resize=True
            )

            output = "\n".join(output_parts)

            if ctx:
                if success:
                    await ctx.info("TS screenshot script completed successfully")
                else:
                    await ctx.error(f"TS screenshot script failed: {data.get('error')}")

            return browser_result_cls(
                success=success,
                url=page_url,
                images=screenshot_images,
                console_logs=data.get("console_logs", []),
                error=data.get("error"),
                script_output=data.get("output"),
                output=output,
            )

        except Exception as e:
            error_msg = f"TS screenshot script failed: {str(e)}"
            if ctx:
                await ctx.error(error_msg)

            return browser_result_cls(
                success=False,
                url=page_url,
                images=[],
                console_logs=[],
                error=error_msg,
                script_output=None,
                output=error_msg,
            )

    screenshot_tool_ts.tags = {"browser", "screenshot", "playwright"}
    return screenshot_tool_ts
