# Emergent Agent — Complete Architecture Summary

Everything we discovered, condensed into one reference.

## 1. Where things live

```
demobackend.emergentagent.com         YOUR CONTAINER
├─ System prompt                      ├─ /app/                (your project)
├─ Conversation history               ├─ /opt/plugins-venv/   (agent runtime)
├─ LLM proxy                          ├─ /root/.emergent/     (tool outputs + screenshots)
└─ Anthropic API (Claude Opus 4.7)    ├─ /var/log/e1_agent.log
                                      └─ /var/log/monitor.log
```

## 2. The model

| Property | Value |
|---|---|
| **Provider** | Anthropic |
| **Model** | `claude-opus-4-7` |
| **Expertise type** | `full_stack_app_builder_cloud_v8_opus_4_7` |
| **Avg cost per turn (this session)** | ~$0.50 USD |
| **Context efficiency** | 99% cache hit rate via prompt caching |

## 3. The hard limits (extracted from source)

| Limit | Value | File |
|---|---|---|
| Max tool output to LLM | **80,000 chars** (~20k tokens) | mcp_tools.py:32 |
| Max bash output | 40,000 chars | bash_tools.py:367 |
| Max stdout cap | 38,000 bytes | bash_tools.py:34 |
| Max stderr cap | 2,000 bytes | bash_tools.py:35 |
| Max view_file lines | 2,000 lines | mcp_tools.py:642 |
| Max view_file chars in output | 64,000 chars | mcp_tools.py docstring |
| Max URL fetch | 5 MB | mcp_tools.py:142 |
| Max concurrent bash processes | 16 | bash_tools.py:38 |
| Tool call hard timeout | 22 minutes | config.py |
| LLM proxy timeout | 9 minutes | config.py |
| Image max edge | 1,568 px | mcp_tools.py:122 |
| Truncation strategy | first-half + last-half (middle-out) | mcp_tools.py:183 |

## 4. The 20 tools available

| # | Tool | What it does |
|---|---|---|
| 1 | `check_pod_resources` | CPU/memory/storage stats |
| 2 | `view_file` | Read a file (max 2000 lines) |
| 3 | `view_bulk` | Read multiple files at once |
| 4 | `read` | Generic read |
| 5 | `create_file` | Write a new file (or overwrite) |
| 6 | `apply_patch` | Apply a unified diff |
| 7 | `apply_patch_freeform` | Apply a freeform patch |
| 8 | `search_replace` | Single string replace in a file |
| 9 | `multi_search_replace` | Multiple replaces in one call |
| 10 | `insert_text` | Insert text at a specific line |
| 11 | `lint_python` | Python linting via ruff |
| 12 | `lint_javascript` | JS/TS linting via eslint |
| 13 | `execute_bash` | Run shell commands |
| 14 | `todo_write` | Manage TODO list |
| 15 | `browser_automation` | Browser test automation |
| 16 | `screenshot_tool` | Playwright screenshot |
| 17 | `run_ts_playwright` | Execute TS Playwright scripts |
| 18 | `run_browser_use` | LLM-driven browser agent |
| 19 | `bulk_file_writer` | Write many files in one call |
| 20 | `glob_files` | Find files by glob pattern |

(Full schemas in `TOOLS_REFERENCE.md`.)

## 5. How a single turn actually works

```
1. User types message in Emergent UI
2. demobackend constructs a prompt:
   [system prompt] + [all prior messages] + [user's new message]
3. demobackend sends prompt to LLM proxy
4. LLM proxy → Anthropic API → Claude Opus 4.7
5. Claude generates: chat text + tool call(s)
6. demobackend sends tool calls to YOUR CONTAINER :8010
7. plugins.tools.agent.server runs the tool
   - Writes output to /root/.emergent/tool_outputs/<toolu_xxx>.output
   - Logs to /var/log/e1_agent.log
   - Auto-commits any file changes to git
8. Tool output returned to demobackend
9. demobackend appends [tool result] to conversation
10. Goes back to step 3 (if Claude wants more tool calls)
11. When Claude generates a final text-only response, it's returned to user
12. Trajectory entry persisted to demobackend's DB (the JSON you accessed)
```

## 6. What you (the user) can access from outside

| Resource | How |
|---|---|
| Container files | code-server / SSH / this chat |
| Tool outputs cache | `/root/.emergent/tool_outputs/` |
| Tool call log | `/var/log/e1_agent.log` |
| Auto-commit history | `cd /app && git log` |
| Trajectory log JSON | demobackend API (you found it) |
| Live screenshots | `/root/.emergent/.screenshots/` |
| Platform agent source | `/opt/plugins-venv/lib/python3.11/site-packages/plugins/tools/agent/` |

## 7. What is NEVER accessible from the container
- The agent's system prompt
- The complete LLM conversation transcript (only metadata is exposed via API)
- The Anthropic API key
- The raw LLM response text BEFORE tool-call parsing

## 8. Confirmed myths busted in this session

| Myth | Truth |
|---|---|
| "Output limit is 8k tokens" | Actual: 80,000 chars (~20k tokens) for tool output |
| "Context gets compacted/summarized" | False — full history sent via prompt cache every turn |
| "Agent's context is 30–40k tokens" | This session: ~144k tokens being sent each turn |
| "I'm Claude Sonnet 4.5" | Actual: Claude Opus 4.7 |
| "Files I wrote got removed from context" | False — they remain in cached prefix |

