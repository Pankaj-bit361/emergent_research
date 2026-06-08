TODO_WRITE_DESCRIPTION = """
Use this tool to create and manage a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.
It also helps the user understand the progress of the task and overall progress of their requests.

#### When to Use This Tool
Use this tool proactively in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. After receiving new instructions - Immediately capture user requirements as todos
6. When you start working on a task - Mark it as in_progress BEFORE beginning work. Ideally you should only have one todo as in_progress at a time
7. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation

#### When NOT to Use This Tool

Skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no organizational benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

NOTE that you should not use this tool if there is only one trivial task to do. In this case you are better off just doing the task directly.

#### Examples of When to Use the Todo List

<example>
User: I want to add a dark mode toggle to the application settings. Make sure you run the tests and build when you're done!
Assistant: I'll help add a dark mode toggle to your application settings. Let me create a todo list to track this implementation.
*Creates todo list with the following items:*
1. Creating dark mode toggle component in Settings page
2. Adding dark mode state management (context/store)
3. Implementing CSS-in-JS styles for dark theme
4. Updating existing components to support theme switching
5. Running tests and build process, addressing any failures or errors that occur
*Begins working on the first task*

<reasoning>
The assistant used the todo list because:
1. Adding dark mode is a multi-step feature requiring UI, state management, and styling changes
2. The user explicitly requested tests and build be run afterward
3. The assistant inferred that tests and build need to pass by adding "Ensure tests and build succeed" as the final task
</reasoning>
</example>

<example>
User: Help me rename the function getCwd to getCurrentWorkingDirectory across my project
Assistant: Let me first search through your codebase to find all occurrences of 'getCwd'.
*Uses grep or search tools to locate all instances of getCwd in the codebase*
Assistant: I've found 15 instances of 'getCwd' across 8 different files. Let me create a todo list to track these changes.
*Creates todo list with specific items for each file that needs updating*

<reasoning>
The assistant used the todo list because:
1. First, the assistant searched to understand the scope of the task
2. Upon finding multiple occurrences across different files, it determined this was a complex task with multiple steps
3. The todo list helps ensure every instance is tracked and updated systematically
4. This approach prevents missing any occurrences and maintains code consistency
</reasoning>
</example>


<example>
User: I need to implement these features for my e-commerce site: user registration, product catalog, shopping cart, and checkout flow.
Assistant: I'll help implement these features. First, let's add all the features to the todo list.
*Creates a todo list breaking down each feature into specific tasks based on the project architecture*
Assistant: Let's start with user registration. This will involve creating database models, API endpoints, and frontend forms that integrate with your existing authentication system.

<reasoning>
The assistant used the todo list because:
1. The user provided multiple complex features to implement in a comma separated list
2. The todo list helps organize these large features into manageable tasks
3. This approach allows for tracking progress across the entire implementation
</reasoning>
</example>

<example>
User: Can you help optimize my React application? It's rendering slowly and has performance issues.</user>
Assistant: I'll help optimize your React application. First, let me examine your codebase to identify potential performance bottlenecks.
*Reviews component structure, render patterns, state management, and data fetching*
Assistant: After analyzing your codebase, I've identified several performance issues. Let me create a todo list to track our optimization efforts.
*Creates todo list with items like: 1) Implementing memoization for expensive calculations in ProductList, 2) Adding virtualization for long lists in Dashboard, 3) Optimizing image loading in Gallery component, 4) Fixing state update loops in ShoppingCart, 5) Reviewing bundle size and implementing code splitting*
Let's start by implementing memoization for the expensive calculations in your ProductList component.</assistant>

<reasoning>
The assistant used the todo list because:
1. First, the assistant examined the codebase to identify specific performance issues
2. Based on this analysis, it identified multiple optimization opportunities
3. Performance optimization is a non-trivial task requiring multiple steps
4. The todo list helps methodically track improvements across different components
5. This systematic approach ensures all performance bottlenecks are addressed
</reasoning>
</example>

#### Examples of When NOT to Use the Todo List

<example>
User: How do I print 'Hello World' in Python?
Assistant: In Python, you can print "Hello World" with this simple code:

python
print("Hello World")

This will output the text "Hello World" to the console when executed.</assistant>

<reasoning>
The assistant did not use the todo list because this is a single, trivial task that can be completed in one step. There's no need to track multiple tasks or steps for such a straightforward request.
</reasoning>
</example>

<example>
User: What does the git status command do?
Assistant: The git status command shows the current state of your working directory and staging area. It displays which changes have been staged, which haven't, and which files aren't being tracked by Git. This is a fundamental command for understanding the current state of your repository before making commits.

<reasoning>
The assistant did not use the todo list because this is an informational request with no actual coding task to complete. The user is simply asking for an explanation, not for the assistant to perform multiple steps or tasks.
</reasoning>
</example>

<example>
User: Can you add a comment to the calculateTotal function to explain what it does?
Assistant: Sure, let me add a comment to the calculateTotal function to explain what it does.
* Uses the Edit tool to add a comment to the calculateTotal function *

<reasoning>
The assistant did not use the todo list because this is a single, straightforward task confined to one location in the code. Adding a comment doesn't require tracking multiple steps or systematic organization.
</reasoning>
</example>

<example>
User: Run npm install for me and tell me what happens.
Assistant: I'll run the npm install command for you.

*Executes: npm install*

The command completed successfully. Here's the output:
[Output of npm install command]

All dependencies have been installed according to your package.json file.

<reasoning>
The assistant did not use the todo list because this is a single command execution with immediate results. There are no multiple steps to track or organize, making the todo list unnecessary for this straightforward task.
</reasoning>
</example>

#### Task States and Management

1. **Task States**: Use these states to track progress:
   - pending: Task not yet started
   - in_progress: Currently working on (limit to ONE task at a time)
   - completed: Task finished successfully
   - cancelled: Task cancelled

2. **Task Management**:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant from the list entirely

3. **Task Completion Requirements**:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
   - When blocked, create a new task describing what needs to be resolved
   - Never mark a task as completed if:
     - Tests are failing
     - Implementation is partial
     - You encountered unresolved errors
     - You couldn't find necessary files or dependencies
   - Do not mark comprehensive testing as completed without calling the testing subagent.

4. **Task Breakdown**:
   - Create specific, actionable items
   - Break complex tasks into smaller, manageable steps
   - Use clear, descriptive task names
"""


BROWSER_AUTOMATION_SCRIPT_DESCRIPTION = """
Complete Python Playwright script to execute. The script must only test the functionalities relevent to current tasks. It should only test UI elements which are present in the current task or app.
 This script will be run inside an async function with access to the page object. Always use Python Playwright syntax (snake_case) for script.
 Guideline for script generation:
 1. Use more specific selectors suitable for current code and task at hand.
 2. All interactive and key informational elements have `data-testid` attribute to facilitate robust automated testing. You must refer and use `data-testid` while writing playwright script wherever applicable
  - **Scope:** This applies to buttons, links, form inputs, menus, and any element that a user interacts with or that displays critical information (e.g., an error message, a user's balance, a confirmation text).
  - e.g., `data-testid="login-form-submit-button"`)
 3. Always use Python Playwright syntax (snake_case)
 4. Used .first when selecting multiple similar elements (like delete buttons)
 5. Add proper waits between actions
 6. Use more specific selectors for form elements
 7. Simplify the test flow to focus on core functionality
 8. Add clear state indicators with screenshots
 9. Add screenshot commands only when necessary and critical to check the functionality. NOT always.
 10. For screenshot commands, always set quality=40 and full_page=False. Always stick with the following screen size for testing: for Desktop: page.set_viewport_size({\"width\": 1920, \"height\": 1080}) and for Tab: page.set_viewport_size({\"width\": 768, \"height\": 1024}) and for Mobile: page.set_viewport_size({\"width\": 390, \"height\": 844}). This config is critical to minimise image size
 11. Added force=True to click actions to bypass modal overlay issues
 12. Used more specific selectors with exact=True
 13. Only includes actions (example: clicks, waits, validations)
 14. Only includes essential timeouts and waits.
 15. Only generate script which is relevant for the current task.
 16. Do not include any script which is not relevant or does not apply to current tasks.
 17. Always use try catch block in the script and always print test results in case success and failure at each step.
 18. IMPORTANT: When detecting error messages, ALWAYS use specific error selectors exactly as shown here: ```python
                # Get error messages using specific selectors
                error_text = await page.evaluate(\"\"\"() => {
                    const errorElements = Array.from(document.querySelectorAll('.error, [class*=\"error\"], [id*=\"error\"]'));
                    return errorElements.map(el => el.textContent).join(\", \");
                }\"\"\")
                if error_text:
                    print(f\"Found error message: {error_text}\")
                else:
                    print(\"No error messages found on the page\")
                ```
"""

BROWSER_AUTOMATION_TOOL_DESCRIPTION = """Complete Python Playwright script to execute. The script must only test the functionalities relevent to current tasks. It should only test UI elements which are present in the current task or app.
 This script will be run inside an async function with access to the page object. Always use Python Playwright syntax (snake_case) for script.
 Guideline for script generation:
 1. Use more specific selectors suitable for current code and task at hand.
 2. All interactive and key informational elements have `data-testid` attribute to facilitate robust automated testing. You must refer and use `data-testid` while writing playwright script wherever applicable
  - **Scope:** This applies to buttons, links, form inputs, menus, and any element that a user interacts with or that displays critical information (e.g., an error message, a user's balance, a confirmation text).
  - e.g., `data-testid=\"login-form-submit-button\"`)
 3. Always use Python Playwright syntax (snake_case)
 4. Used .first when selecting multiple similar elements (like delete buttons)
 5. Add proper waits between actions
 6. Use more specific selectors for form elements
 7. Simplify the test flow to focus on core functionality
 8. Add clear state indicators with screenshots
 9. Add screenshot commands only when necessary and critical to check the functionality. NOT always.
 10. For screenshot commands, always set quality=40 and full_page=False. Always stick with the following screen size for testing: for Desktop: page.set_viewport_size({\\\"width\\\": 1920, \\\"height\\\": 1080}) and for Tab: page.set_viewport_size({\\\"width\\\": 768, \\\"height\\\": 1024}) and for Mobile: page.set_viewport_size({\\\"width\\\": 390, \\\"height\\\": 844}). This config is critical to minimise image size
 11. CRITICAL: Always use force=True when clicking dropdown/select options inside modals to bypass overlay interception
 12. Used more specific selectors with exact=True
 13. When interacting with Select or Dropdown components inside modals/dialogs, add await page.wait_for_timeout(200) after opening the dropdown before clicking options to allow animations to settle
 14. Only includes actions (example: clicks, waits, validations)
 15. Only includes essential timeouts and waits.
 16. Only generate script which is relevant for the current task.
 17. Do not include any script which is not relevant or does not apply to current tasks.
 18. Always use try catch block in the script and always print test results in case success and failure at each step.
 19. IMPORTANT: When detecting error messages, ALWAYS use specific error selectors exactly as shown here: ```python
                # Get error messages using specific selectors
                error_text = await page.evaluate(\\\"\\\"\\\"() => {
                    const errorElements = Array.from(document.querySelectorAll('.error, [class*=\\\"error\\\"], [id*=\\\"error\\\"]'));
                    return errorElements.map(el => el.textContent).join(\\\", \\\");
                }\\\"\\\"\\\")
                if error_text:
                    print(f\\\"Found error message: {error_text}\\\")
                else:
                    print(\\\"No error messages found on the page\\\")"""

MULTI_SEARCH_REPLACE_DESCRIPTION = """
This is a tool for making multiple edits to a single file in one operation.
It is built on top of the search_replace tool and allows you to perform multiple find-and-replace operations efficiently. Prefer this tool over the search_replace tool when you need to make multiple edits to the same file.

Before using this tool:

1. Use the read file tools to understand the file's contents and context
2. Verify the directory path is correct

To make multiple file edits, provide the following:
1. path: The absolute path to the file to modify (must be absolute, not relative)
2. edits: An array of edit operations to perform, where each edit contains:
   - old_str: The text to replace (must match the file contents exactly, including all whitespace and indentation)
   - new_str: The edited text to replace the old_str
   - replace_all: Replace all occurrences of old_str. This parameter is optional and defaults to false.

IMPORTANT:
- All edits are applied in sequence, in the order they are provided
- Each edit operates on the result of the previous edit
- All edits must be valid for the operation to succeed - if any edit fails, none will be applied
- This tool is ideal when you need to make several simple changes to the same file
- **ALWAYS** prefer this tool over the single search_replace tool when making multiple changes to the same file
- Do not escape special characters (e.g., '\n' should remain as '\n', not '\\n').

CRITICAL REQUIREMENTS:
1. All edits follow the same requirements as the single search_replace tool
2. The edits are atomic - either all succeed or none are applied
3. **ALWAYS** plan your edits carefully to avoid conflicts between sequential operations

WARNING:
- The tool will fail if edits.old_str doesn't match the file contents exactly (including whitespace)
- The tool will fail if edits.old_str and edits.new_str are the same
- Since edits are applied in sequence, ensure that earlier edits don't affect the text that later edits are trying to find

When making edits:
- Ensure all edits result in idiomatic, correct code
- Do not leave the code in a broken state
- Always use absolute file paths (starting with /)
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- Use replace_all for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.
"""

RUN_TS_PLAYWRIGHT_DESCRIPTION = """Run a complete TypeScript Playwright test spec and return test results.

Use this for E2E testing with full specs — multiple `test()` blocks, assertions, `test.describe`, `test.beforeEach`, etc.

## Input — provide ONE of:

- spec_inline: Full spec source code as a string. Best for ad-hoc or generated tests.
- spec_path: Absolute path to an existing `.spec.ts` file on disk. Playwright runs from the spec's directory so relative imports and node_modules resolve correctly.

## Screenshots

Playwright auto-captures screenshots on failure (only-on-failure mode). The output includes screenshot paths like:
  `attachment #1: screenshot (image/png) — /root/.emergent/automation_output/.../test-results/...`

For explicit screenshots in your spec, use `await page.screenshot({ path: 'name.jpeg', quality: 20, fullPage: false })`.

Set `inline_screenshots: true` to get screenshots returned directly in the response as inline images — useful for visually verifying what the app looks like after tests run.

With `inline_screenshots: false` (default), use the `read` tool on the screenshot paths from the output to view them.

Set `capture_all_screenshots: true` if you need auto-captured screenshots on every test (pass and fail), not just failures.

## Spec writing rules

- Structure: `test.describe('Feature', () => { test('case', async ({ page }) => { ... }) })`
- Locators: `page.getByTestId(...)`, `page.getByRole(...)`, `page.getByText(...)`
- Assertions: `expect(locator).toBeVisible()`, `expect(locator).toHaveText(...)`
- Screenshots: `await page.screenshot({ path: 'name.jpeg', quality: 20, fullPage: false })`
- Navigation: `await page.goto('/')` — baseURL comes from `page_url` param
- camelCase only (TypeScript), NOT snake_case
- The config sets `screenshot: 'only-on-failure'` — Playwright auto-captures on failure. Use `capture_all_screenshots: true` to capture on pass too
- Viewport defaults to 1280x720. Override with `await page.setViewportSize(...)` if needed
- **data-testid**: All interactive and key informational elements have `data-testid` attribute to facilitate robust automated testing. You must refer and use `data-testid` while writing playwright script wherever applicable
  - Scope: This applies to buttons, links, form inputs, menus, and any element that a user interacts with or that displays critical information (e.g., an error message, a user's balance, a confirmation text).
  - Example: `data-testid="login-form-submit-button"`
"""

SCREENSHOT_SCRIPT_DESCRIPTION = """
Complete Python Playwright script to take screenshot of the webpage.
This script will be run inside an async function with access to the page object. Always use Python Playwright syntax (snake_case) for script.
    Guideline for script generation:
    2. Always use Python Playwright syntax (snake_case)
    4. Add proper waits between actions
    5. Use more specific selectors for form elements
    7. Add clear state indicators with screenshots
    9. For screenshot commands, always set quality=20 and full_page=False. Always stick with the following screen size for testing: page.set_viewport_size({"width": 1920, "height": 800}). This config is critical to minimise image size
    10. Added force=True to click actions to bypass modal overlay issues
    11. Used more specific selectors with exact=True
    12. Only includes actions (example: clicks, waits, validations)
    13. Only includes essential timeouts and waits.
    14. Only generate script which is relevant for the current task.
    15. Do not include any script which is not relevant or does not apply to current tasks.
    16. Always use try catch block in the script and always print test results in case success and failure at each step.
"""

RUN_BROWSER_USE_DESCRIPTION = """Run an AI-driven browser agent (`browser-use`) against a target URL using
plain-English test cases. The agent opens the page in a local headless
Chromium, interprets each test case as natural-language instructions, drives
the browser (clicks, typing, navigation, assertions), and returns a
`pass` / `fail` verdict per test case.

#### When to use this tool
- You have user-facing test cases written as natural language (e.g. "Log in as
  user X and verify the dashboard shows their recent orders").
- The UI may change between runs and you want the agent to figure out
  selectors / flow instead of hard-coding them.
- You want quick end-to-end validation of a preview URL without writing a
  Playwright script.

#### When NOT to use this tool
- You already have a deterministic Playwright spec — use `run_ts_playwright`
  instead (faster, cheaper, reproducible).
- You need a single scripted interaction (capture console logs, take a
  screenshot, run a specific flow) — use `browser_automation` or
  `screenshot_tool`.
- You need cloud / remote browser attach (CDP URL) — not supported in v1.

#### LLM routing (IMPORTANT)
The caller MUST pass `llm_api_key`. The other two LLM fields have sane
defaults but can be overridden:
- `llm_api_key`: the bearer token the OpenAI-compat endpoint expects. When
  routing through Emergent's integration-proxy (the normal case), this is an
  Emergent API key (`sk-emergent-...`) — the proxy swaps it for the real
  provider key server-side, so no raw Gemini/OpenAI/Anthropic key ever
  touches this process. The key MUST be issued for the same env the pod is
  running in — a dev key against a staging proxy will come back `401
  Invalid API key`.
- `llm_base_url`: OpenAI-compatible base URL ending at the version root
  (e.g. `.../v1`). Default is resolved at plugin-library import time from
  the pod's `INTEGRATION_PROXY_URL` / `integration_proxy_url` env var with
  `/llm/v1` auto-appended, so dev / staging / prod / wingman pods each
  route to their own integration-proxy without needing an explicit
  override. Falls back to the production endpoint when neither env var is
  set. Override explicitly when you want a non-integration-proxy endpoint
  (e.g. calling OpenAI directly with a raw key).
- `llm_model`: the LiteLLM model identifier (e.g.
  `gemini/gemini-3-flash-preview`, `openai/gpt-4o-mini`,
  `anthropic/claude-3-5-sonnet`). Defaults to `gemini/gemini-3-flash-preview`
  — the only Gemini model verified to accept the sampling params
  `browser-use` sends through the proxy. Override for other providers, or
  when the proxy's upstream Gemini key has been flagged as leaked (in
  which case Gemini returns HTTP 403 `PERMISSION_DENIED` on every call and
  you should switch to `openai/gpt-4o-mini` or similar).

#### Verdict format
Each test case is wrapped in a prompt that instructs the agent to finish with
a `<verdict>...</verdict>` tag containing JSON, e.g.
`<verdict>{"status": "pass", "details": "Login succeeded; dashboard loaded"}</verdict>`.
The tool parses that tag out of the final agent output and reports
`pass` / `fail` per test. Tests with no parseable verdict are reported as
`error`.

#### Parameters
- `page_url` (required): URL to test against.
- `test_cases` (required, non-empty list): one or more natural-language test
  case strings. Runs sequentially in a single browser session.
- `llm_api_key` (required): per-call secret. Not logged, not cached.
- `system_prompt` (optional): prepended to the task prompt for every test
  case. Use for persona, constraints, auth setup, etc.
- `llm_base_url`, `llm_model`: see "LLM routing" above.
- `max_steps_per_test` (default 30): agent step cap per test case.
- `timeout_per_test` (default 300s): wall-clock cap per test case.
- `headless` (default True): run Chromium headless.
"""
