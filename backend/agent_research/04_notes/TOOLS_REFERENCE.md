# Tool Reference — Emergent Agent (E1 / Opus 4.7)

Extracted from `mcp_tools.py` (3183 lines) — 20 tools.
All tool definitions live in `/opt/plugins-venv/lib/python3.11/site-packages/plugins/tools/agent/mcp_tools.py`.

---

## Quick index

- [`check_pod_resources`](#check-pod-resources) — line 334
- [`view_file`](#view-file) — line 703
- [`view_bulk`](#view-bulk) — line 803
- [`read`](#read) — line 954
- [`create_file`](#create-file) — line 1283
- [`apply_patch`](#apply-patch) — line 1358
- [`apply_patch_freeform`](#apply-patch-freeform) — line 1448
- [`search_replace`](#search-replace) — line 1519
- [`multi_search_replace`](#multi-search-replace) — line 1674
- [`insert_text`](#insert-text) — line 1891
- [`lint_python`](#lint-python) — line 1974
- [`lint_javascript`](#lint-javascript) — line 2048
- [`execute_bash`](#execute-bash) — line 2158
- [`todo_write`](#todo-write) — line 2335
- [`browser_automation`](#browser-automation) — line 2474
- [`screenshot_tool`](#screenshot-tool) — line 2506
- [`run_ts_playwright`](#run-ts-playwright) — line 2540
- [`run_browser_use`](#run-browser-use) — line 2634
- [`bulk_file_writer`](#bulk-file-writer) — line 2809
- [`glob_files`](#glob-files) — line 3029

---

## `check_pod_resources`

*Defined at `mcp_tools.py:334`*

Check current pod resource usage (memory, CPU, storage).

---

## `view_file`

*Defined at `mcp_tools.py:703`*

View file or directory contents. Maximum 2000 lines per request for files.
    * For files: Shows content with line numbers (like 'cat -n')
    * For directories: Lists non-hidden files and subdirectories up to 2 levels deep
    * For files exceeding 2000 lines, use the view_range parameter to paginate through content
    * view_range [start_line, end_line] is 1-indexed. Max range: 2000 lines.
    * Output exceeding 64000 characters will be truncated, marked with '<response clipped>'

**Parameters:**

| Name | Type |
|---|---|
| `path` | `Annotated[str` |
| `view_range` | `Annotated[Optional[List[int]]` |
| `ctx` | `Context` |

---

## `view_bulk`

*Defined at `mcp_tools.py:803`*

View multiple files or directories in sequence
    * Processes a list of file or directory paths
    * Reads up to 2000 lines starting from the beginning of the file
    * For files: Shows content with line numbers (like 'cat -n')
    * For directories: Lists non-hidden files and subdirectories up to 2 levels deep
    * Continues processing even if some paths fail

**Parameters:**

| Name | Type |
|---|---|
| `paths` | `Annotated[List[str]` |
| `ctx` | `Context` |

---

## `read`

*Defined at `mcp_tools.py:954`*

View file, directory, or URL contents with per-file offset and limit
    - Accepts either a single ViewRequest or a list of ViewRequests
    - Prefer to read multiple files in parallel with their relevant offset and limit.
    - Each ViewRequest contains: path (required), offset (default 0), limit (optional)
    - For files: Shows content with line numbers (like 'cat -n')
    - For image files (.png, .jpg, .jpeg, .gif, .bmp, .webp): Returns the image inline
    - For URLs (http:// or https://): Fetches the content from the web. Image URLs return inline images; text/HTML/JSON URLs return conten…

**Parameters:**

| Name | Type |
|---|---|
| `request` | `Annotated[Union[ViewRequest` |
| `ctx` | `Context` |

---

## `create_file`

*Defined at `mcp_tools.py:1283`*

Create a new file with specified content
- Do not escape special characters (e.g., '' should remain as '', not '\\n').
- Overwrite existing file only when the file changes are substantial
- MUST be used for parallel tool call

**Parameters:**

| Name | Type |
|---|---|
| `path` | `Annotated[str` |
| `file_text` | `Annotated[str` |
| `overwrite` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `apply_patch`

*Defined at `mcp_tools.py:1358`*

Apply apply_patch operations across one or more files (atomic).

**Parameters:**

| Name | Type |
|---|---|
| `operations` | `Annotated[` |
| `ctx` | `Context` |

---

## `apply_patch_freeform`

*Defined at `mcp_tools.py:1448`*

Apply a free-form patch string across one or more files (atomic).

**Parameters:**

| Name | Type |
|---|---|
| `patch` | `Annotated[str` |
| `ctx` | `Context` |

---

## `search_replace`

*Defined at `mcp_tools.py:1519`*

Search and replace exact string in file
    CRITICAL REQUIREMENTS:
    * You MUST view the file first to match indentation exactly
    * old_str must match EXACTLY (including all whitespace, tabs, spaces)
    * old_str must be unique in the file - include enough context
    * Do not escape special characters (e.g., '\n' should remain as '\n', not '\\n').
    * Preserves exact formatting and indentation of the file
    * Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
    * Use replace_all for replacing and renaming strings across the file.
       …

**Parameters:**

| Name | Type |
|---|---|
| `path` | `Annotated[str` |
| `old_str` | `Annotated[str` |
| `new_str` | `Annotated[str` |
| `replace_all` | `Annotated[bool` |
| `status` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `multi_search_replace`

*Defined at `mcp_tools.py:1674`*

Array of edit operations to perform sequentially on the file
        IMPORTANT: This must be an actual array of objects, not a JSON string.
        Example: [{"old_str": "old text", "new_str": "new text", "replace_all": false}]
        DO NOT pass as a JSON-encoded string - the array will be handled automatically.

**Parameters:**

| Name | Type |
|---|---|
| `path` | `Annotated[str` |
| `edits` | `Annotated[List[EditOperation]` |
| `IMPORTANT` | `This must be an actual array of objects` |
| `Example` | `[{"old_str": "old text"` |
| `status` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `insert_text`

*Defined at `mcp_tools.py:1891`*

Insert text at a specific line number in a file
    * Text is inserted AFTER the specified line number
    * Line numbers use 1-based indexing (first line is 1)
    * Use when you need to add content without replacing existing text
    * Good for adding imports, new functions, or comments

**Parameters:**

| Name | Type |
|---|---|
| `path` | `Annotated[str` |
| `new_str` | `Annotated[str` |
| `insert_line` | `Annotated[int` |
| `ctx` | `Context` |

---

## `lint_python`

*Defined at `mcp_tools.py:1974`*

Python code linting and static analysis.
- Run before calling the testing subagent
- Checks for syntax errors, undefined variables, unused imports, production bugs (e.g. serialization issues, route ordering), and style violations
- Supports single files, directories, and glob patterns
- Preferred to run in parallel

**Parameters:**

| Name | Type |
|---|---|
| `path_pattern` | `Annotated[str` |
| `exclude_patterns` | `Annotated[Optional[List[str]]` |
| `fix` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `lint_javascript`

*Defined at `mcp_tools.py:2048`*

JavaScript/TypeScript code linting and static analysis.
- Run before calling the testing subagent
- Checks for syntax errors, undefined variables, unused variables, import validation, and style violations
- Supports .js, .jsx, .ts, .tsx files and patterns
- Preferred to run in parallel

**Parameters:**

| Name | Type |
|---|---|
| `path_pattern` | `Annotated[str` |
| `exclude_patterns` | `Annotated[Optional[List[str]]` |
| `fix` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `execute_bash`

*Defined at `mcp_tools.py:2158`*

Execute bash commands with full shell features.
Supports both foreground and background execution.
Foreground execution has a timeout of 120 seconds. So use background execution for long running commands and check logs periodically
For background processes, append '&' to your command.
Use standard bash job control (jobs, fg, bg, kill, wait) for process management.

**Parameters:**

| Name | Type |
|---|---|
| `ctx` | `Context` |
| `command` | `Annotated[str` |
| `timeout` | `Annotated[int` |
| `cwd` | `Annotated[Optional[str]` |

---

## `todo_write`

*Defined at `mcp_tools.py:2335`*

List of TodoItem objects, each containing:
        - content: Brief description of the task
        - status: pending, in_progress, completed, or cancelled

**Parameters:**

| Name | Type |
|---|---|
| `todos` | `Annotated[List[TodoItem]` |
| `ctx` | `Context` |

---

## `browser_automation`

*Defined at `mcp_tools.py:2474`*

Execute browser automation with Playwright - wrapper for the implementation.

**Parameters:**

| Name | Type |
|---|---|
| `page_url` | `Annotated[str` |
| `script` | `Annotated[str` |
| `capture_logs` | `Annotated[bool` |
| `output_dir` | `Annotated[str` |
| `ctx` | `Context` |

---

## `screenshot_tool`

*Defined at `mcp_tools.py:2506`*

Execute screenshot commands using Playwright. Use this tool to take screenshots of the webpage while building.

**Parameters:**

| Name | Type |
|---|---|
| `page_url` | `Annotated[str` |
| `script` | `Annotated[str` |
| `capture_logs` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `run_ts_playwright`

*Defined at `mcp_tools.py:2540`*

Run a TypeScript Playwright spec and return test results.

**Parameters:**

| Name | Type |
|---|---|
| `spec_inline` | `Annotated[str` |
| `spec_path` | `Annotated[str` |
| `page_url` | `Annotated[str` |
| `capture_all_screenshots` | `Annotated[bool` |
| `output_dir` | `Annotated[str` |
| `timeout` | `Annotated[int` |
| `inline_screenshots` | `Annotated[bool` |
| `description` | `Annotated[Optional[str]` |
| `ctx` | `Context` |

---

## `run_browser_use`

*Defined at `mcp_tools.py:2634`*

Drive `browser-use` against `page_url` with a batch of test cases.

**Parameters:**

| Name | Type |
|---|---|
| `page_url` | `Annotated[str` |
| `test_cases` | `Annotated[List[str]` |
| `llm_api_key` | `Annotated[str` |
| `system_prompt` | `Annotated[Optional[str]` |
| `llm_base_url` | `Annotated[str` |
| `llm_model` | `Annotated[str` |
| `max_steps_per_test` | `Annotated[int` |
| `timeout_per_test` | `Annotated[int` |
| `headless` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `bulk_file_writer`

*Defined at `mcp_tools.py:2809`*

Write multiple files simultaneously for improved performance

**Parameters:**

| Name | Type |
|---|---|
| `files` | `Annotated[BulkFilesList` |
| `IMPORTANT` | `This must be an actual array of objects` |
| `status` | `Annotated[bool` |
| `capture_logs_frontend` | `Annotated[bool` |
| `capture_logs_backend` | `Annotated[bool` |
| `ctx` | `Context` |

---

## `glob_files`

*Defined at `mcp_tools.py:3029`*

Fast file pattern matching tool that works with any codebase size
    - Supports glob patterns like "**/*.js" or "src/**/*.ts"
    - Returns matching file paths
    - Respects .gitignore files by default
    - Use this tool when you need to find files by name patterns
    - When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead
    - You have the capability to call multiple tools in a single response. It is always better to speculatively perform multiple searches as a batch that are potentially useful.

**Parameters:**

| Name | Type |
|---|---|
| `pattern` | `Annotated[str` |
| `path` | `Annotated[Optional[str]` |
| `ctx` | `Context` |

---
