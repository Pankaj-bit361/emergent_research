import asyncio
import sys
import io
from playwright.async_api import async_playwright
import argparse
from datetime import datetime
import os
import json
from pathlib import Path
import tempfile
import base64
import re
from .config import AgentConfig

# Compiled patterns for filtering noisy browser console logs
# - Translation fallback messages: Browser extension/i18n related logs
# - PostHog analytics: Third-party analytics service logs
SKIP_LOGS_PATTERNS = [
    re.compile(r'Using fallback translation for', re.IGNORECASE),
    re.compile(r'us-assets\.i\.posthog\.com', re.IGNORECASE),
    # Add more patterns as needed
]

# Match Python byte-literal strings (e.g., b"\xff\xd8...") so we can strip
# embedded binary data from captured stdout/stderr.
BYTE_LITERAL_PATTERN = re.compile(r"b(['\"])(?:\\.|(?!\1).)*\1")


def _sanitize_script_output(text: str) -> str:
    """Remove binary data from script output and keep it readable."""

    if not text:
        return text

    sanitized = BYTE_LITERAL_PATTERN.sub("[binary data omitted]", text)

    # Guard against extremely long log lines that can bloat tool output
    max_length = 40000
    if len(sanitized) > max_length:
        first_half = max_length // 2
        second_half = max_length - first_half
        return (
            sanitized[:first_half]
            + "... [output truncated] ..."
            + sanitized[-second_half:]
        )

    return sanitized

async def execute_playwright_script(script: str, url: str = None, output_dir: str = ".screenshots", capture_logs: bool = True, collect_print_logs: bool = False, mcp_flow: bool = False):
    """
    Executes a Playwright script and captures outputs.

    Args:
        script: Playwright script to execute
        url: URL to navigate to
        output_dir: Directory for screenshots
        capture_logs: Whether to capture browser console logs
        collect_print_logs: Whether to collect print statements in the result
    """
    # Create output directory
    config = AgentConfig.from_env()
    script_path = None
    browser = None
    test_script = None
    print_logs = []  # Collect print logs if requested

    def log_print(message):
        """Helper to print and optionally collect logs"""
        print(message)
        if collect_print_logs:
            print_logs.append(str(message))

    automation_output_dir = Path(config.emergent_base_path) / 'automation_output'
    screenshot_dir = Path(config.emergent_base_path) / output_dir

    os.makedirs(screenshot_dir, exist_ok=True)
    os.makedirs(automation_output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(automation_output_dir) / timestamp
    run_dir.mkdir(exist_ok=True)

    result = {
        "status": "success",
        "data": {
            "screenshots": [],
            "console_logs": [],
            "error": None,
            "output": None,
            "print_logs": []  # Will contain collected print logs
        }
    }

    try:
        if not url:
            url = get_frontend_url()
        log_print(f"\nFrontend URL: {url}")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()

            # Store console logs if requested
            console_logs = []
            if mcp_flow or capture_logs:
                def log_filter(msg):
                    # Only keep error, warning and custom logs, skip info logs
                    if msg.type == "info":
                        return

                    # Check message text against all patterns
                    if any(pattern.search(msg.text) for pattern in SKIP_LOGS_PATTERNS):
                        return

                    # Get location information (file, line, column)
                    location = msg.location
                    location_info = ""
                    if location and location.get("url"):
                        location_url = location.get('url')
                        # Check location URL against all patterns
                        if any(pattern.search(location_url) for pattern in SKIP_LOGS_PATTERNS):
                            return
                        location_info = f" at {location_url}:{location.get('lineNumber', 0)}:{location.get('columnNumber', 0)}"

                    # Format and store the log message with location
                    log_entry = f"{msg.type}: {msg.text}{location_info}"
                    console_logs.append(log_entry)

                    # Print to console immediately for real-time debugging
                    if not mcp_flow:
                        log_print(f"BROWSER CONSOLE: {log_entry}")

                page.on("console", log_filter)
                # Add page error handler to capture uncaught exceptions
                page.on("pageerror", lambda err: console_logs.append(f"PAGE ERROR: {err}"))

                # Add request failed handler for network issues
                def handle_request_failed(request):
                    failure = request.failure
                    error_text = ''
                    if isinstance(failure, dict):
                        error_text = failure.get('errorText', '')
                    elif isinstance(failure, str):
                        error_text = failure
                    console_logs.append(f"REQUEST FAILED: {request.url} - {error_text}")
                page.on("requestfailed", handle_request_failed)

            try:
                # Navigate to URL first
                # await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.set_viewport_size({"width": 1920, "height": 1080})

                await wait_for_page_load(page, url, log_func=log_print)

                # Decode script if base64 encoded
                if script.startswith('base64:'):
                    script = base64.b64decode(script[7:]).decode('utf-8')

                # Modify screenshot paths to use the run directory
                script = modify_screenshot_paths(script, str(run_dir))
                script = modify_script(script)
                # Add proper indentation to the script
                indented_script = ""
                for line in script.split('\n'):
                    if line.strip():
                        indented_script += "    " + line + "\n"
                    else:
                        indented_script += "\n"

                # Create test script with proper indentation.
                # `page_url` is injected so model-written scripts that reference
                # the tool's page_url parameter resolve.
                test_script = f"""async def run_test(page, output_dir, page_url):
{indented_script}"""


                # Save script to temp file for execution
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(test_script)
                    script_path = f.name

                # Import and execute the script
                import importlib.util
                spec = importlib.util.spec_from_file_location("dynamic_script", script_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Run the test
                if collect_print_logs:
                    # Capture stdout and stderr from user script for MCP flow
                    captured_stdout = io.StringIO()
                    captured_stderr = io.StringIO()
                    original_stdout = sys.stdout
                    original_stderr = sys.stderr
                    try:
                        sys.stdout = captured_stdout
                        sys.stderr = captured_stderr
                        output = await module.run_test(page, str(run_dir), url)
                    finally:
                        sys.stdout = original_stdout
                        sys.stderr = original_stderr
                        # Re-print captured output to maintain stdout/stderr behavior
                        script_stdout = _sanitize_script_output(captured_stdout.getvalue())
                        script_stderr = _sanitize_script_output(captured_stderr.getvalue())

                        if script_stdout:
                            print(script_stdout, end='')  # Re-print stdout unchanged for bash compatibility
                            # Collect stdout in print_logs
                            for line in script_stdout.splitlines():
                                print_logs.append(line)

                        if script_stderr:
                            print(script_stderr, end='', file=sys.stderr)  # Re-print stderr unchanged
                            # Collect stderr in print_logs with prefix
                            for line in script_stderr.splitlines():
                                print_logs.append(f"STDERR: {line}")
                else:
                    # No capture - normal execution for bash path
                    output = await module.run_test(page, str(run_dir), url)

                if output is not None:
                    result["data"]["output"] = output

                # Take a screenshot if none were taken
                screenshot_files = []
                for ext in ['.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG']:
                    screenshot_files.extend(list(run_dir.glob(f'*{ext}')))
                if not screenshot_files:
                    final_screenshot = run_dir / f"final_{timestamp}.jpeg"
                    await page.screenshot(
                        path=str(final_screenshot),
                        full_page=False,
                        type="jpeg",
                        quality = 50
                    )
                    result["data"]["screenshots"].append(str(final_screenshot))
                else:
                    result["data"]["screenshots"].extend(str(f) for f in screenshot_files)

            except Exception as e:
                result["status"] = "error"
                result["data"]["error"] = f"Script error: {str(e)}"
                error_screenshot = run_dir / f"error_{timestamp}.jpeg"
                await page.screenshot(
                        path=str(error_screenshot),
                        full_page=False,
                        type="jpeg",
                        quality = 40
                    )
                result["data"]["screenshots"].append(str(error_screenshot))

            finally:
                # Save the test script if it was created
                if test_script:
                    try:
                        test_script_path = run_dir / "test_script.py"
                        with open(test_script_path, "w") as f:
                            f.write(test_script)
                    except Exception as write_error:
                        log_print(f"Failed to write test script: {str(write_error)}")

                # Clean up temporary script file
                if script_path and os.path.exists(script_path):
                    try:
                        os.unlink(script_path)
                    except Exception as cleanup_error:
                        log_print(f"Failed to cleanup script: {str(cleanup_error)}")

                # Save console logs if captured
                if (mcp_flow or capture_logs) and console_logs:
                    try:
                        log_path = run_dir / f"console_{timestamp}.log"
                        with open(log_path, "w", encoding="utf-8") as f:
                            log_content = "\n".join(console_logs)
                            f.write(log_content)
                            if not mcp_flow:
                                log_print("\nConsole Logs:")
                                log_print("-------------")
                                log_print(log_content)
                                log_print("-------------")
                        result["data"]["console_logs"].append(str(log_path))
                    except Exception as log_error:
                        log_print(f"Failed to save console logs: {str(log_error)}")

    except Exception as e:
        result["status"] = "error"
        result["data"]["error"] = f"Setup error: {str(e)}"

    finally:
        try:
            # Copy images from automation_output to .screenshots
            if run_dir and run_dir.exists():
                copy_images_to_screenshots(run_dir, screenshot_dir, log_func=log_print)
        except Exception as copy_error:
            log_print(f"Error during image copy: {str(copy_error)}")
        if browser:
            await browser.close()
        log_print("Analyze the results and take appropriate action.")

        # Add collected print logs to result
        if collect_print_logs:
            result["data"]["print_logs"] = print_logs

    return result

def get_frontend_url(file_path='/root/port_mapping.json'):
    """
    Read the frontend URL first from JSON port mapping file, then from .env file.

    Args:
        file_path (str): Path to the port mapping file (defaults to /root/port_mapping.json)

    Returns:
        str: Frontend URL

    Raises:
        ValueError: If frontend URL cannot be determined from either source
    """
    # First try: Check port mapping file
    try:
        with open(file_path, 'r') as file:
            port_data = json.load(file)

            if 'services' in port_data and 'frontend' in port_data['services']:
                port = int(port_data['services']['frontend'])
                url = f"http://localhost:{port}"
                return url
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    # Second try: Check .env file for REACT_APP_BACKEND_URL
    env_file_path = '/app/frontend/.env'
    try:
        with open(env_file_path, 'r') as env_file:
            for line in env_file:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    # Extract URL and ensure proper format
                    url = line.split('=', 1)[1].strip().strip('"\'')
                    if not url.startswith('http://') and not url.startswith('https://'):
                        url = f"http://{url}"
                    return url
    except FileNotFoundError:
        pass

    print(f"\nCould not determine frontend URL from port mapping or .env file. Using default: http://localhost:3000")
    return f"http://localhost:3000"

def modify_screenshot_paths(script: str, output_path: str) -> str:
    """
    Modifies all screenshot paths in a Playwright script to use the provided output path.
    """
    output_dir = Path(output_path)

    patterns = [
        # Pattern 1: Regular quoted strings with parameters
        r'await page\.screenshot\((.*?)path=(["\'])(.*?)(["\'])(.*?)\)',
        # Pattern 2: f-strings with variables
        r'await page\.screenshot\((.*?)path=f[\'"](.*?)[\'"](.*?)\)'
    ]

    def replace_regular_path(match):
        """Handle regular quoted strings"""
        prefix = match.group(1)  # parameters before path
        quote = match.group(2)   # quote type
        old_path = match.group(3)  # original path
        suffix = match.group(5)  # parameters after path

        filename = Path(old_path).name
        new_path = str(output_dir / filename)

        # Reconstruct the command preserving all parameters
        full_cmd = f'await page.screenshot({prefix}path={quote}{new_path}{quote}{suffix})'
        return modify_screenshot_options(full_cmd)

    def replace_fstring_path(match):
        """Handle f-strings with variables"""
        prefix = match.group(1)
        old_path = match.group(2)
        suffix = match.group(3)

        if '{' in old_path:
            filename = Path(old_path).name
        else:
            filename = Path(old_path).name
        new_path = str(output_dir / filename)

        full_cmd = f'await page.screenshot({prefix}path=f"{new_path}"{suffix})'
        return modify_screenshot_options(full_cmd)

    modified_script = script
    modified_script = re.sub(patterns[0], replace_regular_path, modified_script)
    modified_script = re.sub(patterns[1], replace_fstring_path, modified_script)

    return modified_script

def test_script_modification():
    """Test various screenshot path patterns"""
    test_cases = [
        # Test case 1: Regular quoted string
        '''await page.screenshot(path="automation_output/initial_state.png")''',

        # Test case 2: f-string with variable
        '''await page.screenshot(path=f"move_{move}.png")''',

        # Test case 3: f-string with multiple variables
        '''await page.screenshot(path=f"test_{name}_{timestamp}.png")''',

        # Test case 4: Regular string with single quotes
        '''await page.screenshot(path='final_state.png')'''
    ]

    new_path = "/tmp/screenshots"
    print("\nTesting screenshot path modifications:")

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest case {i}:")
        print(f"Input:  {test_case}")
        modified = modify_screenshot_paths(test_case, new_path)
        print(f"Output: {modified}")

def copy_images_to_screenshots(run_dir: Path, screenshot_dir: Path, log_func=print):
    """
    Copy all images from automation_output timestamp folder to screenshots directory.

    Args:
        run_dir: Source directory containing images
        screenshot_dir: Destination directory for screenshots
        log_func: Function to use for logging (defaults to print)
    """
    import shutil

    try:
        # log_func(f"\nScanning for images in: {run_dir}")
        # Get all image files with different extensions and casings
        image_files = []
        for ext in ['.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG']:
            image_files.extend(list(run_dir.glob(f'*{ext}')))

        if not image_files:
            return

        log_func(f"Found {len(image_files)} images")

        for src_file in image_files:
            dest_file = screenshot_dir / src_file.name

            # Handle duplicate filenames
            counter = 1
            while dest_file.exists():
                name = src_file.stem
                suffix = src_file.suffix
                dest_file = screenshot_dir / f"{name}_{counter}{suffix}"
                counter += 1
            shutil.copy2(src_file, dest_file)
        # log_func(f"\nSuccessfully copied {len(image_files)} images to {screenshot_dir}")

    except Exception as e:
        log_func(f"Error during copy: {str(e)}")
        import traceback
        log_func(traceback.format_exc())

async def wait_for_page_load(page, url: str, max_retries: int = 3, log_func=print):
    """
    Robust page loading with two phases:

      Phase 1 (pre-poll, up to 60s): poll the URL until the server responds.
        Handles the cold-start race where the dev server (e.g. Expo Metro)
        hasn't bound its port yet — Playwright's page.goto fails fast on
        ERR_CONNECTION_REFUSED regardless of timeout, so we have to wait at
        the HTTP layer first.

      Phase 2 (navigation, escalating timeouts 10s/20s/40s): try page.goto
        with progressively longer timeouts so a slow bundle gets a second
        and third chance without blowing up the latency on the happy path.

    Args:
        page: Playwright page object
        url: URL to navigate to
        max_retries: Maximum number of retry attempts for Phase 2
        log_func: Function to use for logging (defaults to print)
    """
    # Phase 1: poll until server responds (handles ERR_CONNECTION_REFUSED window)
    poll_deadline = asyncio.get_event_loop().time() + 30
    server_bound = False
    while asyncio.get_event_loop().time() < poll_deadline:
        try:
            resp = await page.request.get(url, timeout=3000)
            if resp.status:
                server_bound = True
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    if not server_bound:
        log_func("Server didn't bind within 30s — proceeding with navigation anyway")

    # Phase 2: navigation with escalating timeouts
    timeouts_ms = [10000, 20000, 40000]
    for attempt in range(max_retries):
        timeout_ms = timeouts_ms[min(attempt, len(timeouts_ms) - 1)]
        try:
            log_func(f"Navigation attempt {attempt + 1}/{max_retries} (timeout={timeout_ms}ms)")

            # First try with load event
            try:
                await page.goto(url, wait_until="load", timeout=timeout_ms)
                # log_func("Page loaded with 'load' event")
                return True
            except Exception as load_error:
                log_func(f"Load event failed: {str(load_error)}")

            # If load fails, try with domcontentloaded
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # log_func("Page loaded with 'domcontentloaded' event")

                # Wait for network to be idle, but don't fail if it times out
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    log_func("Network didn't reach idle state, but page is loaded")

                return True
            except Exception as dom_error:
                log_func(f"DOM load failed: {str(dom_error)}")

            if attempt < max_retries - 1:
                # log_func("Waiting before retry...")
                await asyncio.sleep(2)  # Wait before retry

        except Exception as e:
            log_func(f"Navigation error: {str(e)}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2)  # Wait before retry

    return False

def modify_screenshot_options(screenshot_command: str) -> str:
    """
    Ensures all screenshots are JPEG format with quality=40
    """
    match = re.match(r'await page\.screenshot\((.*)\)', screenshot_command)
    if not match:
        return screenshot_command

    params_str = match.group(1)
    params = {}

    # Parse existing parameters
    for param in re.findall(r'([^,=]+)=([^,]+)(?:,|$)', params_str):
        key = param[0].strip()
        value = param[1].strip()
        params[key] = value

    # Ensure path ends with .jpeg
    if 'path' in params:
        path_value = params['path']
        if path_value.startswith('f'):
            path_pattern = r'(f["\'].*?)(\.(?:png|jpg|jpeg|PNG|JPG|JPEG))?(["\'])'
            path_value = re.sub(path_pattern, r'\1.jpeg\3', path_value)
        else:
            path_pattern = r'(["\'].*?)(\.(?:png|jpg|jpeg|PNG|JPG|JPEG))?(["\'])'
            path_value = re.sub(path_pattern, r'\1.jpeg\3', path_value)
        params['path'] = path_value

    # Set type and quality
    params['type'] = '"jpeg"'
    params['quality'] = '40'

    # Reconstruct with ordered parameters
    ordered_params = []
    for key in ['path', 'type', 'quality']:
        if key in params:
            ordered_params.append(f'{key}={params[key]}')

    # Add remaining parameters
    for key, value in params.items():
        if key not in ['path', 'type', 'quality']:
            ordered_params.append(f'{key}={value}')

    return f'await page.screenshot({", ".join(ordered_params)})'

def modify_viewport_size(match, max_pixel):
    """Modify viewport size to cap height at max_pixel pixels"""
    viewport_str = match.group(1)
    try:
        # Parse the viewport dictionary
        viewport_dict = eval(viewport_str)
        if 'height' in viewport_dict and viewport_dict['height'] > max_pixel:
            viewport_dict['height'] = max_pixel
            return f'await page.set_viewport_size({viewport_dict})'
    except:
        # If parsing fails, return original
        return match.group(0)
    return match.group(0)

def modify_script(script: str) -> str:
    """
    Modifies all screenshot commands in a Playwright script to set full_page=False.
    Also modifies viewport size settings to ensure height doesn't exceed:
    7000 pixels for single screenshot
    1920 pixels for multiple screenshots

    This function:
    1. Finds all screenshot commands that have full_page=True
    2. Replaces them with full_page=False
    3. For screenshot commands without a full_page parameter, adds full_page=False
    """
    # Pattern for finding screenshot commands with full_page=True
    pattern_true = r'await page\.screenshot\((.*?)full_page=True(.*?)\)'

    # Pattern for finding screenshot commands without a full_page parameter
    pattern_missing = r'await page\.screenshot\(([^)]*?)\)'

    # Pattern for finding viewport size settings
    pattern_viewport = r'await page\.set_viewport_size\(({.*?})\)'

    # Count screenshot commands
    screenshot_pattern = r'await page\.screenshot\('
    screenshot_count = len(re.findall(screenshot_pattern, script))
    max_pixel = 1920 if screenshot_count > 1 else 7000

    def replace_full_page_true(match):
        """Replace full_page=True with full_page=False"""
        prefix = match.group(1)
        suffix = match.group(2)
        return f'await page.screenshot({prefix}full_page=False{suffix})'

    def add_full_page_false(match):
        """Add full_page=False if parameter is missing"""
        params = match.group(1)

        # Skip if full_page is already specified
        if 'full_page=' in params:
            return match.group(0)

        # Add comma if there are already parameters
        if params.strip():
            if params.strip().endswith(','):
                new_params = f"{params} full_page=False"
            else:
                new_params = f"{params}, full_page=False"
        else:
            new_params = "full_page=False"

        return f'await page.screenshot({new_params})'

    # First replace full_page=True with full_page=False
    modified_script = re.sub(pattern_true, replace_full_page_true, script)

    # Then add full_page=False where it's missing
    modified_script = re.sub(pattern_missing, add_full_page_false, modified_script)
    # Finally modify viewport size settings, passing max_pixel
    modified_script = re.sub(
        pattern_viewport,
        lambda m: modify_viewport_size(m, max_pixel),
        modified_script
    )
    return modified_script

def test_screenshot_options_modification():
    test_cases = [
        # Previous test cases...

        # Test case specifically for the failing scenario
        (
            'await page.screenshot(path="adhd_app.jpg", full_page=False, quality=40)',
            'await page.screenshot(path="adhd_app.jpeg", type="jpeg", quality=40, full_page=False)'
        ),
        # Additional edge cases
        (
            'await page.screenshot(path="test.jpg", quality=40)',
            'await page.screenshot(path="test.jpeg", type="jpeg", quality=40)'
        ),
        (
            'await page.screenshot(path="test.png", quality=40)',
            'await page.screenshot(path="test.jpeg", type="jpeg", quality=40)'
        )
    ]

    print("\nTesting screenshot options modifications:")
    for i, (input_cmd, expected_output) in enumerate(test_cases, 1):
        print(f"\nTest case {i}:")
        print(f"Input:    {input_cmd}")
        result = modify_screenshot_options(input_cmd)
        print(f"Output:   {result}")
        print(f"Expected: {expected_output}")
        assert result == expected_output, f"Test case {i} failed"

def main():

    # Run test
    # test_script_modification()
    # test_screenshot_options_modification()

    parser = argparse.ArgumentParser(description="Execute Playwright automation script")
    parser.add_argument("--script", required=True, help="Playwright script to execute (plain text or base64 encoded with 'base64:' prefix)")
    # parser.add_argument("url", help="URL to automate")
    parser.add_argument("--url", help="URL to automate")  # Added URL argument
    parser.add_argument("--output_dir", "-o", default=".screenshots",
                        help="Output directory for screenshots and logs")
    parser.add_argument("--capture-logs", action="store_true", help="Capture console logs")

    args = parser.parse_args()

    result = asyncio.run(execute_playwright_script(
        args.script,
        args.url,
        args.output_dir,
        args.capture_logs
    ))

    print(json.dumps(result))

if __name__ == "__main__":
    main()
