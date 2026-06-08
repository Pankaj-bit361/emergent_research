# Hidden Limits & Caps — Emergent Agent Runtime

Extracted by grepping all platform source files for MAX_/LIMIT/TIMEOUT/cap/truncate constants.

## From mcp_tools.py

```python
32:MAX_OUTPUT_CHARS = 80_000
122:IMAGE_MAX_LONG_EDGE = 1568
123:IMAGE_JPEG_QUALITY = 80
126:MIDDLE_OUT_TRUNCATION = os.environ.get("MCP_MIDDLE_OUT_TRUNCATION", "1") == "1"
142:_FETCH_URL_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap for URL reads
145:def _fetch_url(url: str, timeout: int = 30, max_bytes: int = _FETCH_URL_MAX_BYTES) -> tuple:
153:        data = resp.read(max_bytes + 1)
154:        if len(data) > max_bytes:
156:                f"Response from {url} exceeds {max_bytes // (1024 * 1024)}MB limit."
162:def truncate_output(text: Optional[str], max_length: int = MAX_OUTPUT_CHARS) -> str:
165:    When MCP_MIDDLE_OUT_TRUNCATION=1 (default), keeps the first half and last
167:    Set MCP_MIDDLE_OUT_TRUNCATION=0 for head-only truncation.
183:    if MIDDLE_OUT_TRUNCATION:
195:    """Resize image so the long edge is ≤ IMAGE_MAX_LONG_EDGE (1568px).
209:        needs_resize = long_edge > IMAGE_MAX_LONG_EDGE
216:            scale = IMAGE_MAX_LONG_EDGE / long_edge
642:MAX_VIEW_FILE_LINES = 2000
663:    view_range: Optional[List[int]], total_lines: int, max_lines: int
670:        effective_end = end if end == -1 else min(end, start + max_lines - 1, total_lines)
673:        effective_end = min(total_lines, max_lines)
754:                view_range, total_lines, MAX_VIEW_FILE_LINES
2252:        MAX_OUTPUT_LENGTH = 40000
2263:        stdout_max = MAX_OUTPUT_LENGTH - RESERVED_FOR_STDERR - RESERVED_FOR_EXIT_CODE
2286:        if len(output) > MAX_OUTPUT_LENGTH:
2289:            max_content_length = MAX_OUTPUT_LENGTH - len(exit_code_line) - 30  # 30 for truncation message
```

## From impl_ato.py

```python
62:def truncate(content, max_chars, message_type='Observation'):
64:    if len(content) <= max_chars or max_chars == -1:
67:    half = max_chars // 2
```

## From bash_tools.py

```python
33:CHUNK_SIZE = 8192
34:STDOUT_BYTE_CAP = 38_000
35:STDERR_BYTE_CAP = 2_000
36:DRAIN_TIMEOUT = 2.0
37:SIGTERM_GRACE = 1.0
38:MAX_PROCESSES = 16
169:                timeout=DRAIN_TIMEOUT,
218:    if len(_process_store) >= MAX_PROCESSES:
367:    MAX_OUTPUT_LENGTH = 40000
371:    stdout_max = MAX_OUTPUT_LENGTH - RESERVED_FOR_STDERR - RESERVED_FOR_EXIT_CODE
386:    if len(output) > MAX_OUTPUT_LENGTH:
388:        max_content = MAX_OUTPUT_LENGTH - len(exit_code_line) - 30
```

## From config.py (global config)

```python
"""Configuration management for the agent tool."""
import os
from dataclasses import dataclass

@dataclass
class AgentConfig:
    """Configuration for the agent tool."""
    base_url: str = "http://localhost:8009"
    auth_token: str = ""

    base_path: str = os.path.expanduser("~/runs")
    max_retries: int = 5
    emergent_base_path: str = os.path.expanduser("~/.emergent")
    plugin_lib_path_to_export: str = ''
    is_mock_setup: bool = False

    http_timeout: int = 1320 # 22 minutes
    http_timeout_llm_proxy: int = 9 * 60 # 9 minutes 
    http_timeout_agent_service: int = 500 
    max_iterations: int = 10000
    
    # 409 polling configuration
    poll_409_max_attempts: int = 11
    poll_timeout: int = 5*60  # timeout for each poll request
    
    # Resource monitoring thresholds (percentages)
    memory_threshold: float = 85.0  # % memory usage
    cpu_threshold: float = 80.0     # % CPU load
    storage_threshold: float = 90.0  # % disk usage

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Create configuration from environment variables."""
        config = cls(
            base_url=os.getenv("EMERGENT_BASE_URL", cls.base_url),
            auth_token=os.getenv("EMERGENT_AUTH_TOKEN", cls.auth_token),
            base_path=os.path.expanduser(os.getenv("EMERGENT_BASE_PATH", cls.base_path)),
            max_retries=int(os.getenv("EMERGENT_MAX_RETRIES", cls.max_retries)),
            http_timeout=int(os.getenv("EMERGENT_HTTP_TIMEOUT", cls.http_timeout)),
            http_timeout_agent_service=cls.http_timeout_agent_service,
            http_timeout_llm_proxy=cls.http_timeout_llm_proxy,
            max_iterations=int(os.getenv("EMERGENT_MAX_ITERATIONS", cls.max_iterations)),
            emergent_base_path = cls.emergent_base_path,
        )
        
        # Create base_path directory if it doesn't exist
        os.makedirs(config.base_path, exist_ok=True)
        
        return config

```

## From server.py (FastAPI entry)

```python
2:import hashlib
3:import json
4:import sys
5:import signal
6:import shutil
7:import threading
8:import concurrent.futures
9:import subprocess
10:import asyncio
11:import time
12:import mimetypes
13:import os
14:import tarfile
15:import uuid
16:from pathlib import Path
18:from fastapi import FastAPI, HTTPException, Request
19:from fastapi.responses import StreamingResponse
20:from pydantic import BaseModel
21:from typing import Optional, Dict, Any, List
22:import uvicorn
```

## Middleware (caching, idempotency, output persistence)

README.md
__init__.py
__pycache__
mcp_eb_lint.py
mcp_idempotency.py
mcp_output_persistence.py
mcp_resource_monitor.py
mcp_stringify_fix.py

**mcp_output_persistence.py** — this is what caches each tool output to disk:
```python
1:"""MCP output persistence middleware — saves full tool outputs to disk.
3:Uses a contextvars.ContextVar to pass persistence context (tool_name, request_id)
4:into tool handlers so that truncate_output() and inline truncation in execute_bash
5:can persist the FULL output BEFORE truncation happens.
7:The middleware also does a fallback persist on the response path for outputs that
8:weren't truncated (>= MIN_PERSIST_SIZE) but still worth saving.
20:# Context var set by middleware, read by persist_full_output().
22:_persist_ctx: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
23:    "_persist_ctx", default=None
27:def persist_full_output(text: str) -> None:
30:    Called from truncate_output() and execute_bash inline truncation.
31:    Only writes if the persistence middleware set _persist_ctx and len(text) >= MIN_PERSIST_SIZE.
33:    ctx = _persist_ctx.get()
46:        logger.warning("Failed to persist full tool output", exc_info=True)
52:    Writes every tool call's untruncated output to:
55:    Two persistence paths:
56:    1. PRE-TRUNCATION (preferred): Sets _persist_ctx before tool executes.
57:       truncate_output() and execute_bash call persist_full_output() with the
59:    2. FALLBACK: After tool returns, persists structured_content["output"] if
70:        # Set context var so persist_full_output() can write pre-truncation output
71:        token = _persist_ctx.set((tool_name, tool_call_id) if tool_call_id else None)
75:            _persist_ctx.reset(token)
77:        # Fallback: persist from structured_content if no file was written yet
84:                # Already persisted by persist_full_output() — skip
101:            logger.warning("Failed to persist tool output", exc_info=True)
```

**mcp_idempotency.py** — tool-call caching by ID:
```python
2:from cachetools import LRUCache
6:# LRU cache configuration
7:MAX_CACHE_SIZE = 30  # Maximum number of cached results
9:# Global LRU cache instance (thread-safe for single worker)
10:_cache: LRUCache = LRUCache(maxsize=MAX_CACHE_SIZE)
17:        """Hook into tool execution to cache results by request_id."""
30:        # Check cache
31:        if request_id in _cache:
33:            return _cache[request_id]
40:        _cache[request_id] = result
46:def get_cache() -> LRUCache:
47:    """Get cache for testing."""
48:    return _cache
```
