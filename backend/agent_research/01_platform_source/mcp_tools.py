"""Direct MCP tool registration following FastMCP best practices.

This module implements tools using FastMCP's recommended patterns:
- Direct function decoration with @mcp.tool
- Proper async/sync handling
- Structured outputs with Pydantic models
- Context support for logging and progress
"""

import ast
import base64
import fnmatch
import logging
import asyncio
import os
import re
from typing import Optional, List, Dict, Any, Annotated, Union, Literal
from pathlib import Path
from pydantic import BaseModel, Field
from mcp.types import ImageContent

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError

from plugins.tools.agent.todo_tools import TodoWriteResult, TodoItem
from plugins.tools.agent.descriptions import BROWSER_AUTOMATION_SCRIPT_DESCRIPTION, BROWSER_AUTOMATION_TOOL_DESCRIPTION, MULTI_SEARCH_REPLACE_DESCRIPTION, RUN_BROWSER_USE_DESCRIPTION, RUN_TS_PLAYWRIGHT_DESCRIPTION, SCREENSHOT_SCRIPT_DESCRIPTION, TODO_WRITE_DESCRIPTION
from plugins.tools.file_editor.codex_apply_patch import stage_apply_patch_operations
from plugins.tools.file_editor.freeform_apply_patch import parse_freeform_patch
from plugins.tools.agent.middleware.mcp_eb_lint import register_touched_path
logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 80_000


# Lines whose leading non-whitespace is XML/HTML tag shape (`<x>` or `</x>`)
# — Python's `<` operator never appears followed by `>` on the same line.
_TAG_SHAPED_LINE = re.compile(r"^</?[a-zA-Z][^<>\n]*>")


def _strip_trailing_markup(script: str) -> tuple[str, bool]:
    """Drop trailing tag-shaped lines if doing so makes the script valid Python.
    Scans from the end so an opening wrapper like ``<script>`` at the top never
    becomes the cut point. No-op if nothing changes or the result is empty."""
    if not script:
        return script, False
    try:
        ast.parse(script)
        return script, False
    except SyntaxError:
        pass
    lines = script.splitlines(keepends=True)
    cut = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped == "" or _TAG_SHAPED_LINE.match(stripped):
            cut = i
            continue
        break
    if cut == len(lines):
        return script, False
    cleaned = "".join(lines[:cut]).rstrip() + "\n"
    if not cleaned.strip():
        return script, False
    try:
        ast.parse(cleaned)
        return cleaned, True
    except SyntaxError:
        return script, False


def _default_llm_base_url() -> str:
    """Resolve the default LLM base URL for tools that route through the
    Emergent integration proxy (currently only ``run_browser_use``).

    Plugin-library images are deployed across several envs — dev, staging,
    prod, wingman — each with its own integration-proxy hostname. Pods expose
    their own proxy hostname as ``integration_proxy_url`` (or
    ``INTEGRATION_PROXY_URL``), without a path suffix, so the caller can
    build env-appropriate URLs at runtime. Hardcoding one hostname as the
    tool default (which was the case before) meant a dev-env ``sk-emergent-*``
    key would get routed to the staging proxy, come back ``401 Invalid API
    key``, and the whole browser-use agent loop would fail with
    ``Invalid API key`` on every step.

    Resolution order:
      1. ``INTEGRATION_PROXY_URL`` env var (uppercase, standard shell convention)
      2. ``integration_proxy_url`` env var (lowercase, matches what the pod
         provisioner writes into supervisor env)
      3. Hardcoded production fallback so local smoke tests still work when
         neither env var is set.

    The ``/llm/v1`` suffix is always appended because the tool's LLM client
    expects the OpenAI-compat version root — pods only expose the
    authority. Trailing slashes and redundant ``/llm/v1`` suffixes are
    normalized so setting the env var either way is safe.
    """
    raw = (
        os.environ.get("INTEGRATION_PROXY_URL")
        or os.environ.get("integration_proxy_url")
        or "https://integrations.emergentagent.com"
    )
    base = raw.rstrip("/")
    if base.endswith("/llm/v1"):
        return base
    if base.endswith("/llm"):
        return base + "/v1"
    return base + "/llm/v1"


_DEFAULT_LLM_BASE_URL = _default_llm_base_url()
SCREENSHOT_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

# Image resize limits — Claude recommends long edge ≤ 1568px for optimal
# performance (images above this are scaled down server-side anyway).
IMAGE_MAX_LONG_EDGE = 1568
IMAGE_JPEG_QUALITY = 80


MIDDLE_OUT_TRUNCATION = os.environ.get("MCP_MIDDLE_OUT_TRUNCATION", "1") == "1"

# URL content-type to image extension mapping
_URL_IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}


def _is_url(path: str) -> bool:
    """Return True if *path* looks like an HTTP(S) URL."""
    return path.startswith("http://") or path.startswith("https://")

_FETCH_URL_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap for URL reads


def _fetch_url(url: str, timeout: int = 30, max_bytes: int = _FETCH_URL_MAX_BYTES) -> tuple:
    """Download *url* synchronously and return ``(bytes, content_type, final_url)``."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers={"User-Agent": "Emergent-Read/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(
                f"Response from {url} exceeds {max_bytes // (1024 * 1024)}MB limit."
            )
        final_url = resp.url
    return data, content_type, final_url


def truncate_output(text: Optional[str], max_length: int = MAX_OUTPUT_CHARS) -> str:
    """Keep tool output within the configured size limit.

    When MCP_MIDDLE_OUT_TRUNCATION=1 (default), keeps the first half and last
    half of the text so that errors/summaries at the end are preserved.
    Set MCP_MIDDLE_OUT_TRUNCATION=0 for head-only truncation.

    Marker format matches xllm/squash.go TruncationMarker.
    """
    if text is None:
        return ""
    if max_length <= 0 or len(text) <= max_length:
        return text
    # Already truncated — don't double-truncate
    if "chars truncated" in text:
        return text

    # Persist full output before truncating (if middleware set the context)
    from plugins.tools.agent.middleware.mcp_output_persistence import persist_full_output
    persist_full_output(text)

    if MIDDLE_OUT_TRUNCATION:
        removed = len(text) - max_length
        half = max_length // 2
        return text[:half] + f"\u2026{removed} chars truncated\u2026" + text[len(text) - half:]

    suffix = "\n... [output truncated]"
    if len(suffix) >= max_length:
        return text[:max_length]
    return text[: max_length - len(suffix)] + suffix


def _resize_image_bytes(raw: bytes, mime_type: str) -> tuple[bytes, str]:
    """Resize image so the long edge is ≤ IMAGE_MAX_LONG_EDGE (1568px).

    Returns (bytes, mime_type).  If the image already fits, the original
    bytes are returned unchanged (preserving the original format).
    Non-JPEG/PNG inputs are converted to JPEG.
    """
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(raw))
        w, h = img.size

        long_edge = max(w, h)
        needs_resize = long_edge > IMAGE_MAX_LONG_EDGE
        is_native_format = mime_type in ("image/jpeg", "image/png")

        if not needs_resize and is_native_format:
            return raw, mime_type

        if needs_resize:
            scale = IMAGE_MAX_LONG_EDGE / long_edge
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Always output JPEG for smaller size (screenshots rarely need alpha)
        buf = io.BytesIO()
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=IMAGE_JPEG_QUALITY)
        return buf.getvalue(), "image/jpeg"

    except ImportError:
        # Pillow not installed — return raw bytes
        return raw, mime_type
    except Exception as exc:
        logger.warning(f"Image resize failed, using original: {exc}")
        return raw, mime_type


def _build_image_contents(screenshots: List[Any], max_images: Optional[int] = None, resize: bool = False) -> List[ImageContent]:
    """Convert screenshot artifacts into ImageContent objects.

    When *resize* is True, images are resized so the long edge is ≤ 1568px
    (per Claude's recommendation) and JPEG-compressed at IMAGE_JPEG_QUALITY.
    When False (default), raw bytes are passed through unchanged.
    """
    if max_images is not None and max_images <= 0:
        return []

    images: List[ImageContent] = []

    for entry in screenshots:
        try:
            if isinstance(entry, ImageContent):
                images.append(entry)
                if max_images and len(images) >= max_images:
                    break
                continue

            if not isinstance(entry, (str, Path)):
                logger.warning(f"Could not convert screenshot entry of type {type(entry)}")
                continue

            path = Path(entry)
            raw = path.read_bytes()
            mime_type = SCREENSHOT_MIME_TYPES.get(path.suffix.lower(), "image/jpeg")

            if resize:
                raw, mime_type = _resize_image_bytes(raw, mime_type)
            data = base64.b64encode(raw).decode("utf-8")

            images.append(ImageContent(
                type="image",
                data=data,
                mimeType=mime_type,
                meta={"file_name": path.name}
            ))
            if max_images and len(images) >= max_images:
                break
        except Exception as exc:
            logger.warning(f"Could not convert screenshot entry ({type(entry)}): {exc}")

    return images


# Create the FastMCP server instance
mcp = FastMCP(
    name="Emergent-Tools"
)

# Disable MCP protocol-level JSON Schema validation so our middleware can fix
# stringified JSON arguments before Pydantic validation runs.
# See: https://github.com/anthropics/claude-code/issues/3084
# Handle both old (2.11.x: _mcp_call_tool) and new (2.14.x+: _call_tool_mcp) attribute names
_call_tool_handler = getattr(mcp, '_call_tool_mcp', None) or mcp._mcp_call_tool
mcp._mcp_server.call_tool(validate_input=False)(_call_tool_handler)

# Middleware registration
# NOTE: first registered = outermost = runs first on request (due to reversed() in _apply_middleware)
#
# Request path (outer → inner):
#   ResourceMonitor → OutputPersistence → Idempotency → UnifiedLint → StringifyFix → Tool
# Response path (inner → outer):
#   Tool → StringifyFix → UnifiedLint (append violations) → Idempotency (cache lint-augmented result) → OutputPersistence → ResourceMonitor
# UnifiedLint sits INSIDE Idempotency so the cached result already carries
# lint_violations — retries return the same lint-augmented payload without
# relying on shared-reference mutation of the cached object.
from plugins.tools.agent.middleware.mcp_resource_monitor import MCPResourceMonitorMiddleware
from plugins.tools.agent.middleware.mcp_output_persistence import MCPOutputPersistenceMiddleware
from plugins.tools.agent.middleware.mcp_idempotency import MCPIdempotencyMiddleware
from plugins.tools.agent.middleware.mcp_stringify_fix import MCPStringifyFixMiddleware
from plugins.tools.agent.middleware.mcp_eb_lint import MCPUnifiedLintMiddleware

mcp.add_middleware(MCPResourceMonitorMiddleware())    # 1st: outermost — appends resource warnings on response
mcp.add_middleware(MCPOutputPersistenceMiddleware())  # 2nd: captures request_id on request, persists clean output on response
mcp.add_middleware(MCPIdempotencyMiddleware())        # 3rd: pops request_id, caches lint-augmented result
mcp.add_middleware(MCPUnifiedLintMiddleware())        # 4th: runs Ruff + EB001/EB002 on touched Python files (inside cache)
mcp.add_middleware(MCPStringifyFixMiddleware())       # innermost — fixes stringified JSON before tool runs

# ============================================================================
# System Tools - Resource Monitoring
# ============================================================================

from plugins.tools.agent.system_tools import get_pod_resources

class ResourceMetric(BaseModel):
    """Individual resource metric."""
    percentage: float = Field(description="Usage percentage (0-100+)")
    details: str = Field(description="Human-readable details with units")

class PodResourcesResult(BaseModel):
    """Pod resource usage metrics."""
    memory: ResourceMetric = Field(description="Memory usage from cgroup")
    cpu: ResourceMetric = Field(description="CPU usage from load average")
    storage: ResourceMetric = Field(description="Storage usage from df")
    output: str

@mcp.tool()
def check_pod_resources() -> PodResourcesResult:
    """Check current pod resource usage (memory, CPU, storage).

    Returns real-time resource metrics from cgroup. Use this to check resource
    availability before running intensive operations or when debugging performance.

    Returns structured data with percentage and details for each resource type.
    """
    return get_pod_resources()

# ============================================================================
# Lazy Loading Tool Cache
# ============================================================================

# Cache variables for heavy tool imports
_edit_tool = None
_todo_tools = None
_bulk_create_tool = None

def get_edit_tool():
    """Lazy load and cache EditTool."""
    global _edit_tool
    if _edit_tool is None:
        from plugins.tools.file_editor.impl import EditTool
        _edit_tool = EditTool()
    return _edit_tool

_oxlint_engine = None
def get_oxlint_engine():
    """Lazy load and cache OxlintEngine."""
    global _oxlint_engine
    if _oxlint_engine is None:
        from linters.engines import OxlintEngine
        _oxlint_engine = OxlintEngine()
    return _oxlint_engine

_oxfmt_engine = None
def get_oxfmt_engine():
    """Lazy load and cache OxfmtEngine."""
    global _oxfmt_engine
    if _oxfmt_engine is None:
        from linters.engines import OxfmtEngine
        _oxfmt_engine = OxfmtEngine()
    return _oxfmt_engine

_import_validator = None
def get_import_validator():
    """Lazy load and cache ImportValidator."""
    global _import_validator
    if _import_validator is None:
        from linters.import_validator import ImportValidator
        from linters.lint_utils import WORKSPACE_ROOT
        _import_validator = ImportValidator(str(WORKSPACE_ROOT))
    return _import_validator

def get_todo_tools():
    """Lazy load and cache todo tools module."""
    global _todo_tools
    if _todo_tools is None:
        from plugins.tools.agent import todo_tools
        _todo_tools = todo_tools
    return _todo_tools

def get_bulk_create_tool():
    """Lazy load and cache BulkCreateTool."""
    global _bulk_create_tool
    if _bulk_create_tool is None:
        from plugins.tools.file_editor.bulk_create_impl import BulkCreateTool
        _bulk_create_tool = BulkCreateTool()
    return _bulk_create_tool

# ============================================================================
# Structured Output Models
# ============================================================================

class ViewFileResult(BaseModel):
    """Result of viewing a file."""
    success: bool
    path: str
    output: str
    total_lines: Optional[int] = None
    lines_shown: Optional[str] = None
    has_more: bool = False

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


class ViewBulkResult(BaseModel):
    """Result of bulk file viewing operation."""
    success: bool
    paths: List[str]
    results: List[Dict[str, Any]]  # Individual results for each path
    total_viewed: int
    total_failed: int
    output: str  # Combined output for display

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


class ViewRequest(BaseModel):
    """Request model for viewing a file with optional offset and limit."""
    path: str
    offset: int = 0
    limit: Optional[int] = None


class ViewResult(BaseModel):
    """Result of unified view operation (single or multiple files)."""
    success: bool
    paths: List[str]  # List of paths requested
    results: List[Dict[str, Any]]  # Individual results for each path
    total_viewed: int
    total_failed: int
    output: str  # Combined output for display

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


class FileEditResult(BaseModel):
    """Result of a file editing operation."""
    success: bool
    path: str
    message: str
    output: Optional[str] = None
    lines_affected: Optional[int] = None
    lint_results: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output or self.message


class ApplyPatchResult(BaseModel):
    """Result of applying apply_patch operations."""
    success: bool
    message: str
    files_changed: List[str] = Field(default_factory=list)
    output: str = ""
    lint_results: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return self.output or self.message


class LintResult(BaseModel):
    """Result of a linting operation."""
    success: bool
    path: str
    output: str

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


class FormatResult(BaseModel):
    """Result of a formatting operation."""
    success: bool
    path: str
    mode: str  # "check" or "write"
    output: str

    def __str__(self) -> str:
        return self.output


class ApplyPatchOperation(BaseModel):
    """OpenAI apply_patch operation payload."""
    type: Literal["create_file", "update_file"] = Field(
        description="Operation type"
    )
    path: str = Field(description="File path for the operation")
    diff: Optional[str] = Field(
        default=None,
        description="V4A diff for create/update; omitted for delete",
    )


class BashResult(BaseModel):
    """Result of executing a bash command."""
    success: bool
    command: str
    stdout: str
    stderr: str
    return_code: int
    output: str  # Combined pretty-printed output

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


from plugins.tools.agent.bash_tools import register_streaming_bash_tool, register_manage_process_tool
register_streaming_bash_tool(mcp, BashResult)
register_manage_process_tool(mcp, BashResult)


class PlaywrightResult(BaseModel):
    """Result of running a TypeScript Playwright spec."""
    success: bool
    images: List[ImageContent] = Field(default_factory=list)
    output: str

    def __str__(self) -> str:
        return self.output


class BrowserAutomationResult(BaseModel):
    """Result of browser automation execution."""
    success: bool
    url: str
    images: List[ImageContent] = Field(default_factory=list)
    console_logs: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    script_output: Optional[str] = None
    output: str  # Combined output for display

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


class BrowserUseTestResult(BaseModel):
    """Result of a single browser-use test case."""
    test_name: str
    status: Literal["pass", "fail", "error"]
    details: str
    steps: int = 0


class BrowserUseResult(BaseModel):
    """Result of running a batch of browser-use tests against a URL."""
    success: bool
    url: str
    pass_count: int = 0
    fail_count: int = 0
    results: List[BrowserUseTestResult] = Field(default_factory=list)
    error: Optional[str] = None
    output: str  # Combined summary for display

    def __str__(self) -> str:
        return self.output


from plugins.tools.agent.screenshot_tools import register_screenshot_tool_ts
register_screenshot_tool_ts(mcp, BrowserAutomationResult, _build_image_contents)


class BulkFileItem(BaseModel):
    """Individual file item for bulk operations."""
    path: Annotated[str, Field(description="Absolute path to the file")]
    content: Annotated[str, Field(
        description="Raw text content for the file"
    )]


class BulkFilesList:
    """Custom type that accepts Union[str, List] but only shows List in schema."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        """Define how Pydantic should validate this type."""
        from pydantic_core import core_schema

        # Build the list schema for BulkFileItem
        list_schema = core_schema.list_schema(handler(BulkFileItem))

        # Accept either string or list for validation
        return core_schema.union_schema([
            core_schema.str_schema(),
            list_schema
        ])

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        """Define JSON schema - only show array type to hide Union."""
        from pydantic_core import core_schema

        # Build and return only the list schema for JSON/OpenAPI
        list_schema = core_schema.list_schema(
            core_schema.model_schema(BulkFileItem, BulkFileItem.__pydantic_core_schema__)
        )
        return handler(list_schema)


class BulkFileWriterResult(BaseModel):
    """Result of bulk file writing operation."""
    success: bool
    files_processed: int
    output: str
    failed_files: Optional[List[str]] = None

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


# ============================================================================
# File Editor Tools - Direct Registration
# ============================================================================

MAX_VIEW_FILE_LINES = 2000


def _count_file_lines(file_path: str) -> int:
    """Count total lines matching EditTool's split('\\n') logic."""
    with open(file_path, "r", errors="replace") as f:
        return len(f.read().split('\n'))


def _validate_view_range(start: int, end: int, total_lines: int) -> Optional[str]:
    """Validate view_range against file. Returns error message or None."""
    if start < 1:
        return f"Error: start line must be >= 1, got {start}"
    if start > total_lines:
        return f"Error: start line {start} exceeds total lines ({total_lines})."
    if end != -1 and end < start:
        return f"Error: end line {end} is before start line {start}."
    return None


def _compute_effective_range(
    view_range: Optional[List[int]], total_lines: int, max_lines: int
) -> tuple[int, int]:
    """Compute effective (start, end) range with cap applied. Assumes validated input."""
    if view_range:
        start, end = view_range[0], view_range[1]
        effective_start = start
        # -1 passes through to EditTool which resolves it to end of file
        effective_end = end if end == -1 else min(end, start + max_lines - 1, total_lines)
    else:
        effective_start = 1
        effective_end = min(total_lines, max_lines)
    return effective_start, effective_end


def _format_paginated_output(
    output: str, effective_start: int, effective_end: int, total_lines: int
) -> tuple[str, bool]:
    """Add pagination metadata to output if truncated. Returns (output, has_more)."""
    if effective_end == -1:
        effective_end = total_lines
    has_more = effective_end < total_lines
    # Prepend line range header for both cases
    output = (
        f"[Showing lines {effective_start}-{effective_end} of {total_lines} total] "
        + output
    )
    if has_more:
        remaining_start = effective_end + 1
        remaining_count = total_lines - effective_end
        lines_shown = effective_end - effective_start + 1
        output += (
            f" [{lines_shown} lines shown. "
            f"Remaining: lines {remaining_start}-{total_lines} ({remaining_count} lines). "
            f"Use view_range parameter to continue.]"
        )
    else:
        output += "[End of file]"
    return output, has_more


@mcp.tool(
    description="""
    View file or directory contents. Maximum 2000 lines per request for files.
    * For files: Shows content with line numbers (like 'cat -n')
    * For directories: Lists non-hidden files and subdirectories up to 2 levels deep
    * For files exceeding 2000 lines, use the view_range parameter to paginate through content
    * view_range [start_line, end_line] is 1-indexed. Max range: 2000 lines.
    * Output exceeding 64000 characters will be truncated, marked with '<response clipped>'
    """,
    annotations={
        "readOnlyHint": True,  # This is a read-only operation
        "openWorldHint": True  # Interacts with file system
    }
)
async def view_file(
    path: Annotated[str, Field(description="The absolute path to the file to view")],
    view_range: Annotated[Optional[List[int]], Field(
        description="""
        Optional line range [start_line, end_line] for viewing specific lines.
        * Lines are 1-indexed. Max range: 2000 lines per request.
        * Example: [1, 2000] for first 2000 lines, [2001, 4000] for next 2000.
        """
    )] = None,
    ctx: Context = None
) -> ViewFileResult:
    """
    View file contents with optional line range and 2000-line limit.

    Read and display the contents of a file, with optional line range specification.
    Returns the file content with pagination metadata.
    """
    if ctx:
        await ctx.info(f"Viewing file: {path}")

    try:
        is_dir = os.path.isdir(path)
        effective_start = None
        effective_end = None
        total_lines = None

        if not is_dir:
            total_lines = await asyncio.to_thread(_count_file_lines, path)

            # Validate LLM's original range
            if view_range:
                error = _validate_view_range(view_range[0], view_range[1], total_lines)
                if error:
                    return ViewFileResult(success=False, path=path, output=error)

            # Compute capped range
            effective_start, effective_end = _compute_effective_range(
                view_range, total_lines, MAX_VIEW_FILE_LINES
            )

        # Call EditTool — handles directories, -1, validation, everything
        def do_view():
            edit_tool = get_edit_tool()
            kwargs = {"command": "view", "path": path}
            if effective_start is not None:
                kwargs["view_range_start"] = effective_start
                kwargs["view_range_end"] = effective_end
            return edit_tool(**kwargs)

        result = await asyncio.to_thread(do_view)
        output = result.output if hasattr(result, 'output') else str(result)

        # Add pagination metadata for files
        if not is_dir:
            output, has_more = _format_paginated_output(
                output, effective_start, effective_end, total_lines
            )
            return ViewFileResult(
                success=True,
                path=path,
                output=output,
                total_lines=total_lines,
                lines_shown=f"{effective_start}-{effective_end}",
                has_more=has_more,
            )

        return ViewFileResult(success=True, path=path, output=output)

    except FileNotFoundError:
        if ctx:
            await ctx.error(f"File not found: {path}")
        return ViewFileResult(
            success=False,
            path=path,
            output=f"Error: File not found: {path}"
        )
    except Exception as e:
        if ctx:
            await ctx.error(f"Error viewing file: {e}")
        return ViewFileResult(
            success=False,
            path=path,
            output=f"Error viewing file: {str(e)}"
        )


@mcp.tool(
    description="""
    View multiple files or directories in sequence
    * Processes a list of file or directory paths
    * Reads up to 2000 lines starting from the beginning of the file
    * For files: Shows content with line numbers (like 'cat -n')
    * For directories: Lists non-hidden files and subdirectories up to 2 levels deep
    * Continues processing even if some paths fail
    """,
    annotations={
        "readOnlyHint": True,  # This is a read-only operation
        "openWorldHint": True  # Interacts with file system
    }
)
async def view_bulk(
    paths: Annotated[List[str], Field(
        description="List of absolute paths to files or directories to view",
        min_length=1,
        max_length=20  # Reasonable limit to prevent excessive operations
    )],
    ctx: Context = None
) -> ViewBulkResult:
    """
    View multiple files or directories in sequence.

    Efficiently view the contents of multiple files or directory listings in a single operation.
    Returns consolidated output with clear separation between files.
    """
    if ctx:
        await ctx.info(f"Viewing {len(paths)} path(s) in bulk")

    results = []
    output_parts = []
    total_viewed = 0
    total_failed = 0

    # Process each path
    for i, path in enumerate(paths, 1):
        if ctx:
            await ctx.report_progress(i - 1, len(paths))
            await ctx.info(f"Viewing {i}/{len(paths)}: {path}")

        try:
            # Use the synchronous EditTool in a thread pool
            def do_view():
                edit_tool = get_edit_tool()
                kwargs = {"command": "view", "path": path}
                # Limit the output to 2000 lines
                kwargs["view_range_start"] = 0
                kwargs["view_range_end"] = 2000
                return edit_tool(**kwargs)

            result = await asyncio.to_thread(do_view)

            # EditTool returns a result object with .output attribute
            file_output = result.output if hasattr(result, 'output') else str(result)

            # Add result
            results.append({
                "path": path,
                "success": True,
                "output": file_output
            })

            # Add to combined output with new format
            if output_parts:  # Add separator between entries
                output_parts.append("")

            # Detect if it's a file or directory based on content
            # Files have line numbers like "1|content" or "1\tcontent", directories don't
            lines = file_output.split('\n') if file_output else []
            # Skip the first line if it's the file path itself
            content_lines = lines[1:] if lines and lines[0].endswith(':') else lines

            # Check if it looks like a file with line numbers
            is_file = False
            if content_lines:
                first_content = content_lines[0]
                # Check for line numbers with | or tab separator
                if '|' in first_content or '\t' in first_content:
                    # Extract the part before the separator
                    parts = first_content.split('|' if '|' in first_content else '\t')
                    if parts and parts[0].strip().isdigit():
                        is_file = True

            if is_file:
                output_parts.append(f"===FILE: {path}")
            else:
                output_parts.append(f"===DIR: {path}")
            output_parts.append(file_output)
            output_parts.append("===END")

            total_viewed += 1

        except FileNotFoundError:
            error_msg = f"File not found: {path}"
            if ctx:
                await ctx.error(error_msg)

            results.append({
                "path": path,
                "success": False,
                "error": error_msg
            })

            if output_parts:  # Add separator between entries
                output_parts.append("")
            output_parts.append(f"===ERROR: {path}")
            output_parts.append(error_msg)
            output_parts.append("===END")

            total_failed += 1

        except Exception as e:
            error_msg = f"Error viewing {path}: {str(e)}"
            if ctx:
                await ctx.error(error_msg)

            results.append({
                "path": path,
                "success": False,
                "error": str(e)
            })

            if output_parts:  # Add separator between entries
                output_parts.append("")
            output_parts.append(f"===ERROR: {path}")
            output_parts.append(str(e))
            output_parts.append("===END")

            total_failed += 1

    if ctx:
        await ctx.report_progress(len(paths), len(paths))

    # Combine output with simple format
    combined_output = "\n".join(output_parts)

    if ctx:
        await ctx.info(f"Completed bulk view: {total_viewed}/{len(paths)} successful")

    return ViewBulkResult(
        success=(total_viewed > 0 or len(paths) == 0),  # Success if files viewed or empty request
        paths=paths,
        results=results,
        total_viewed=total_viewed,
        total_failed=total_failed,
        output=combined_output
    )


@mcp.tool(
    description="""View file, directory, or URL contents with per-file offset and limit
    - Accepts either a single ViewRequest or a list of ViewRequests
    - Prefer to read multiple files in parallel with their relevant offset and limit.
    - Each ViewRequest contains: path (required), offset (default 0), limit (optional)
    - For files: Shows content with line numbers (like 'cat -n')
    - For image files (.png, .jpg, .jpeg, .gif, .bmp, .webp): Returns the image inline
    - For URLs (http:// or https://): Fetches the content from the web. Image URLs return inline images; text/HTML/JSON URLs return content with line numbers
    - For directories: Lists files and subdirectories (offset/limit not applicable)
    - Each file can have its own viewing range
    - Continues processing even if some paths fail""",
    annotations={
        "readOnlyHint": True,  # This is a read-only operation
        "openWorldHint": True  # Interacts with file system
    }
)
async def read(
    request: Annotated[Union[ViewRequest, List[ViewRequest]], Field(
        description="Single ViewRequest or list of ViewRequests with path, offset, and limit"
    )],
    ctx: Context = None
) -> Union[ViewResult, list]:
    """
    Read file or directory contents, with per-file offset and limit.

    Accepts a single ViewRequest or a list. For image files, returns the
    image inline as ImageContent.
    """
    from mcp.types import TextContent

    # Normalize input to list of ViewRequest objects
    # Use isinstance(., list) instead of isinstance(., ViewRequest) to avoid
    # class-identity mismatches when the module is importable via multiple paths
    # (e.g. editable installs in CI). See: plugin-library-tests CI failures.
    requests = request if isinstance(request, list) else [request]

    if ctx:
        if len(requests) == 1:
            await ctx.info(f"Viewing: {requests[0].path}")
        else:
            await ctx.info(f"Viewing {len(requests)} path(s)")

    results = []
    output_parts = []
    image_contents = []  # Collect ImageContent objects for inline display
    total_viewed = 0
    total_failed = 0

    # Process each ViewRequest
    for i, req in enumerate(requests, 1):
        if ctx and len(requests) > 1:
            await ctx.report_progress(i - 1, len(requests))
            await ctx.info(f"Viewing {i}/{len(requests)}: {req.path}")

        # ------------------------------------------------------------------
        # Handle URLs — fetch via HTTP(S)
        # ------------------------------------------------------------------
        if _is_url(req.path):
            try:
                if ctx:
                    await ctx.info(f"Fetching URL: {req.path}")
                data, content_type, final_url = await asyncio.to_thread(
                    _fetch_url, req.path
                )

                # Determine if this is an image
                ext = _URL_IMAGE_CONTENT_TYPES.get(content_type)
                if ext is None:
                    # Also check the URL path extension as a fallback
                    from urllib.parse import urlparse
                    url_path = urlparse(req.path).path
                    url_ext = os.path.splitext(url_path)[1].lower()
                    if url_ext in SCREENSHOT_MIME_TYPES:
                        ext = url_ext
                        content_type = SCREENSHOT_MIME_TYPES[url_ext]

                if ext and content_type in _URL_IMAGE_CONTENT_TYPES:
                    # Image URL — resize and return inline
                    raw, mime = _resize_image_bytes(data, content_type)
                    b64 = base64.b64encode(raw).decode("utf-8")
                    img = ImageContent(
                        type="image",
                        data=b64,
                        mimeType=mime,
                        meta={"url": req.path},
                    )
                    label = f"Image from URL: {req.path} ({len(data)} bytes)"
                    output_parts.append(f"===IMAGE: {req.path}")
                    output_parts.append(label)
                    output_parts.append("===END")
                    image_contents.append((label, img))
                    results.append({"path": req.path, "success": True, "output": label})
                    total_viewed += 1
                else:
                    # Text / HTML / JSON — decode and apply offset/limit
                    text = data.decode("utf-8", errors="replace")
                    lines = text.splitlines()
                    total_lines = len(lines)

                    start = req.offset
                    end = start + req.limit if req.limit is not None else total_lines
                    selected = lines[start:end]

                    # Format with line numbers (1-based, matching local file style)
                    numbered = []
                    for idx, line in enumerate(selected, start=start + 1):
                        numbered.append(f"{idx:>6}\t{line}")
                    file_output = "\n".join(numbered)

                    lines_shown = f"{start + 1}-{start + len(selected)}" if selected else "0"
                    has_more = end < total_lines

                    results.append({
                        "path": req.path,
                        "success": True,
                        "output": file_output,
                        "total_lines": total_lines,
                        "lines_shown": lines_shown,
                        "has_more": has_more,
                    })

                    if len(requests) == 1:
                        output_parts.append(file_output)
                    else:
                        if output_parts:
                            output_parts.append("")
                        output_parts.append(f"===URL: {req.path}")
                        output_parts.append(file_output)
                        output_parts.append("===END")

                    total_viewed += 1

            except Exception as e:
                error_msg = f"Error fetching URL {req.path}: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                results.append({"path": req.path, "success": False, "error": str(e)})
                if len(requests) == 1:
                    output_parts.append(f"Error: {error_msg}")
                else:
                    if output_parts:
                        output_parts.append("")
                    output_parts.append(f"===ERROR: {req.path}")
                    output_parts.append(str(e))
                    output_parts.append("===END")
                total_failed += 1

            continue

        file_path = Path(req.path)

        # Handle image files — return inline
        if file_path.suffix.lower() in SCREENSHOT_MIME_TYPES:
            try:
                if not file_path.exists():
                    raise FileNotFoundError(f"Image not found: {req.path}")
                images = _build_image_contents([req.path], max_images=1, resize=True)
                if images:
                    size = file_path.stat().st_size
                    label = f"Image: {file_path.name} ({size} bytes)"
                    output_parts.append(f"===IMAGE: {req.path}")
                    output_parts.append(label)
                    output_parts.append("===END")
                    image_contents.append((label, images[0]))
                    results.append({"path": req.path, "success": True, "output": label})
                    total_viewed += 1
                else:
                    raise ValueError(f"Could not read image: {req.path}")
            except FileNotFoundError:
                error_msg = f"File not found: {req.path}"
                if ctx:
                    await ctx.error(error_msg)
                results.append({"path": req.path, "success": False, "error": error_msg})
                output_parts.append(f"===ERROR: {req.path}")
                output_parts.append(error_msg)
                output_parts.append("===END")
                total_failed += 1
            except Exception as e:
                error_msg = f"Error viewing image {req.path}: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                results.append({"path": req.path, "success": False, "error": str(e)})
                output_parts.append(f"===ERROR: {req.path}")
                output_parts.append(str(e))
                output_parts.append("===END")
                total_failed += 1
            continue

        try:
            # Run the synchronous EditTool in a thread pool
            def do_view():
                edit_tool = get_edit_tool()
                kwargs = {"command": "view", "path": req.path}

                # Check if path is a directory - directories don't support view_range
                import os
                is_directory = os.path.isdir(req.path)

                # Only apply offset/limit for files, not directories
                if not is_directory:
                    # Convert offset/limit to view_range for EditTool
                    # EditTool uses 1-based indexing, our offset is 0-based
                    if req.offset != 0 or req.limit is not None:
                        start = req.offset + 1  # Convert 0-based to 1-based
                        if req.limit is not None:
                            end = start + req.limit - 1
                        else:
                            end = -1  # -1 means end of file in EditTool
                        kwargs["view_range_start"] = start
                        kwargs["view_range_end"] = end
                    elif len(requests) > 1 and req.limit is None:
                        # For multiple files without explicit limit, default limit to 2000 lines
                        kwargs["view_range_start"] = 1
                        kwargs["view_range_end"] = 2000

                return edit_tool(**kwargs)

            result = await asyncio.to_thread(do_view)

            # EditTool returns a result object with .output attribute
            file_output = result.output if hasattr(result, 'output') else str(result)

            # Add result
            results.append({
                "path": req.path,
                "success": True,
                "output": file_output
            })

            # Format output
            if len(requests) == 1:
                # Single file/directory - just use the output directly
                output_parts.append(file_output)
            else:
                # Multiple files/directories - add separators
                if output_parts:  # Add separator between entries
                    output_parts.append("")

                # Detect if it's a file or directory based on content
                lines = file_output.split('\n') if file_output else []
                content_lines = lines[1:] if lines and lines[0].endswith(':') else lines

                is_file = False
                if content_lines:
                    first_content = content_lines[0]
                    # Check for line numbers with | or tab separator
                    if '|' in first_content or '\t' in first_content:
                        parts = first_content.split('|' if '|' in first_content else '\t')
                        if parts and parts[0].strip().isdigit():
                            is_file = True

                if is_file:
                    output_parts.append(f"===FILE: {req.path}")
                else:
                    output_parts.append(f"===DIR: {req.path}")
                output_parts.append(file_output)
                output_parts.append("===END")

            total_viewed += 1

        except FileNotFoundError:
            error_msg = f"File not found: {req.path}"
            if ctx:
                await ctx.error(error_msg)

            results.append({
                "path": req.path,
                "success": False,
                "error": error_msg
            })

            if len(requests) == 1:
                output_parts.append(f"Error: {error_msg}")
            else:
                if output_parts:
                    output_parts.append("")
                output_parts.append(f"===ERROR: {req.path}")
                output_parts.append(error_msg)
                output_parts.append("===END")

            total_failed += 1

        except Exception as e:
            error_msg = f"Error viewing {req.path}: {str(e)}"
            if ctx:
                await ctx.error(error_msg)

            results.append({
                "path": req.path,
                "success": False,
                "error": str(e)
            })

            if len(requests) == 1:
                output_parts.append(f"Error: {error_msg}")
            else:
                if output_parts:
                    output_parts.append("")
                output_parts.append(f"===ERROR: {req.path}")
                output_parts.append(str(e))
                output_parts.append("===END")

            total_failed += 1

    if ctx and len(requests) > 1:
        await ctx.report_progress(len(requests), len(requests))
        await ctx.info(f"Completed: {total_viewed}/{len(requests)} successful")

    # Combine output
    combined_output = "\n".join(output_parts)

    # If we collected images, return mixed content (text + images)
    if image_contents:
        content_list = []
        content_list.append(TextContent(type="text", text=combined_output))
        for _label, img in image_contents:
            content_list.append(img)
        return content_list

    return ViewResult(
        success=(total_viewed > 0 or len(requests) == 0),
        paths=[req.path for req in requests],
        results=results,
        total_viewed=total_viewed,
        total_failed=total_failed,
        output=combined_output
    )


@mcp.tool(
    description="""Create a new file with specified content
- Do not escape special characters (e.g., '' should remain as '', not '\\n').
- Overwrite existing file only when the file changes are substantial
- MUST be used for parallel tool call

Usage:
- ALWAYS add file name with absolute path. Avoid adding emojis to files unless asked by user.""",
    annotations={
        "destructiveHint": True,  # This creates/overwrites files
        "idempotentHint": False   # Multiple calls create conflicts
    }
)
async def create_file(
    path: Annotated[str, Field(description="The absolute path for the new file")],
    file_text: Annotated[str, Field(
        description="Content for the new file"
    )],
    overwrite: Annotated[bool, Field(description="Set to True to replace an existing file")] = False,
    ctx: Context = None
) -> FileEditResult:
    """
    Create a new file with specified content, or overwrite an existing file.

    Creates a new file at the specified path with the provided content.
    If overwrite=True, replaces existing file content entirely.
    """
    if ctx:
        await ctx.report_progress(0, 100)
        await ctx.info(f"{'Overwriting' if overwrite else 'Creating'} file: {path}")

    try:
        # Run the synchronous EditTool in a thread pool
        def do_create():
            edit_tool = get_edit_tool()

            # Pass plain text directly with use_plain_text flag
            return edit_tool(
                command="create",
                path=path,
                file_text=file_text,
                overwrite=overwrite,
                run_lint=False,
                use_plain_text=True
            )

        result = await asyncio.to_thread(do_create)
        register_touched_path(path)

        if ctx:
            await ctx.report_progress(100, 100)

        return FileEditResult(
            success=True,
            path=path,
            message=f"File {'overwritten' if overwrite else 'created'} successfully: {path}",
            output=result.output if hasattr(result, 'output') else str(result),
            lines_affected=len(file_text.splitlines()),
            lint_results=None
        )

    except Exception as e:
        error_msg = f"Failed to {'overwrite' if overwrite else 'create'} file: {str(e)}"

        if ctx:
            await ctx.error(error_msg)

        return FileEditResult(
            success=False,
            path=path,
            message=error_msg,
            output=error_msg
        )


@mcp.tool(
    description="""
    Apply apply_patch operations across one or more files (atomic).

    Each operation is a structured object:
      - type: update_file | create_file
      - path: file path
      - diff: V4A diff

    Example (update_file)
      operations: [
        {
          "type": "update_file",
          "path": "lib/fib.py",
          "diff": "@@\\n-def fib(n):\\n+def fibonacci(n):\\n    if n <= 1:\\n        return n\\n-    return fib(n-1) + fib(n-2)\\n+    return fibonacci(n-1) + fibonacci(n-2)\\n"
        }
      ]

    Example (create_file) — every line must start with "+" (no "@@"):
    operations: [
    {
        "type": "create_file",
        "path": "/app/plan.md",
        "diff": "+# Title\\n+\\n+First line\\n"
    }
    ]


    Notes:
    - All operations are applied atomically: if any hunk fails, no files are written.
    - V4A diff parsing is forgiving to minor whitespace mismatches.
    - operations must be a list of objects only (no extra strings or logs).
    - diff must be V4A hunks only — do NOT end a diff with a trailing @@, it creates an empty section error.
    - create_file diffs must contain only "+"-prefixed lines (no "@@" hunks).
    """,
    annotations={
        "destructiveHint": True,
        "idempotentHint": False,
    },
)
async def apply_patch(
    operations: Annotated[
        List[ApplyPatchOperation],
        Field(description="List of apply_patch operations (update/create)"),
    ],
    ctx: Context = None,
) -> ApplyPatchResult:
    if ctx:
        await ctx.report_progress(0, 100)
        await ctx.info("Applying patch...")

    try:
        staged, changed_paths = stage_apply_patch_operations(
            operations, base_dir=Path.cwd()
        )

        for path_obj, new_text in staged.items():
            if new_text is None:
                path_obj.unlink(missing_ok=True)
                continue
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(new_text, encoding="utf-8")

        for path_obj, new_text in staged.items():
            if new_text is not None:
                register_touched_path(str(path_obj))

        files_changed = sorted({str(p) for p in changed_paths})
        msg = f"Patch applied successfully ({len(files_changed)} file ops)."
        if ctx:
            await ctx.report_progress(100, 100)
            await ctx.info(msg)
        return ApplyPatchResult(
            success=True,
            message=msg,
            files_changed=files_changed,
            output=msg,
            lint_results=None,
        )

    except Exception as e:
        if ctx:
            await ctx.error(f"Failed to apply patch: {e}")
        return ApplyPatchResult(
            success=False,
            message=f"Failed to apply patch: {e}",
            output=str(e),
        )


@mcp.tool(
    description="""
    Apply a free-form patch string across one or more files (atomic).

    Patch format:
      *** Begin Patch
      *** Update File: path/to/file
      @@
      -old line
      +new line
      *** End Patch

    Notes:
    - Supported hunks: *** Add File and *** Update File only.
    - Do NOT use *** Delete File
    - Only text between *** Begin Patch and *** End Patch is parsed.
    - All operations are applied atomically: if any hunk fails, no files are written.
    """,
    annotations={
        "destructiveHint": True,
        "idempotentHint": False,
    },
)
async def apply_patch_freeform(
    patch: Annotated[str, Field(description="Free-form apply_patch text")],
    ctx: Context = None,
) -> ApplyPatchResult:
    if ctx:
        await ctx.report_progress(0, 100)
        await ctx.info("Applying free-form patch...")

    try:
        operations = parse_freeform_patch(patch)
        staged, changed_paths = stage_apply_patch_operations(
            operations, base_dir=Path.cwd()
        )

        for path_obj, new_text in staged.items():
            if new_text is None:
                path_obj.unlink(missing_ok=True)
                continue
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(new_text, encoding="utf-8")

        for path_obj, new_text in staged.items():
            if new_text is not None:
                register_touched_path(str(path_obj))

        files_changed = sorted({str(p) for p in changed_paths})
        msg = f"Patch applied successfully ({len(files_changed)} file ops)."
        if ctx:
            await ctx.report_progress(100, 100)
            await ctx.info(msg)
        return ApplyPatchResult(
            success=True,
            message=msg,
            files_changed=files_changed,
            output=msg,
            lint_results=None,
        )

    except Exception as e:
        if ctx:
            await ctx.error(f"Failed to apply free-form patch: {e}")
        return ApplyPatchResult(
            success=False,
            message=f"Failed to apply free-form patch: {e}",
            output=str(e),
        )


@mcp.tool(
    description="""
    Search and replace exact string in file
    CRITICAL REQUIREMENTS:
    * You MUST view the file first to match indentation exactly
    * old_str must match EXACTLY (including all whitespace, tabs, spaces)
    * old_str must be unique in the file - include enough context
    * Do not escape special characters (e.g., '\n' should remain as '\n', not '\\n').
    * Preserves exact formatting and indentation of the file
    * Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
    * Use replace_all for replacing and renaming strings across the file.
        This parameter is useful if you want to rename a variable for instance or change css class name, etc.
    """,
    annotations={
        "destructiveHint": True,  # This modifies files
        "idempotentHint": True    # Same replacement is idempotent
    }
)
async def search_replace(
    path: Annotated[str, Field(description="The absolute path to the file to modify")],
    old_str: Annotated[str, Field(
        description="""
        Exact string to replace - must match EXACTLY including all whitespace.
        * Include enough surrounding context to make it unique
        * Must match consecutive lines from the file
        * Do not include line numbers
        * Whitespace (spaces, tabs) must match exactly
        """,
    )],
    new_str: Annotated[str, Field(
        description="""
        Replacement string that will replace old_str.
        * Should maintain proper indentation for the context
        * Do not include line numbers
        * Note: For best performance with large replacements (>10KB), consider using smaller, targeted changes
        """,
        min_length=1
    )],
    replace_all: Annotated[bool, Field(
        description="""Replace all occurrences of old_str (default false)
        Use this to replace and rename strings across the file.
        """
    )] = False,
    status: Annotated[bool, Field(
        description="""
        Check if all services are running properly after modification.
        * Set to true when making final changes
        * Helps verify your changes don't break the application
        """
    )] = False,
    ctx: Context = None
) -> FileEditResult:
    """
    Perform exact string replacement in file.

    Important:
    - You must view the file first to ensure correct indentation
    - The old_str must be unique in the file
    - Preserves exact formatting and indentation
    """
    if ctx:
        await ctx.report_progress(0, 100)
        await ctx.info(f"Replacing in {path}: '{old_str[:50]}...'")

        # Check sizes and emit warnings if over 10KB
        old_str_size = len(old_str.encode('utf-8'))
        new_str_size = len(new_str.encode('utf-8'))

        if old_str_size > 10_000:
            await ctx.info(f"ℹ️ Note: old_str is {old_str_size/1024:.1f}KB - consider smaller, targeted changes for better performance")
        if new_str_size > 10_000:
            await ctx.info(f"ℹ️ Note: new_str is {new_str_size/1024:.1f}KB - consider smaller, targeted changes for better performance")

    try:
        # Run the synchronous EditTool in a thread pool
        def do_replace():
            edit_tool = get_edit_tool()

            # Pass plain text directly with use_plain_text flag
            return edit_tool(
                command="str_replace",
                path=path,
                old_str=old_str,
                new_str=new_str,
                replace_all=replace_all,
                run_lint=False,
                status=status,
                use_plain_text=True
            )

        result = await asyncio.to_thread(do_replace)
        register_touched_path(path)

        if ctx:
            await ctx.report_progress(100, 100)

        output = truncate_output(result.output if hasattr(result, 'output') else str(result))


        return FileEditResult(
            success=True,
            path=path,
            message="String replacement completed successfully",
            output=output,
            lint_results=None
        )

    except Exception as e:
        error_msg = f"String replacement failed: {str(e)}"

        if ctx:
            await ctx.error(error_msg)

        return FileEditResult(
            success=False,
            path=path,
            message=error_msg,
            output=error_msg
        )


# ============================================================================
# Multi Search Replace Models and Function
# ============================================================================

class EditOperation(BaseModel):
    """Single edit operation for multi_search_replace."""
    old_str: Annotated[str, Field(
        description="The text to replace",
        min_length=1
    )]
    new_str: Annotated[str, Field(
        description="The text to replace it with"
    )]
    replace_all: Annotated[bool, Field(
        description="Replace all occurrences of old_str (default false)"
    )] = False


class MultiEditResult(BaseModel):
    """Result of multiple file editing operations."""
    success: bool
    path: str
    total_edits: int
    successful_edits: int
    failed_edits: int
    results: List[FileEditResult]
    output: str
    lint_results: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        """Return text representation."""
        return self.output


@mcp.tool(
    description= MULTI_SEARCH_REPLACE_DESCRIPTION,
    annotations={
        "destructiveHint": True,  # This modifies files
        "idempotentHint": False   # Multiple edits are not idempotent
    }
)
async def multi_search_replace(
    path: Annotated[str, Field(description="The absolute path to the file to modify")],
    edits: Annotated[List[EditOperation], Field(
        description="""
        Array of edit operations to perform sequentially on the file
        IMPORTANT: This must be an actual array of objects, not a JSON string.
        Example: [{"old_str": "old text", "new_str": "new text", "replace_all": false}]
        DO NOT pass as a JSON-encoded string - the array will be handled automatically.
        """,
        min_length=1
    )],
    status: Annotated[bool, Field(
        description="""
        Check if all services are running properly after modifications.
        * Set to true when making final changes
        * Helps verify your changes don't break the application
        """
    )] = False,
    ctx: Context = None
) -> MultiEditResult:
    """
    Perform multiple exact string replacements in file sequentially.

    Each edit operation is applied to the result of the previous edit,
    allowing for complex multi-step transformations of a file.
    All edits are atomic - if any edit fails, the file is restored to its original state.
    """
    results = []
    successful_edits = 0
    failed_edits = 0
    original_content = None
    backup_made = False

    if ctx:
        total_steps = len(edits)
        await ctx.info(f"Starting {total_steps} edit operations on {path}")

        # Check each edit operation for size warnings
        for idx, edit in enumerate(edits, 1):
            old_str_size = len(edit.old_str.encode('utf-8'))
            new_str_size = len(edit.new_str.encode('utf-8'))

            if old_str_size > 10_000:
                await ctx.info(f"ℹ️ Note: Edit {idx} old_str is {old_str_size/1024:.1f}KB - consider smaller, targeted changes for better performance")
            if new_str_size > 10_000:
                await ctx.info(f"ℹ️ Note: Edit {idx} new_str is {new_str_size/1024:.1f}KB - consider smaller, targeted changes for better performance")

    try:
        # First, backup the original file content for atomic operation
        try:
            file_path = Path(path)
            if file_path.exists():
                original_content = file_path.read_text(encoding='utf-8')
                backup_made = True
                if ctx:
                    await ctx.info(f"Backed up original content of {path}")
        except Exception as e:
            error_msg = f"Failed to backup original file: {str(e)}"
            if ctx:
                await ctx.error(error_msg)
            return MultiEditResult(
                success=False,
                path=path,
                total_edits=len(edits),
                successful_edits=0,
                failed_edits=0,
                results=[],
                output=error_msg,
                lint_results=None
            )
        # Apply each edit sequentially
        for i, edit in enumerate(edits, 1):
            if ctx:
                await ctx.report_progress(i - 1, total_steps)
                await ctx.info(f"Edit {i}/{total_steps}: Replacing '{edit.old_str[:50]}...'")

            try:
                # Run the synchronous EditTool in a thread pool
                def do_replace():
                    edit_tool = get_edit_tool()

                    # Don't run lint/status on intermediate edits, only on the last one
                    should_lint = False
                    should_check_status = status and (i == len(edits))

                    # Pass plain text directly with use_plain_text flag
                    return edit_tool(
                        command="str_replace",
                        path=path,
                        old_str=edit.old_str,
                        new_str=edit.new_str,
                        replace_all=edit.replace_all,
                        run_lint=should_lint,
                        status=should_check_status,
                        use_plain_text=True
                    )

                result = await asyncio.to_thread(do_replace)

                # Create FileEditResult for this edit
                edit_result = FileEditResult(
                    success=True,
                    path=path,
                    message=f"Edit {i}: Replacement completed successfully",
                    output=result.output if hasattr(result, 'output') else str(result)
                )

                results.append(edit_result)
                successful_edits += 1

            except Exception as e:
                error_msg = f"Edit {i} failed: {str(e)}"

                if ctx:
                    await ctx.error(error_msg)

                # Create failed result for this edit
                edit_result = FileEditResult(
                    success=False,
                    path=path,
                    message=error_msg,
                    output=error_msg
                )
                results.append(edit_result)
                failed_edits += 1

                # Restore original file content on failure (atomic operation)
                if backup_made and original_content is not None:
                    try:
                        file_path = Path(path)
                        file_path.write_text(original_content, encoding='utf-8')
                        if ctx:
                            await ctx.info(f"Restored original content of {path} after edit failure")
                        error_msg = f"Edit {i} of {len(edits)} failed: {str(e)} - all edits reverted (file restored to original state)"
                    except Exception as restore_error:
                        error_msg += f" (WARNING: Failed to restore original file: {str(restore_error)})"
                        if ctx:
                            await ctx.error(f"Failed to restore original file: {str(restore_error)}")

                # Stop on first failure - edits are sequential and dependent
                break

        if ctx:
            await ctx.report_progress(len(edits), len(edits))

        # Determine overall success
        overall_success = failed_edits == 0
        if overall_success:
            register_touched_path(path)
        # Get final output and lint results
        final_output = results[-1].output if results else "No edits performed"

        # Create summary message
        if overall_success:
            summary_message = f"Successfully applied {successful_edits} edit(s) to {path}"
            actual_successful = successful_edits
        else:
            # When we fail, all edits are rolled back due to atomic operation
            if backup_made and failed_edits > 0:
                summary_message = f"All {successful_edits} edit(s) reverted due to failure at edit {successful_edits + 1} of {len(edits)} (file restored to original state)"
                actual_successful = 0  # No edits persisted due to rollback
            else:
                summary_message = f"Applied {successful_edits} edit(s), {failed_edits} failed on {path}"
                actual_successful = successful_edits

        if ctx:
            await ctx.info(summary_message)

        return MultiEditResult(
            success=overall_success,
            path=path,
            total_edits=len(edits),
            successful_edits=actual_successful,
            failed_edits=failed_edits,
            results=results,
            output=summary_message if not overall_success else final_output,
            lint_results=None
        )

    except Exception as e:
        error_msg = f"Multi-edit operation failed: {str(e)}"

        # Restore original file content on any failure (atomic operation)
        if backup_made and original_content is not None:
            try:
                file_path = Path(path)
                file_path.write_text(original_content, encoding='utf-8')
                error_msg += " (file reverted to original state)"
                if ctx:
                    await ctx.info(f"Restored original content of {path} after operation failure")
            except Exception as restore_error:
                error_msg += f" (WARNING: Failed to restore original file: {str(restore_error)})"
                if ctx:
                    await ctx.error(f"Failed to restore original file: {str(restore_error)}")

        if ctx:
            await ctx.error(error_msg)

        return MultiEditResult(
            success=False,
            path=path,
            total_edits=len(edits),
            successful_edits=successful_edits,
            failed_edits=failed_edits,
            results=results,
            output=error_msg,
            lint_results=None
        )


@mcp.tool(
    description="""
    Insert text at a specific line number in a file
    * Text is inserted AFTER the specified line number
    * Line numbers use 1-based indexing (first line is 1)
    * Use when you need to add content without replacing existing text
    * Good for adding imports, new functions, or comments
    """,
    annotations={
        "destructiveHint": True,  # This modifies files
        "idempotentHint": False   # Multiple inserts are not idempotent
    }
)
async def insert_text(
    path: Annotated[str, Field(description="The absolute path to the file to modify")],
    new_str: Annotated[str, Field(description="Text to insert into the file")],
    insert_line: Annotated[int, Field(
        description="""
        Line number AFTER which the text will be inserted.
        * Uses 1-based indexing (first line is 1)
        * Text appears on line insert_line + 1
        * Use 0 to insert at the beginning of the file
        """,
        ge=0
    )],
    ctx: Context = None
) -> FileEditResult:
    """
    Insert text at specified line in file.

    Inserts new text after the specified line number.
    Line numbers use 1-based indexing.
    """
    if ctx:
        await ctx.report_progress(0, 100)
        await ctx.info(f"Inserting text at line {insert_line} in {path}")

    try:
        # Run the synchronous EditTool in a thread pool
        def do_insert():
            edit_tool = get_edit_tool()

            # Pass plain text directly with use_plain_text flag
            return edit_tool(
                command="insert",
                path=path,
                new_str=new_str,
                insert_line=insert_line,
                run_lint=False,
                use_plain_text=True
            )

        result = await asyncio.to_thread(do_insert)
        register_touched_path(path)

        if ctx:
            await ctx.report_progress(100, 100)

        return FileEditResult(
            success=True,
            path=path,
            message=f"Text inserted at line {insert_line}",
            output=result.output if hasattr(result, 'output') else str(result),
            lines_affected=len(new_str.splitlines()),
            lint_results=None
        )

    except Exception as e:
        if ctx:
            await ctx.error(f"Text insertion failed: {e}")

        return FileEditResult(
            success=False,
            path=path,
            message=f"Text insertion failed: {str(e)}",
            output=f"Text insertion failed: {str(e)}"
        )


# ============================================================================
# Linting Tools - Direct Registration
# ============================================================================

@mcp.tool(
    description="""Python code linting and static analysis.
- Run before calling the testing subagent
- Checks for syntax errors, undefined variables, unused imports, production bugs (e.g. serialization issues, route ordering), and style violations
- Supports single files, directories, and glob patterns
- Preferred to run in parallel""",
    annotations={
        "readOnlyHint": False,  # Can modify files when fix=True
        "openWorldHint": True  # Reads from file system
    }
)
async def lint_python(
    path_pattern: Annotated[str, Field(
        description="File/directory path or glob pattern to lint"
    )],
    exclude_patterns: Annotated[Optional[List[str]], Field(
        description="List of glob patterns to exclude from linting"
    )] = None,
    fix: Annotated[bool, Field(
        description="Automatically fix safe issues. Use ONLY for single files, not directories/patterns"
    )] = False,
    ctx: Context = None
) -> LintResult:
    """
    Python linting tool using ruff.

    Checks Python code for errors and style issues.
    Supports single files, directories, and glob patterns.
    """
    if ctx:
        await ctx.info(f"Linting Python code at: {path_pattern}")

    try:
        from linters.lint_utils import approx_tokens
        from linters.lint_tools import run_python_linter

        lint_result = await asyncio.to_thread(
            run_python_linter,
            [path_pattern],
            "manual",
            exclude_patterns,
            fix,
        )
        output = lint_result.raw_output

        blocking_count, advisory_count = lint_result.blocking_count, lint_result.advisory_count
        logger.info(
            "[LINTER-METRIC] type=lint_tool_invocation tool=lint_python path=%s "
            "blocking=%d advisory=%d output_chars=%d output_tokens=%d "
            "engine_success=%s is_lint_failure=%s",
            path_pattern, blocking_count, advisory_count, len(output or ""), approx_tokens(output),
            lint_result.engine_success, blocking_count > 0,
        )

        # Tool error only on a genuine engine crash; blocking findings are a lint
        # failure carried via the output directive. Advisory isn't a gating factor
        # (no warning-level checks run), so block only on blocking + engine.
        if blocking_count == 0 and not lint_result.engine_success:
            raise ToolError(output)

        return LintResult(
            success=True,
            path=path_pattern,
            output=output
        )

    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Python linting failed: {e}")
        raise ToolError(f"Linting failed: {str(e)}")


@mcp.tool(
    description="""JavaScript/TypeScript code linting and static analysis.
- Run before calling the testing subagent
- Checks for syntax errors, undefined variables, unused variables, import validation, and style violations
- Supports .js, .jsx, .ts, .tsx files and patterns
- Preferred to run in parallel""",
    annotations={
        "readOnlyHint": False,  # Can modify files when fix=True
        "openWorldHint": True
    }
)
async def lint_javascript(
    path_pattern: Annotated[str, Field(
        description="File/directory path or glob pattern to lint"
    )],
    exclude_patterns: Annotated[Optional[List[str]], Field(
        description="List of glob patterns to exclude from linting"
    )] = None,
    fix: Annotated[bool, Field(
        description="Automatically fix safe issues. Use ONLY for single files, not directories/patterns"
    )] = False,
    ctx: Context = None
) -> LintResult:
    """
    JavaScript/TypeScript linting tool using ESLint.

    Checks JavaScript/JSX/TypeScript code for errors and style issues.
    Supports single files, directories, and glob patterns.
    """
    if ctx:
        await ctx.info(f"Linting code at: {path_pattern}")

    # Legacy ESLint drives success/failure AND is the only output the agent
    # sees. The internal linter runs as a pure side-effect for telemetry —
    # its per-finding [LINTER-METRIC] logs land in Loki/Grafana from inside
    # run_javascript_internal. Its return value is intentionally discarded.
    try:
        from linters.lint_utils import approx_tokens
        from linters.lint_tools import run_javascript_internal, run_javascript_linter

        # When fix=True, legacy ESLint mutates files; run sequentially so the
        # shadow pass reads post-fix state. Otherwise run concurrently.
        if fix:
            legacy_result = await run_javascript_linter(
                [path_pattern], trigger="manual",
                exclude_patterns=exclude_patterns, fix=True,
            )
            internal_or_exc = await asyncio.gather(
                run_javascript_internal(
                    [path_pattern], trigger="manual",
                    exclude_patterns=exclude_patterns,
                ),
                return_exceptions=True,
            )
            internal_result = internal_or_exc[0]
        else:
            legacy_result, internal_result = await asyncio.gather(
                run_javascript_linter(
                    [path_pattern], trigger="manual",
                    exclude_patterns=exclude_patterns, fix=False,
                ),
                run_javascript_internal(
                    [path_pattern], trigger="manual",
                    exclude_patterns=exclude_patterns,
                ),
                return_exceptions=True,
            )

        if isinstance(legacy_result, BaseException):
            raise legacy_result
        if isinstance(internal_result, BaseException):
            # Shadow pass is best-effort; failures are non-fatal and don't
            # affect what the agent sees.
            logger.warning("internal JS lint failed (shadow): %s", internal_result)

        output = legacy_result.raw_output or ""

        blocking_count, advisory_count = legacy_result.blocking_count, legacy_result.advisory_count
        logger.info(
            "[LINTER-METRIC] type=lint_tool_invocation tool=lint_javascript path=%s "
            "blocking=%d advisory=%d output_chars=%d output_tokens=%d "
            "engine_success=%s is_lint_failure=%s",
            path_pattern, blocking_count, advisory_count, len(output or ""), approx_tokens(output),
            legacy_result.engine_success, blocking_count > 0,
        )

        # Tool error only on a genuine engine crash; blocking findings are a lint
        # failure carried via the output directive. Advisory isn't a gating factor
        # (no warning-level checks run), so block only on blocking + engine.
        if blocking_count == 0 and not legacy_result.engine_success:
            raise ToolError(output)

        return LintResult(
            success=True,
            path=path_pattern,
            output=output
        )

    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"JavaScript linting failed: {e}")
        raise ToolError(f"Linting failed: {str(e)}")


# ============================================================================
# Bash Execution Tool
# ============================================================================

@mcp.tool(
    description="""Execute bash commands with full shell features.
Supports both foreground and background execution.
Foreground execution has a timeout of 120 seconds. So use background execution for long running commands and check logs periodically
For background processes, append '&' to your command.
Use standard bash job control (jobs, fg, bg, kill, wait) for process management.

Returns stdout, stderr, and exit code in a structured format.

Examples:
- Foreground: "ls -la"
- Background: "sleep 60 &"
- Check jobs: "jobs"
- Kill job: "kill %1" or "kill <PID>"
- Wait for job: "wait %1" or "wait <PID>"
- Check files in an folder with depth 3: "fd . /app -d 3"

Args:
    command: The bash command to execute
    timeout: Maximum execution time in seconds (default: 60)
    cwd: Working directory for command execution (optional)

Usage Notes:
- Avoid using execute_bash with the `cat`, `head`, `sed`, `tail`, `awk`, or `echo` commands, unless explicitly instructed or when these commands are truly necessary for the task. Instead, always prefer using the dedicated tools for these commands:
   - File search: Use glob_files (NOT find or ls)
   - Read multiple files or folders: Use view_file or view_bulk tool (NOT cat/head/tail)
   - Read files: Use view_file (NOT cat/head/tail)
   - Edit files: Use `search_replace` tool (NOT sed/awk)
   - Write files: Use create_file (NOT cat > /tmp/test_convee_flow.py << 'EOF')

- When issuing multiple commands:
   - If the commands are independent and can run in parallel, make multiple bash tool calls in a single message ie multiple bash tool calls in parallel.
   - If the commands depend on each other and must run sequentially, use a single bash call with '&&' to chain them together."""
)
async def execute_bash(
    ctx: Context,
    command: Annotated[str, Field(description="Bash command to execute")],
    timeout: Annotated[int, Field(description="Timeout in seconds", ge=1, le=300)] = 120,
    cwd: Annotated[Optional[str], Field(description="Working directory")] = None
) -> BashResult:
    """Execute a bash command and return structured results."""
    import tempfile

    script_path = None
    try:
        if ctx:
            await ctx.info(f"Executing: {command}")

        # Create a temporary script file to avoid shell escaping issues
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            script_path = f.name
            # Write shebang and command
            f.write('#!/bin/bash\n')
            f.write(command)

        # Make script executable
        os.chmod(script_path, 0o755)

        # Run the script file instead of passing command directly to shell
        proc = await asyncio.create_subprocess_exec(
            '/bin/bash', script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        # Wait with timeout
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            stderr = (stderr or b'') + f'\n[Command timed out after {timeout} seconds]'.encode()

        # Decode output
        stdout_str = stdout.decode('utf-8', errors='replace') if stdout else ''
        stderr_str = stderr.decode('utf-8', errors='replace') if stderr else ''

        # Persist full output before truncation (if middleware set the context).
        # Build the full combined output first for persistence.
        full_parts = []
        if stdout_str.strip():
            full_parts.append(stdout_str.rstrip())
        if stderr_str.strip():
            full_parts.append(f"[stderr] {stderr_str.rstrip()}")
        full_parts.append(f"Exit code: {proc.returncode}")
        full_output = '\n'.join(full_parts)
        from plugins.tools.agent.middleware.mcp_output_persistence import persist_full_output
        persist_full_output(full_output)

        # Truncate output to 40000 chars
        MAX_OUTPUT_LENGTH = 40000

        # Reserve space for stderr and exit code when truncating
        # This ensures we always show some stderr and the exit code
        RESERVED_FOR_STDERR = 2000  # Reserve 2K for stderr
        RESERVED_FOR_EXIT_CODE = 50  # Reserve space for exit code line

        stdout_truncated = False
        stderr_truncated = False

        # Calculate available space for stdout (leave room for stderr and exit code)
        stdout_max = MAX_OUTPUT_LENGTH - RESERVED_FOR_STDERR - RESERVED_FOR_EXIT_CODE
        if len(stdout_str) > stdout_max:
            stdout_str = stdout_str[:stdout_max] + '\n... [stdout truncated]'
            stdout_truncated = True

        # Truncate stderr if needed
        if len(stderr_str) > RESERVED_FOR_STDERR:
            stderr_str = stderr_str[:RESERVED_FOR_STDERR] + '\n... [stderr truncated]'
            stderr_truncated = True

        # Format pretty output - always include exit code
        output_parts = []
        if stdout_str.strip():
            output_parts.append(stdout_str.rstrip())
        if stderr_str.strip():
            output_parts.append(f"[stderr] {stderr_str.rstrip()}")

        # Always include exit code
        output_parts.append(f"Exit code: {proc.returncode}")

        output = '\n'.join(output_parts)

        # Final safety check - truncate combined output if still too long
        if len(output) > MAX_OUTPUT_LENGTH:
            # Keep the exit code at the end
            exit_code_line = f"\nExit code: {proc.returncode}"
            max_content_length = MAX_OUTPUT_LENGTH - len(exit_code_line) - 30  # 30 for truncation message
            output = output[:max_content_length] + '\n... [output truncated]' + exit_code_line

        if ctx:
            await ctx.info(f"Command completed with exit code: {proc.returncode}")

        return BashResult(
            success=proc.returncode == 0,
            command=command,
            stdout=stdout_str,
            stderr=stderr_str,
            return_code=proc.returncode,
            output=output
        )

    except Exception as e:
        # Handle execution errors
        error_msg = f"Failed to execute command: {str(e)}"

        if ctx:
            await ctx.error(error_msg)

        output = f"$ {command}\n[Error] {error_msg}\nExit code: -1"

        return BashResult(
            success=False,
            command=command,
            stdout='',
            stderr=error_msg,
            return_code=-1,
            output=output
        )

    finally:
        # Clean up the temporary script file
        if script_path and os.path.exists(script_path):
            try:
                os.unlink(script_path)
            except Exception:
                pass  # Ignore cleanup errors


# ============================================================================
# Todo Management Tools
# ============================================================================

@mcp.tool(
    description=TODO_WRITE_DESCRIPTION,
    annotations={
        "readOnlyHint": False,  # This modifies the todo list
        "idempotentHint": True  # Same todo list is idempotent
    }
)
async def todo_write(
    todos: Annotated[List[TodoItem], Field(
        description="""
        List of TodoItem objects, each containing:
        - content: Brief description of the task
        - status: pending, in_progress, completed, or cancelled
        """
    )],
    ctx: Context = None
) -> TodoWriteResult:
    """
    Write/update the todo list.

    Replaces the entire todo list with the provided items.
    """
    if ctx:
        await ctx.info(f"Updating todo list with {len(todos)} items")

    try:
        # Get the todo tools module and call write_todos with TodoItem objects
        todo_module = get_todo_tools()
        result : TodoWriteResult = await asyncio.to_thread(todo_module.write_todos, todos)

        if ctx and result.success:
            await ctx.info(f"Todo list updated: {result.todo_count} incomplete items")

        # Return the result as a dict for MCP compatibility
        return result

    except Exception as e:
        if ctx:
            await ctx.error(f"Failed to write todos: {e}")

        raise Exception(f"Failed to write todos: {e}")



# ============================================================================
# Browser Automation Tools
# ============================================================================

async def _browser_automation_impl(
    page_url: Annotated[str, Field(
        description="URL of the webpage to automate"
    )],
    script: Annotated[str, Field(
        description=BROWSER_AUTOMATION_SCRIPT_DESCRIPTION
    )],
    capture_logs: Annotated[bool, Field(
        description="Whether to capture browser console logs"
    )] = True,
    output_dir: Annotated[str, Field(
        description="Directory for screenshots and logs"
    )] = ".screenshots",
    ctx: Context = None
) -> BrowserAutomationResult:
    """
    Execute browser automation with Playwright.

    Runs a Playwright script on the specified URL and returns results
    including screenshots, console logs, and script output.
    """
    if ctx:
        await ctx.info(f"Starting browser automation on {page_url}")

    try:
        # Import the script handler
        from plugins.tools.agent.qabot_script_handler import execute_playwright_script

        # Execute the script
        result = await execute_playwright_script(
            script=script,
            url=page_url,
            output_dir=output_dir,
            capture_logs=capture_logs,
            collect_print_logs=True,
            mcp_flow = True
        )

        # Process the result
        success = result.get("status") == "success"
        data = result.get("data", {})

        # Format output
        output_parts = data.get("print_logs", [])

        if data.get("console_logs"):
            output_parts.append(f"Console logs saved: {', '.join(data['console_logs'])}")

        if data.get("error"):
            output_parts.append(f"Error: {data['error']}")
            success = False


        output = "\n".join(output_parts)
        output = truncate_output(output)

        # Normalise screenshots into ImageContent objects
        screenshot_images = _build_image_contents(data.get("screenshots", []), max_images=5)

        if ctx:
            if success:
                await ctx.info("Browser automation completed successfully")
            else:
                await ctx.error(f"Browser automation failed: {data.get('error')}")

        return BrowserAutomationResult(
            success=success,
            url=page_url,
            images=screenshot_images,
            console_logs=data.get("console_logs", []),
            error=data.get("error"),
            script_output=data.get("output"),
            output=output
        )

    except Exception as e:
        error_msg = f"Browser automation failed: {str(e)}"
        if ctx:
            await ctx.error(error_msg)

        return BrowserAutomationResult(
            success=False,
            url=page_url,
            images=[],
            console_logs=[],
            error=error_msg,
            script_output=None,
            output=error_msg
        )


@mcp.tool(
    description=BROWSER_AUTOMATION_TOOL_DESCRIPTION,
    annotations={
        "destructiveHint": False,  # Read-only browser automation
        "openWorldHint": True      # Interacts with external websites
    }
)
async def browser_automation(
    page_url: Annotated[str, Field(
        description="URL of the webpage to automate"
    )],
    script: Annotated[str, Field(
        description=BROWSER_AUTOMATION_SCRIPT_DESCRIPTION
    )],
    capture_logs: Annotated[bool, Field(
        description="Whether to capture browser console logs"
    )] = False,
    output_dir: Annotated[str, Field(
        description="Directory for screenshots and logs"
    )] = ".screenshots",
    ctx: Context = None
) -> BrowserAutomationResult:
    """Execute browser automation with Playwright - wrapper for the implementation."""
    return await _browser_automation_impl(
        page_url=page_url,
        script=script,
        capture_logs=capture_logs,
        output_dir=output_dir,
        ctx=ctx
    )


@mcp.tool(
    description="""Execute screenshot commands using Playwright. Use this tool to take screenshots of the webpage while building.""",
    annotations={
        "destructiveHint": False,
        "openWorldHint": True
    }
)
async def screenshot_tool(
    page_url: Annotated[str, Field(
        description="URL of the webpage to take screenshot of"
    )],
    script: Annotated[str, Field(
        description=SCREENSHOT_SCRIPT_DESCRIPTION
    )],
    capture_logs: Annotated[bool, Field(
        description="Whether to capture browser console logs"
    )] = False,
    ctx: Context = None
) -> BrowserAutomationResult:
    """Run Playwright screenshot scripts via the browser automation backend."""

    script, _stripped = _strip_trailing_markup(script)
    if _stripped:
        logger.info("screenshot_tool: stripped trailing markup from script")

    return await _browser_automation_impl(
        page_url=page_url,
        script=script,
        capture_logs=capture_logs,
        output_dir=".screenshots",
        ctx=ctx
    )


@mcp.tool(
    description=RUN_TS_PLAYWRIGHT_DESCRIPTION,
    annotations={
        "destructiveHint": False,
        "openWorldHint": True
    }
)
async def run_ts_playwright(
    spec_inline: Annotated[str, Field(
        description="Inline TypeScript spec content (a complete @playwright/test spec). Mutually exclusive with spec_path."
    )] = "",
    spec_path: Annotated[str, Field(
        description="Absolute path to an existing .spec.ts file on disk (e.g. /app/tests/e2e/homepage.spec.ts). Mutually exclusive with spec_inline."
    )] = "",
    page_url: Annotated[str, Field(
        description="Base URL of the app under test (e.g. http://localhost:3000). Used as baseURL in Playwright config."
    )] = "",
    capture_all_screenshots: Annotated[bool, Field(
        description="If true, capture screenshots on every test (pass and fail). If false, only on failure."
    )] = False,
    output_dir: Annotated[str, Field(
        description="Directory for collected screenshots"
    )] = ".screenshots",
    timeout: Annotated[int, Field(
        description="Maximum execution time in seconds. Default 300 (5 minutes). The MCP infrastructure enforces a hard 300s limit, so values above 300 have no effect. Use lower values for quick smoke tests.",
        ge=10,
        le=300,
    )] = 300,
    inline_screenshots: Annotated[bool, Field(
        description="If true, return screenshots as inline images in the response. If false (default), screenshots are saved to disk — use the read tool on paths from the output to view them."
    )] = False,
    description: Annotated[Optional[str], Field(
        description="Operator status ping. Always fill — tests are long. 3-5 words max. e.g. 'Scanning login sequence', 'Probing checkout flow'."
    )] = None,
    ctx: Context = None
) -> PlaywrightResult:
    """Run a TypeScript Playwright spec and return test results."""
    if ctx:
        await ctx.info("Starting TypeScript Playwright test run")

    try:
        from plugins.tools.agent.ts_playwright_runner import execute_ts_playwright

        spec_content = spec_inline.strip() if spec_inline else None
        spec_file = spec_path.strip() if spec_path else None

        if not spec_content and not spec_file:
            raise ValueError(
                "Either spec_inline or spec_path must be provided"
            )
        if spec_content and spec_file:
            raise ValueError(
                "Provide only one of spec_inline or spec_path, not both"
            )

        result = await execute_ts_playwright(
            spec_content=spec_content,
            spec_file=spec_file,
            base_url=page_url if page_url else None,
            output_dir=output_dir,
            capture_all_screenshots=capture_all_screenshots,
            timeout=timeout,
        )

        data = result.get("data", {})

        output_parts = data.get("print_logs", [])
        if data.get("error"):
            output_parts.append(f"Error: {data['error']}")

        json_report = data.get("json_report")
        if json_report:
            output_parts.append(f"\nFull report: {json_report}")

        output = "\n".join(output_parts)
        success = result.get("status") == "success"

        images = []
        if inline_screenshots:
            images = _build_image_contents(data.get("screenshots", []), max_images=5, resize=True)

        return PlaywrightResult(
            success=success,
            images=images,
            output=output,
        )

    except Exception as e:
        return PlaywrightResult(
            success=False,
            output=f"TypeScript Playwright runner failed: {str(e)}",
        )


@mcp.tool(
    description=RUN_BROWSER_USE_DESCRIPTION,
    annotations={
        "destructiveHint": False,  # Read-only browser automation
        "openWorldHint": True,     # Interacts with external websites / LLM
    },
)
async def run_browser_use(
    page_url: Annotated[str, Field(
        description="URL of the application under test (e.g. https://jsonbuddy.online)."
    )],
    test_cases: Annotated[List[str], Field(
        description=(
            "One or more natural-language test cases. Each is wrapped in a "
            "verdict-producing prompt and run sequentially in a single "
            "shared browser session."
        ),
        min_length=1,
    )],
    llm_api_key: Annotated[str, Field(
        description=(
            "Bearer token for the OpenAI-compatible LLM endpoint. When using "
            "the default Emergent integration-proxy base URL this is an "
            "Emergent API key (`sk-emergent-...`); the proxy substitutes the "
            "real provider key server-side so no raw key is needed on the "
            "host. Required; never read from environment."
        ),
    )],
    system_prompt: Annotated[Optional[str], Field(
        description=(
            "Optional extra instructions prepended verbatim to every test "
            "case prompt (persona, auth setup, stop conditions, etc.)."
        ),
    )] = None,
    llm_base_url: Annotated[str, Field(
        description=(
            "OpenAI-compatible base URL ending at the version root "
            "(e.g. `.../v1`). Default is resolved at plugin-library import "
            "time from the pod's `INTEGRATION_PROXY_URL` / "
            "`integration_proxy_url` env var so dev / staging / prod / "
            "wingman pods each route to their own integration-proxy. Falls "
            "back to the production endpoint when neither env var is set."
        ),
    )] = _DEFAULT_LLM_BASE_URL,
    llm_model: Annotated[str, Field(
        description=(
            "LiteLLM model identifier (e.g. `gemini/gemini-3-flash-preview`, "
            "`openai/gpt-4o-mini`, `anthropic/claude-3-5-sonnet`). Default "
            "is the only Gemini model verified to accept the sampling "
            "parameters browser-use sends through the proxy."
        ),
    )] = "gemini/gemini-3-flash-preview",
    max_steps_per_test: Annotated[int, Field(
        description="Max agent steps per test case.",
        ge=1,
        le=100,
    )] = 30,
    timeout_per_test: Annotated[int, Field(
        description="Wall-clock timeout per test case, in seconds.",
        ge=10,
        le=600,
    )] = 300,
    headless: Annotated[bool, Field(
        description="Run Chromium headless. Default True."
    )] = True,
    ctx: Context = None,
) -> BrowserUseResult:
    """Drive `browser-use` against `page_url` with a batch of test cases."""
    if ctx:
        await ctx.info(
            f"Running {len(test_cases)} browser-use test(s) on {page_url} "
            f"(model={llm_model})"
        )

    try:
        from plugins.tools.agent.browser_use_runner import execute_browser_use_tests
    except ImportError as e:
        return BrowserUseResult(
            success=False,
            url=page_url,
            error=f"browser_use_runner import failed: {e}",
            output=f"Failed to import browser_use_runner: {e}",
        )

    try:
        raw = await execute_browser_use_tests(
            page_url=page_url,
            test_cases=test_cases,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            system_prompt=system_prompt,
            timeout_per_test_s=timeout_per_test,
            max_steps_per_test=max_steps_per_test,
            headless=headless,
        )
    except Exception as e:
        error_msg = f"browser-use runner raised: {e}"
        if ctx:
            await ctx.error(error_msg)
        return BrowserUseResult(
            success=False,
            url=page_url,
            error=error_msg,
            output=error_msg,
        )

    data = raw.get("data", {})
    top_level_error = data.get("error")
    per_test = [
        BrowserUseTestResult(
            test_name=r.get("test_name", ""),
            status=r.get("status", "error"),  # type: ignore[arg-type]
            details=r.get("details", ""),
            steps=int(r.get("steps", 0) or 0),
        )
        for r in data.get("results", [])
    ]
    pass_count = int(data.get("pass_count", 0) or 0)
    fail_count = int(data.get("fail_count", 0) or 0)
    error_count = sum(1 for r in per_test if r.status == "error")

    # Tool is "successful" iff the runner ran, every test produced a verdict,
    # and all verdicts were pass.
    success = (
        raw.get("status") == "success"
        and not top_level_error
        and error_count == 0
        and fail_count == 0
        and pass_count == len(per_test)
        and len(per_test) > 0
    )

    output_lines: list[str] = []
    if top_level_error:
        output_lines.append(f"Error: {top_level_error}")
    for idx, r in enumerate(per_test, 1):
        output_lines.append(
            f"[{idx}/{len(per_test)}] {r.status.upper()} "
            f"(steps={r.steps}) — {r.test_name[:80]}"
        )
        if r.details:
            output_lines.append(f"    {r.details[:400]}")
    output_lines.append(
        f"Summary: {pass_count} pass, {fail_count} fail, {error_count} error"
    )
    for log_line in data.get("print_logs", [])[-10:]:
        output_lines.append(f"  log: {log_line}")

    output = truncate_output("\n".join(output_lines))

    if ctx:
        if success:
            await ctx.info(f"browser-use: {pass_count}/{len(per_test)} passed")
        else:
            await ctx.error(
                f"browser-use: {fail_count} fail, {error_count} error, "
                f"{pass_count} pass"
            )

    return BrowserUseResult(
        success=success,
        url=page_url,
        pass_count=pass_count,
        fail_count=fail_count,
        results=per_test,
        error=top_level_error,
        output=output,
    )


# ============================================================================
# Bulk File Operations Tools
# ============================================================================

@mcp.tool(
    description="""
    Write multiple files simultaneously for improved performance

    * Preferred over single-file tools when creating/overwriting multiple files
    * Handles bulk operations efficiently with atomic writes
    * Do not escape special characters (e.g., '\n' should remain as '\n', not '\\n').
    * Supports status monitoring and log capture

    Usage:
    - All paths must be absolute paths
    - Optionally monitor system status and capture logs after operation
    <example>
    files: [
    {
        "path": "/app/backend/server.py",
        "content": "# Python code here\nprint('hello')"
    },
    {
        "path": "/app/frontend/src/App.js",
        "content": "import React from 'react';\n\nfunction App() {\n  return <div>Hello</div>;\n}"
    }
    ]
    </example>
    """,
    annotations={
        "destructiveHint": True,  # This creates/overwrites files
        "idempotentHint": True    # Same content writes are idempotent
    }
)
async def bulk_file_writer(
    files: Annotated[BulkFilesList, Field(
        description="""
        List of files to create/overwrite. Each item must be an object with 'path' and
        'content' fields.
        IMPORTANT: This must be an actual array of objects, not a JSON string.
        DO NOT pass as a JSON-encoded string - the array will be handled automatically.
        """,
        min_length=1
    )],
    status: Annotated[bool, Field(
        description="Check system services status after file operations"
    )] = False,
    capture_logs_frontend: Annotated[bool, Field(
        description="Capture frontend logs after file operations"
    )] = False,
    capture_logs_backend: Annotated[bool, Field(
        description="Capture backend logs after file operations"
    )] = False,
    ctx: Context = None
) -> BulkFileWriterResult:
    """
    Write multiple files simultaneously using bulk operations.

    Creates or overwrites multiple files in a single efficient operation.
    Supports status monitoring and log capture for system verification.
    """
    # Try to parse JSON string if provided
    if isinstance(files, str):
        import json
        try:
            parsed = json.loads(files)
            if isinstance(parsed, list):
                # Convert parsed dicts to BulkFileItem objects
                try:
                    files = [BulkFileItem(**item) if isinstance(item, dict) else item for item in parsed]
                except (TypeError, ValueError) as e:
                    # Re-raise with a cleaner message about invalid item format
                    raise ValueError(
                        f'Invalid file item format in JSON. Each item must have "path" and "content" fields.'
                    ) from None
            else:
                raise ValueError(
                    'Files parameter must be an array of file objects, not a JSON string. '
                    'Example: [{"path": "/app/file.py", "content": "..."}]'
                )
        except json.JSONDecodeError:
            # Only show the string error if JSON parsing fails
            raise ValueError(
                'Files parameter must be an array of file objects, not a string. '
                'Example: [{"path": "/app/file.py", "content": "..."}]'
            ) from None

    if len(files) == 0:
        raise ValueError('Files parameter must contain at least one file item')

    # Validate each item is a BulkFileItem
    for i, item in enumerate(files):
        if not isinstance(item, BulkFileItem):
            raise ValueError(
                f'Item {i} must be a BulkFileItem with "path" and "content" fields. '
                f'Received type: {type(item).__name__}'
            )

    if ctx:
        await ctx.report_progress(0, 100)
        await ctx.info(f"Writing {len(files)} files in bulk operation")

    try:
        # Extract paths and contents from BulkFileItem models
        paths = []
        contents = []

        for i, file_item in enumerate(files):
            # BulkFileItem model handles validation automatically
            path = file_item.path
            content = file_item.content

            if not path.startswith('/'):
                raise ValueError(f"File {i} path must be absolute: {path}")

            paths.append(path)
            contents.append(content)

        if ctx:
            await ctx.report_progress(25, 100)

        # Run BulkCreateTool in thread pool with plain text
        def do_bulk_create():
            bulk_tool = get_bulk_create_tool()
            return bulk_tool(
                paths=paths,
                texts=contents,  # Pass plain text directly
                status=status,
                capture_logs_frontend=capture_logs_frontend,
                capture_logs_backend=capture_logs_backend,
                use_plain_text=True  # Use plain text flag
            )

        # NOTE: BulkCreateTool returns (ToolResult, success_paths) — corresponding
        # changes in cli required if this signature is changed (see
        # plugins/tools/file_editor/__init__.py:bulk_file_creator).
        result, success_paths = await asyncio.to_thread(do_bulk_create)

        # Only register written paths — registering failed ones would have the
        # lint middleware try to lint files that don't exist.
        for p in success_paths:
            register_touched_path(p)

        if ctx:
            await ctx.report_progress(100, 100)

        # Extract result information
        output = result.output if hasattr(result, 'output') else str(result)
        success = not hasattr(result, 'error') or not result.error

        # Try to determine how many files were processed
        files_processed = len(files) if success else 0
        failed_files = None

        # Parse output for any file-specific failures
        if not success and hasattr(result, 'error') and result.error:
            # If there was an error, mark all files as potentially failed
            failed_files = paths
            files_processed = 0

        if ctx:
            if success:
                await ctx.info(f"Successfully wrote {files_processed} files")
            else:
                await ctx.error("Bulk file write operation failed")

        return BulkFileWriterResult(
            success=success,
            files_processed=files_processed,
            output=output,
            failed_files=failed_files
        )

    except Exception as e:
        error_msg = f"Bulk file write failed: {str(e)}"

        if ctx:
            await ctx.error(error_msg)


        return BulkFileWriterResult(
            success=False,
            files_processed=0,
            output=error_msg,
            failed_files=[file_item.path for file_item in files]
        )


class GlobResult(BaseModel):
    """Result of glob file matching operation."""
    success: bool
    pattern: str
    search_path: str
    matches: List[str]
    count: int
    output: str

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


# Gitignored file patterns to always include in glob results.
# These are searched separately with --hidden --no-ignore so they
# show up even when gitignored (e.g. .env files in a project).
# Add new patterns here to extend coverage (e.g. ".secret", ".credentials").
GITIGNORED_INCLUDE_PATTERNS = [".env*"]


async def _run_fd(cmd: list[str], raise_on_error: bool = False) -> list[str]:
    """Run fd command and return list of matched file paths."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0 and stdout:
        return [f.strip() for f in stdout.decode('utf-8').strip().split('\n') if f.strip()]
    if raise_on_error and proc.returncode != 0 and stderr:
        error = stderr.decode('utf-8', errors='replace').strip()
        if "is not a directory" in error or "No such file" in error:
            raise ValueError(error)
    return []


@mcp.tool(
    description="""Fast file pattern matching tool that works with any codebase size
    - Supports glob patterns like "**/*.js" or "src/**/*.ts"
    - Returns matching file paths
    - Respects .gitignore files by default
    - Use this tool when you need to find files by name patterns
    - When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead
    - You have the capability to call multiple tools in a single response. It is always better to speculatively perform multiple searches as a batch that are potentially useful.""",
    annotations={
        "readOnlyHint": True,  # This is a read-only operation
        "openWorldHint": True  # Interacts with file system
    }
)
async def glob_files(
    pattern: Annotated[str, Field(description="The glob pattern to match files against")],
    path: Annotated[Optional[str], Field(
        description="The directory to search in. If not specified, the current working directory will be used. IMPORTANT: Omit this field to use the default directory. DO NOT enter \"undefined\" or \"null\" - simply omit it for the default behavior. Must be a valid directory path if provided."
    )] = None,
    ctx: Context = None
) -> GlobResult:
    """
    Find files matching glob patterns using fd command.

    Runs two fd calls:
    1. Normal glob respecting .gitignore
    2. .env-specific search that bypasses .gitignore
    Results are merged and deduplicated.
    """
    # If pattern contains an absolute path (e.g. /app/src/*.tsx), split it
    # into directory + filename glob so fd can match correctly.  fd's -g flag
    # matches against paths relative to the search directory, so an absolute
    # pattern like /app/src/*.tsx would never match.
    if not path and os.path.isabs(pattern):
        path = os.path.dirname(pattern)
        pattern = os.path.basename(pattern)

    search_path = path or "."

    if ctx:
        await ctx.info(f"Searching for pattern '{pattern}' in {search_path}")

    try:
        # Call 1: Normal fd respecting .gitignore
        normal = await _run_fd(["fd", "--type", "f", "-g", pattern, search_path], raise_on_error=True)

        # Call 2: Find gitignored files (e.g. .env) when the pattern could match them
        files = normal
        basename = pattern.split('/')[-1]
        should_search_gitignored = any(
            fnmatch.fnmatch(gp.rstrip("*"), basename)
            for gp in GITIGNORED_INCLUDE_PATTERNS
        )

        if should_search_gitignored:
            for gp in GITIGNORED_INCLUDE_PATTERNS:
                envs = await _run_fd([
                    "fd", "--type", "f", "--hidden", "--no-ignore",
                    "--exclude", "node_modules", "--exclude", ".git",
                    "-g", gp, search_path,
                ])
            seen = set(files)
            files = files + [f for f in envs if f not in seen]
        output = '\n'.join(files) if files else f"No files found matching pattern '{pattern}' in {search_path}"

        if ctx:
            await ctx.info(f"Found {len(files)} matching files")

        return GlobResult(
            success=True,
            pattern=pattern,
            search_path=search_path,
            matches=files,
            count=len(files),
            output=output
        )

    except ValueError as e:
        error_msg = str(e)
        if ctx:
            await ctx.error(f"Error searching for pattern: {error_msg}")
        return GlobResult(
            success=False, pattern=pattern, search_path=search_path,
            matches=[], count=0,
            output=f"Error searching for pattern '{pattern}': {error_msg}"
        )

    except FileNotFoundError:
        error_msg = "fd command not found. Please install fd (fd-find) for fast file searching."
        if ctx:
            await ctx.error(error_msg)

        return GlobResult(
            success=False,
            pattern=pattern,
            search_path=search_path,
            matches=[],
            count=0,
            output=error_msg
        )
    except Exception as e:
        # Other unexpected errors
        error_msg = f"Unexpected error during file search: {str(e)}"
        if ctx:
            await ctx.error(error_msg)

        return GlobResult(
            success=False,
            pattern=pattern,
            search_path=search_path,
            matches=[],
            count=0,
            output=error_msg
        )

# ============================================================================
# Tool Grouping and Tagging
# ============================================================================

# Tag all file operations for easier discovery
for tool in [view_file, read, create_file, apply_patch, apply_patch_freeform, search_replace, multi_search_replace, insert_text, bulk_file_writer]:
    tool.tags = {"file_operations", "editor"}

# Add additional tag for read tool
read.tags = {"file_operations", "read", "view", "unified"}

# Tag all linting tools
for tool in [lint_python, lint_javascript]:
    tool.tags = {"linting", "code_quality"}

# Tag bash execution tool
execute_bash.tags = {"system", "shell", "command"}

# Tag todo management tool
todo_write.tags = {"todo", "task_management"}

# Tag browser automation tools
for tool in [browser_automation, screenshot_tool, run_ts_playwright]:
    tool.tags = {"browser", "automation", "testing", "screenshot"}


# ============================================================================
# Skills - SKILL.md Discovery and Loading
# ============================================================================

from plugins.tools.agent.skill_tools import register_skill_tools
register_skill_tools(mcp)


# ============================================================================
# Server Execution
# ============================================================================

if __name__ == "__main__":
    # Run the FastMCP server directly
    mcp.run()
