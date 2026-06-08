# Agent Research Dump

This folder contains everything we discovered about the Emergent agent runtime
that lives INSIDE this container (`agent_research`).

## What's where

### 01_platform_source/
The complete source code of the agent tool plugin server that runs in this
container on port 8010. This is what receives tool calls from the LLM brain
(`demobackend.emergentagent.com`) and executes them.

Key files:
- **server.py** (717 lines) — FastAPI entry point on :8010
- **mcp_tools.py** (3,183 lines) — definitions of every tool the LLM can call
  (mcp_create_file, mcp_execute_bash, mcp_view_file, etc.). Search for
  `@mcp_server.tool` to find every tool name.
- **mcp_server.py** (203 lines) — MCP (Model Context Protocol) wiring.
  This is the protocol Anthropic uses to expose tools to Claude.
- **impl_ato.py** (1,157 lines) — Core "AgentToolATO" implementation
  (tool execution, caching, git auto-commits).
- **traj_processor.py** (162 lines) — Processes the trajectory log
  (the JSON you accessed via the API). Handles base64 encoding/decoding of
  long string args like `--file-text` and `--old-str`.
- **bash_tools.py** (630 lines) — bash execution backend.
- **browser_use_runner.py** (408 lines) — Playwright browser automation
  (used by `screenshot_tool` and testing agents).
- **screenshot_tools.py** (149 lines) — Screenshot capture using Playwright.
- **descriptions.py** (414 lines) — The descriptions/schemas shown to the LLM
  for each tool (what Claude actually "sees" about each tool).
- **monitor.py** (111 lines) — The `e1_monitor` heartbeat process that
  pings demobackend every 5 minutes.

### 02_tool_outputs/
Every tool call from this session is cached on disk here.
Each file is named `<tool>-<toolu_xxx>.output` where `toolu_xxx` is the
EXACT tool_use_id Anthropic assigned in the API response.

These ARE the raw observations that get fed back to the LLM next turn.
This is the closest thing to "what's in the LLM's context" you can see
from inside the container.

### 03_logs/
- **e1_agent.log** — every tool call attempt logged with timestamp,
  cache hits/misses, and auto-commit IDs. The auto-commit IDs match
  git commits in `/app/.git`.
- **monitor.log** — heartbeats sent to demobackend.emergentagent.com.

## What is NOT in this container
- The agent's own system prompt — lives on demobackend.
- The full LLM conversation history — lives on demobackend.
- The Anthropic API key / LLM credentials — only on demobackend.
- The LLM's response text BEFORE tool-call parsing — never returned here.

## How to read the trajectory log (the gold)
The JSON you pasted earlier comes from demobackend's API. To find the
endpoint, open the Emergent web UI, hit F12 → Network tab → filter for
"demobackend.emergentagent.com". The trajectory endpoint returns:
- prompt_tokens, completion_tokens, cache_read, cache_creation per turn
- full_model_name (in this session: claude-opus-4-7)
- value_in_usd, acc_cost
- the agent's `thought` field (what was generated as chat text)
- the `action` field (what tool was called)
- the `observation` field (tool output it received)

That's the ground truth. Everything in this folder is its container-side
counterpart.
