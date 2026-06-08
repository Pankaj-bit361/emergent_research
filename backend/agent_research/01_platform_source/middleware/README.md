# MCP Middleware

## Available Middlewares

### 1. Resource Monitor (Outermost)
- **File**: `mcp_resource_monitor.py`
- **Purpose**: Appends resource warnings to `structured_content.output` if thresholds exceeded
- **Position**: Outermost — last to modify response, appends warnings after all other middleware

### 2. Output Persistence
- **File**: `mcp_output_persistence.py`
- **Purpose**: Persists full, untruncated tool outputs to disk at `/root/.emergent/tool_outputs/{tool_name}-{tool_call_id}.output`
- **Position**: Between ResourceMonitor and Idempotency — captures `request_id` before Idempotency pops it on request, persists clean output before ResourceMonitor appends warnings on response
- **Min size**: Only persists outputs >= 1000 chars
- **Why**: Tool outputs go through two lossy stages (plugin truncation at 40K-80K chars, then squasher truncation at 150 chars). This sidecar store lets the agent `tail`/`grep` into full outputs later, and Cortex can read them at squash time.

### 3. Idempotency
- **File**: `mcp_idempotency.py`
- **Purpose**: Caches tool results by `request_id` to prevent duplicate execution
- **Position**: Pops `request_id` from arguments and checks/populates LRU cache

### 4. Stringify Fix (Innermost)
- **File**: `mcp_stringify_fix.py`
- **Purpose**: Parses JSON-string arguments back into dicts/lists before Pydantic validation
- **Position**: Innermost — runs right before the tool function, fixing arguments just before Pydantic validates them
- **Why**: LLMs sometimes serialize dict params as JSON strings (e.g. `'{"path": "/root/file"}'` instead of `{"path": "/root/file"}`), which fails FastMCP's Pydantic validation. See [claude-code#3084](https://github.com/anthropics/claude-code/issues/3084).

## Execution Order

**Important**: `_apply_middleware` uses `reversed()`, so **first registered = outermost = runs first on request**.

```python
# Registration in mcp_tools.py (first registered = outermost):
mcp.add_middleware(MCPResourceMonitorMiddleware())    # 1st: outermost — appends resource warnings on response
mcp.add_middleware(MCPOutputPersistenceMiddleware())  # 2nd: captures request_id on request, persists clean output on response
mcp.add_middleware(MCPIdempotencyMiddleware())        # 3rd: pops request_id, caches results
mcp.add_middleware(MCPStringifyFixMiddleware())       # 4th: innermost — fixes stringified JSON before tool runs

# Request path (outer → inner):
ResourceMonitor (noop) → OutputPersistence (capture request_id) → Idempotency (pop request_id, cache check) → StringifyFix (parse JSON) → Tool

# Response path (inner → outer):
Tool → StringifyFix (noop) → Idempotency (cache result) → OutputPersistence (persist to disk) → ResourceMonitor (append warnings)
```

## Resource Monitoring

**Thresholds** (defined in `mcp_resource_monitor.py`):
- Memory: 80%
- CPU: 80%
- Storage:
  - Warning: 75%
  - Critical: 90% (triggers "clear the storage" message)

**Warning Format** (appended to `structured_content.output`):
```
<system_reminder>
RESOURCE WARNING:
Memory: 6.8GB/8.00GB (85.0%)
CPU: load 1.8/2.00 cores (1-min avg)
Storage: 8.5G/9.8G (87%)
NOTE: This is an automated reminder. Please do not mention this in your response.
</system_reminder>

# At 90%+ storage:
<system_reminder>
RESOURCE WARNING:
Storage: 9.2G/9.8G (94%) CRITICAL - Clear the storage immediately!
NOTE: This is an automated reminder. Please do not mention this in your response.
</system_reminder>
```

**MCP Tool**: LLM can manually check resources using `check_pod_resources()` tool.

**Performance**: CPU check uses load average (no `sleep 1` delay) - ~50ms vs ~1050ms.
