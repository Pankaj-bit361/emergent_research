"""TypeScript Playwright test runner.

Runs .spec.ts files via `npx playwright test`, collects screenshots
and JSON reporter output, and returns a result dict compatible with
`qabot_script_handler.execute_playwright_script()`.
"""

import asyncio
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

from .config import AgentConfig
from .qabot_script_handler import copy_images_to_screenshots, get_frontend_url


async def execute_ts_playwright(
    spec_content: str = None,
    spec_file: str = None,
    base_url: str = None,
    output_dir: str = ".screenshots",
    capture_all_screenshots: bool = False,
    timeout: int = 300,
) -> dict:
    """Execute a TypeScript Playwright spec and return screenshots + results.

    Accepts either inline spec content or a path to an existing .spec.ts file.
    Writes a temporary playwright.config.ts, runs `npx playwright test`, parses
    the JSON reporter output, and collects screenshots from `test-results/`.

    Returns the same dict shape as ``qabot_script_handler.execute_playwright_script``.
    """
    config = AgentConfig.from_env()
    automation_output_dir = Path(config.emergent_base_path) / "automation_output"
    screenshot_dir = Path(config.emergent_base_path) / output_dir

    os.makedirs(screenshot_dir, exist_ok=True)
    os.makedirs(automation_output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = automation_output_dir / timestamp
    run_dir.mkdir(exist_ok=True)

    result = {
        "status": "success",
        "data": {
            "screenshots": [],
            "console_logs": [],
            "error": None,
            "output": None,
            "print_logs": [],
        },
    }

    spec_path = None
    tmp_config_path = None
    tmp_spec_path = None

    try:
        # Resolve the base URL for the app under test
        if not base_url:
            base_url = get_frontend_url()
        print(f"Base URL for Playwright tests: {base_url}")

        # Determine spec file path
        if spec_file:
            spec_path = Path(spec_file)
            if not spec_path.exists():
                raise FileNotFoundError(f"Spec file not found: {spec_file}")
        elif spec_content:
            # Write inline content to a temp .spec.ts file
            tmp_spec = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".spec.ts",
                dir=str(run_dir),
                delete=False,
            )
            tmp_spec.write(spec_content)
            tmp_spec.close()
            tmp_spec_path = tmp_spec.name
            spec_path = Path(tmp_spec_path)
        else:
            raise ValueError("Either spec_content or spec_file must be provided")

        # JSON reporter output path
        json_results_path = run_dir / "results.json"

        # Playwright test-results directory (screenshots, traces, etc.)
        test_results_dir = run_dir / "test-results"

        # Write playwright config.
        # For spec_file: place config next to the spec so both resolve
        # @playwright/test from the same node_modules tree.
        # For spec_content: place in the timestamped run_dir.
        if spec_file:
            tmp_config_path = str(spec_path.parent / ".pw_runner.config.ts")
        else:
            tmp_config_path = str(run_dir / ".pw_runner.config.ts")
        test_dir = str(spec_path.parent) if spec_file else None
        # Per-test timeout: use 80% of overall timeout to leave room for setup/teardown
        per_test_timeout_ms = int(min(timeout * 0.8, 60) * 1000)
        pw_config = _build_playwright_config(
            base_url=base_url,
            output_dir=str(test_results_dir),
            json_output_file=str(json_results_path),
            capture_all_screenshots=capture_all_screenshots,
            test_dir=test_dir,
            per_test_timeout_ms=per_test_timeout_ms,
        )
        with open(tmp_config_path, "w") as f:
            f.write(pw_config)

        # Build the command.
        if spec_file:
            cwd = str(spec_path.parent)
            cmd = f"npx playwright test {spec_path.name} --config={tmp_config_path}"
        else:
            cwd = str(run_dir)
            cmd = f"npx playwright test {spec_path} --config={tmp_config_path}"
        print(f"Running: {cmd}  (cwd={cwd})")

        # Set env for Playwright browsers
        env = os.environ.copy()
        env["PLAYWRIGHT_FORCE_TTY"] = "0"
        env["FORCE_COLOR"] = "0"
        browsers_path = _resolve_browsers_path()
        if browsers_path:
            env["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

        # For inline specs (spec_content), ensure @playwright/test is
        # resolvable from automation_output via a symlink to the global
        # installation.  For spec_file runs the config lives next to the
        # spec so Node resolves from the same node_modules tree.
        if not spec_file:
            _ensure_playwright_test_module(automation_output_dir)

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        stdout_str = _ANSI_RE.sub("", stdout_bytes.decode("utf-8", errors="replace"))
        stderr_str = _ANSI_RE.sub("", stderr_bytes.decode("utf-8", errors="replace"))

        # Collect print logs from test runner output
        if stdout_str.strip():
            result["data"]["print_logs"].append(stdout_str.strip())
        if stderr_str.strip():
            result["data"]["print_logs"].append(f"[stderr] {stderr_str.strip()}")

        # Record path to JSON reporter output (agent can read if needed)
        if json_results_path.exists():
            result["data"]["json_report"] = str(json_results_path)

        # Determine success from exit code
        if proc.returncode != 0:
            result["status"] = "error"
            result["data"]["error"] = (
                f"Playwright tests failed (exit code {proc.returncode})"
            )

        # Collect screenshots from both locations, dedup by file content
        all_screenshots = _collect_screenshots(test_results_dir)
        all_screenshots.extend(_collect_screenshots(run_dir, recursive=False))

        screenshot_files, dropped = _dedup_screenshots(all_screenshots)

        if dropped:
            names = ", ".join(f.name for f in dropped)
            result["data"]["print_logs"].append(
                f"Deduped {len(dropped)} duplicate screenshot(s): {names}"
            )

        if screenshot_files:
            result["data"]["screenshots"].extend(str(f) for f in screenshot_files)
        else:
            # No screenshots captured — note this in logs
            result["data"]["print_logs"].append(
                "No screenshots were captured during the test run."
            )

    except asyncio.TimeoutError:
        result["status"] = "error"
        result["data"]["error"] = f"Playwright test run timed out after {timeout}s"
    except Exception as e:
        result["status"] = "error"
        result["data"]["error"] = f"Setup error: {str(e)}"

    finally:
        # Copy screenshots to the shared screenshot directory
        try:
            if run_dir and run_dir.exists():
                # Collect from test-results subdirectories into run_dir first
                test_results_dir = run_dir / "test-results"
                if test_results_dir.exists():
                    import shutil

                    for img in _collect_screenshots(test_results_dir):
                        dest = run_dir / img.name
                        if not dest.exists():
                            shutil.copy2(img, dest)
                copy_images_to_screenshots(run_dir, screenshot_dir)
        except Exception as copy_err:
            print(f"Error copying screenshots: {copy_err}")

        # Clean up temp spec file (keep config for debugging)
        if tmp_spec_path and os.path.exists(tmp_spec_path):
            try:
                os.unlink(tmp_spec_path)
            except OSError:
                pass

    return result



def _resolve_browsers_path() -> str | None:
    """Return the best PLAYWRIGHT_BROWSERS_PATH for the current environment.

    Checks, in order:
    1. Already set in the environment (honour explicit config).
    2. /pw-browsers (container / CI path).
    3. ~/Library/Caches/ms-playwright (macOS default from `npx playwright install`).
    4. None – let Playwright fall back to its own default resolution.
    """
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return os.environ["PLAYWRIGHT_BROWSERS_PATH"]

    candidates = [
        Path("/pw-browsers"),
        Path.home() / "Library" / "Caches" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",  # Linux default
    ]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.iterdir()):
            return str(candidate)
    return None


def _ensure_playwright_test_module(automation_output_dir: Path) -> None:
    """Make sure ``@playwright/test`` is resolvable from *automation_output_dir*.

    When the Playwright CLI is installed globally (e.g. via ``npm i -g
    @playwright/test``) the ``@playwright/test`` package lives under
    the global ``node_modules``.  Spec files written under
    *automation_output_dir* won't find it because Node resolves
    relative to the file location.  We solve this by symlinking.
    """
    target_dir = automation_output_dir / "node_modules" / "@playwright" / "test"
    if target_dir.exists():
        return  # already present (local install or previous symlink)

    # Try to find the global @playwright/test
    import subprocess as _sp

    try:
        global_prefix = (
            _sp.check_output(["npm", "root", "-g"], stderr=_sp.DEVNULL)
            .decode()
            .strip()
        )
        global_pkg = Path(global_prefix) / "@playwright" / "test"
        if global_pkg.is_dir():
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            target_dir.symlink_to(global_pkg)
            return
    except Exception:
        pass

    # Nothing to do – the import will either work or Playwright will
    # produce a clear error message.


def _build_playwright_config(
    base_url: str,
    output_dir: str,
    json_output_file: str,
    capture_all_screenshots: bool = False,
    test_dir: str | None = None,
    per_test_timeout_ms: int = 60_000,
) -> str:
    """Generate a temporary playwright.config.ts string."""
    screenshot_mode = "on" if capture_all_screenshots else "only-on-failure"
    test_dir_line = f"  testDir: '{test_dir}',\n" if test_dir else ""

    return f"""import {{ defineConfig, devices }} from '@playwright/test';

export default defineConfig({{
{test_dir_line}  outputDir: '{output_dir}',
  timeout: {per_test_timeout_ms},
  retries: 0,
  workers: 1,
  reporter: [
    ['line'],
    ['json', {{ outputFile: '{json_output_file}' }}],
  ],
  use: {{
    baseURL: '{base_url}',
    screenshot: '{screenshot_mode}',
    trace: 'off',
    headless: true,
    viewport: {{ width: 1920, height: 1080 }},
    ignoreHTTPSErrors: true,
  }},
  projects: [
    {{
      name: 'chromium',
      use: {{ ...devices['Desktop Chrome'] }},
    }},
  ],
}});
"""


def _dedup_screenshots(files: list[Path]) -> tuple[list[Path], list[Path]]:
    """Deduplicate screenshot files by content hash, keeping the first occurrence.

    Returns (unique_files, dropped_files).
    """
    import hashlib

    seen_hashes: set[str] = set()
    unique: list[Path] = []
    dropped: list[Path] = []
    for f in files:
        try:
            file_hash = hashlib.md5(f.read_bytes()).hexdigest()
        except OSError:
            continue
        if file_hash not in seen_hashes:
            seen_hashes.add(file_hash)
            unique.append(f)
        else:
            dropped.append(f)
    return unique, dropped


def _collect_screenshots(directory: Path, recursive: bool = True) -> list[Path]:
    """Collect screenshot image files from a directory."""
    if not directory.exists():
        return []

    extensions = {".png", ".jpg", ".jpeg"}
    files = []

    if recursive:
        for ext in extensions:
            files.extend(directory.rglob(f"*{ext}"))
    else:
        for ext in extensions:
            files.extend(directory.glob(f"*{ext}"))

    return sorted(files)
