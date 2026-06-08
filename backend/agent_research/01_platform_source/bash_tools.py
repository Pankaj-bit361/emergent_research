"""Streaming bash execution with partial output on timeout + background process support.

Foreground mode (default): reads stdout/stderr in chunks as they arrive.
On timeout, partial output captured before the kill is returned.

Background mode (wait_ms set): redirects output to disk files, returns a
process_id so the agent can poll for output later via manage_bash_process.

Key design:
- Two-stage kill (SIGTERM → SIGKILL) with process group targeting
- Chunked read(n) instead of readline() for robustness with long lines
- In-stream byte cap to prevent unbounded memory growth (foreground)
- Disk-backed output for background processes (no memory growth)
- Client-provided offsets for idempotent output polling
"""
import asyncio
import logging
import os
import random
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Annotated, Dict, List, Literal, Optional, Tuple

from anyio import BrokenResourceError, ClosedResourceError
from fastmcp import Context, FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

CHUNK_SIZE = 8192
STDOUT_BYTE_CAP = 38_000
STDERR_BYTE_CAP = 2_000
DRAIN_TIMEOUT = 2.0
SIGTERM_GRACE = 1.0
MAX_PROCESSES = 16
RETURN_CODE_RUNNING = -2  # Sentinel: process still alive


async def _safe_ctx_log(ctx: Optional[Context], message: str, level: str = "info") -> None:
    """Log to MCP context, swallowing errors if the session stream has closed."""
    if not ctx:
        return
    try:
        if level == "error":
            await ctx.error(message)
        else:
            await ctx.info(message)
    except (ClosedResourceError, BrokenResourceError):
        pass


# ── Foreground streaming helpers ──────────────────────────────────


async def _read_stream(
    stream: asyncio.StreamReader,
    label: str,
    parts: List[str],
    ctx: Optional[Context],
    byte_cap: int,
) -> None:
    """Read chunks from a stream, split into lines for ctx, cap total bytes."""
    total = 0
    line_buf = ""
    while True:
        chunk = await stream.read(CHUNK_SIZE)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        parts.append(text)
        total += len(chunk)

        if ctx:
            line_buf += text
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                try:
                    await ctx.info(f"[{label}] {line}")
                except (ClosedResourceError, BrokenResourceError):
                    ctx = None  # stream closed — stop logging, keep collecting
                    break

        if total >= byte_cap:
            parts.append(f"\n... [{label.lower()} capped at {byte_cap} bytes]")
            break

    if ctx and line_buf:
        try:
            await ctx.info(f"[{label}] {line_buf}")
        except (ClosedResourceError, BrokenResourceError):
            pass


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Two-stage kill: SIGTERM → grace period → SIGKILL."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=SIGTERM_GRACE)
            return
        except asyncio.TimeoutError:
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    except (ProcessLookupError, PermissionError):
        proc.kill()
    await proc.wait()


async def run_bash_streaming(
    ctx: Optional[Context],
    command: str,
    timeout: float,
    cwd: Optional[str],
) -> Tuple[str, str, int, bool]:
    """Foreground execution with streaming output capture.

    Returns (stdout, stderr, return_code, timed_out).
    """
    script_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            script_path = f.name
            f.write("#!/bin/bash\n")
            f.write(command)

        os.chmod(script_path, 0o755)

        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=True,
        )

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []

        read_tasks = [
            asyncio.create_task(
                _read_stream(proc.stdout, "STDOUT", stdout_parts, ctx, STDOUT_BYTE_CAP)
            ),
            asyncio.create_task(
                _read_stream(proc.stderr, "STDERR", stderr_parts, ctx, STDERR_BYTE_CAP)
            ),
        ]

        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await _kill_process_group(proc)

        try:
            await asyncio.wait_for(
                asyncio.gather(*read_tasks, return_exceptions=True),
                timeout=DRAIN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            for task in read_tasks:
                task.cancel()

        return (
            "".join(stdout_parts),
            "".join(stderr_parts),
            proc.returncode,
            timed_out,
        )
    finally:
        if script_path and os.path.exists(script_path):
            try:
                os.unlink(script_path)
            except OSError:
                pass


# ── Background process store ─────────────────────────────────────


@dataclass
class ProcessEntry:
    process_id: str
    process: asyncio.subprocess.Process
    command: str
    output_dir: str
    script_path: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started_at: float = 0.0
    exited: bool = False
    exit_code: Optional[int] = None


_process_store: Dict[str, ProcessEntry] = {}


def _generate_process_id() -> str:
    """Generate a unique 4-digit process ID."""
    for _ in range(100):
        pid = str(random.randint(1000, 9999))
        if pid not in _process_store:
            return pid
    raise RuntimeError("Failed to generate unique process ID")


def _store_process(entry: ProcessEntry) -> None:
    if len(_process_store) >= MAX_PROCESSES:
        _evict_oldest()
    _process_store[entry.process_id] = entry


def _get_process(process_id: str) -> Optional[ProcessEntry]:
    return _process_store.get(process_id)


def _cleanup_process(entry: ProcessEntry) -> None:
    """Remove entry from store and delete its files. Idempotent."""
    _process_store.pop(entry.process_id, None)
    if os.path.isdir(entry.output_dir):
        shutil.rmtree(entry.output_dir, ignore_errors=True)
    if os.path.exists(entry.script_path):
        try:
            os.unlink(entry.script_path)
        except OSError:
            pass


def _evict_oldest() -> None:
    """Evict one entry: prefer exited, then oldest alive."""
    exited = [e for e in _process_store.values() if e.exited]
    if exited:
        victim = min(exited, key=lambda e: e.started_at)
    elif _process_store:
        victim = min(_process_store.values(), key=lambda e: e.started_at)
    else:
        return
    _cleanup_process(victim)


async def _watch_exit(entry: ProcessEntry) -> None:
    """Fire-and-forget: wait for process exit, update entry state."""
    try:
        await entry.process.wait()
        async with entry.lock:
            entry.exited = True
            entry.exit_code = entry.process.returncode
    except Exception:
        async with entry.lock:
            entry.exited = True
            entry.exit_code = -1


# ── Background execution ─────────────────────────────────────────


def _read_output_file(path: str, offset: int = 0) -> Tuple[str, int]:
    """Read a file from offset, return (content, new_offset)."""
    try:
        size = os.path.getsize(path)
        if size <= offset:
            return "", offset
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
        return data.decode("utf-8", errors="replace"), offset + len(data)
    except FileNotFoundError:
        return "", offset


async def _run_bash_background(
    command: str,
    wait_ms: float,
    cwd: Optional[str],
) -> Tuple[str, str, bool, Optional[int], Optional[str]]:
    """Run command with disk-backed output. Returns partial output + process_id if still running.

    Returns (stdout, stderr, exited, exit_code, process_id_or_none).
    process_id is None if process exited within wait_ms.
    """
    process_id = _generate_process_id()
    output_dir = tempfile.mkdtemp(prefix=f"ebash_{process_id}_")
    stdout_path = os.path.join(output_dir, "stdout.log")
    stderr_path = os.path.join(output_dir, "stderr.log")

    # Write temp script
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, dir=output_dir
    ) as f:
        script_path = f.name
        f.write("#!/bin/bash\n")
        f.write(command)
    os.chmod(script_path, 0o755)

    # Open output files, spawn process, close parent FDs
    stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)

    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            script_path,
            stdout=stdout_fd,
            stderr=stderr_fd,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=True,
        )
    finally:
        os.close(stdout_fd)
        os.close(stderr_fd)

    # Wait for process to exit or yield time to expire
    exited = False
    exit_code = None
    try:
        await asyncio.wait_for(proc.wait(), timeout=wait_ms / 1000.0)
        exited = True
        exit_code = proc.returncode
    except asyncio.TimeoutError:
        pass

    # Read whatever output is available
    stdout_str, _ = _read_output_file(stdout_path)
    stderr_str, _ = _read_output_file(stderr_path)

    if exited:
        # Process finished — clean up, no need to store
        shutil.rmtree(output_dir, ignore_errors=True)
        return stdout_str, stderr_str, True, exit_code, None

    # Process still running — store for later polling
    entry = ProcessEntry(
        process_id=process_id,
        process=proc,
        command=command,
        output_dir=output_dir,
        script_path=script_path,
        started_at=asyncio.get_event_loop().time(),
    )
    _store_process(entry)
    asyncio.create_task(_watch_exit(entry))

    return stdout_str, stderr_str, False, None, process_id


# ── Output formatting (shared) ───────────────────────────────────


def _format_bash_output(
    stdout_str: str, stderr_str: str, return_code: int, timed_out: bool = False, timeout: float = 0
) -> Tuple[str, str, str]:
    """Apply truncation and formatting. Returns (stdout, stderr, output)."""
    if timed_out:
        stderr_str += f"\n[Command timed out after {timeout:.0f} seconds]"

    MAX_OUTPUT_LENGTH = 40000
    RESERVED_FOR_STDERR = 2000
    RESERVED_FOR_EXIT_CODE = 50

    stdout_max = MAX_OUTPUT_LENGTH - RESERVED_FOR_STDERR - RESERVED_FOR_EXIT_CODE
    if len(stdout_str) > stdout_max:
        stdout_str = stdout_str[:stdout_max] + "\n... [stdout truncated]"

    if len(stderr_str) > RESERVED_FOR_STDERR:
        stderr_str = stderr_str[:RESERVED_FOR_STDERR] + "\n... [stderr truncated]"

    output_parts = []
    if stdout_str.strip():
        output_parts.append(stdout_str.rstrip())
    if stderr_str.strip():
        output_parts.append(f"[stderr] {stderr_str.rstrip()}")
    output_parts.append(f"Exit code: {return_code}")
    output = "\n".join(output_parts)

    if len(output) > MAX_OUTPUT_LENGTH:
        exit_code_line = f"\nExit code: {return_code}"
        max_content = MAX_OUTPUT_LENGTH - len(exit_code_line) - 30
        output = output[:max_content] + "\n... [output truncated]" + exit_code_line

    return stdout_str, stderr_str, output


# ── Tool registration ─────────────────────────────────────────────


def register_streaming_bash_tool(mcp: FastMCP, bash_result_cls):
    """Register execute_bash_streaming on the provided FastMCP instance."""

    @mcp.tool(
        description="""Execute bash commands with streaming output capture. Returns partial output on timeout instead of losing it.

## Two modes

### Foreground (default) — command runs to completion or timeout
Set `timeout` (seconds, default 120, max 300). The tool blocks until the command finishes or the timeout expires. On timeout the process is killed and partial output is returned.

### Background — long-running commands you poll later
Set `wait_ms` (milliseconds). The tool waits that long, then returns whatever output has been produced so far **plus a `process_id`**. Use `manage_bash_process` to poll for more output, check status, or kill the process.

## IMPORTANT — do NOT use shell backgrounding
NEVER append `&` to the command. Shell backgrounding detaches the process from the tool's output capture — you get exit code 0 from the shell and lose all real output. Use `wait_ms` instead for long-running commands.

## Output handling
stdout is capped at ~38 KB and stderr at ~2 KB. Do NOT pipe through `head`, `tail`, or `wc` to limit output — the tool already truncates. Use pipes only when you need to transform the output (e.g. `grep`, `jq`, `sort`).

## Examples

Foreground (wait up to 60s):
  command: "npm run build 2>&1", timeout: 60

Background (check back later):
  command: "npx playwright test --reporter=list 2>&1", wait_ms: 10000
  → returns partial output + process_id → use manage_bash_process to poll"""
    )
    async def execute_bash_streaming(
        ctx: Context,
        command: Annotated[str, Field(description="Bash command to execute. Do NOT append & for backgrounding — use wait_ms instead.")],
        timeout: Annotated[int, Field(description="Foreground mode: max seconds to wait (default 120). Ignored when wait_ms is set.", ge=1, le=300)] = 120,
        cwd: Annotated[Optional[str], Field(description="Working directory")] = None,
        wait_ms: Annotated[Optional[int], Field(
            description="Background mode: wait this many ms, then return partial output + process_id if still running. Use manage_bash_process to poll."
        )] = None,
        description: Annotated[Optional[str], Field(
            description="Operator status ping. Only for heavy ops (builds, installs, tests). Skip recon (ls, cat, grep). 3-5 words max. e.g. 'Compiling reactor core', 'Deploying build artifacts'."
        )] = None,
    ):
        """Execute a bash command with streaming output and partial results on timeout."""
        try:
            await _safe_ctx_log(ctx, f"Executing: {command}")

            # Background mode
            if wait_ms is not None:
                stdout_str, stderr_str, exited, exit_code, process_id = (
                    await _run_bash_background(command, float(wait_ms), cwd)
                )

                if exited:
                    stdout_str, stderr_str, output = _format_bash_output(
                        stdout_str, stderr_str, exit_code
                    )
                    await _safe_ctx_log(ctx, f"Command completed with exit code: {exit_code}")
                    return bash_result_cls(
                        success=exit_code == 0,
                        command=command,
                        stdout=stdout_str,
                        stderr=stderr_str,
                        return_code=exit_code,
                        output=output,
                    )

                # Still running — return partial output with process_id marker
                stdout_str, stderr_str, output = _format_bash_output(
                    stdout_str, stderr_str, RETURN_CODE_RUNNING
                )
                output = f"[Process running: ID={process_id}]\n{output}"
                await _safe_ctx_log(ctx, f"Process backgrounded with ID={process_id}")
                return bash_result_cls(
                    success=True,
                    command=command,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    return_code=RETURN_CODE_RUNNING,
                    output=output,
                )

            # Foreground mode (unchanged)
            effective_timeout = float(timeout)
            stdout_str, stderr_str, return_code, timed_out = await run_bash_streaming(
                ctx, command, effective_timeout, cwd
            )

            stdout_str, stderr_str, output = _format_bash_output(
                stdout_str, stderr_str, return_code, timed_out, effective_timeout
            )

            await _safe_ctx_log(ctx, f"Command completed with exit code: {return_code}")

            return bash_result_cls(
                success=return_code == 0,
                command=command,
                stdout=stdout_str,
                stderr=stderr_str,
                return_code=return_code,
                output=output,
            )

        except Exception as e:
            error_msg = f"Failed to execute command: {str(e)}"
            await _safe_ctx_log(ctx, error_msg, level="error")

            output = f"$ {command}\n[Error] {error_msg}\nExit code: -1"

            return bash_result_cls(
                success=False,
                command=command,
                stdout="",
                stderr=error_msg,
                return_code=-1,
                output=output,
            )

    execute_bash_streaming.tags = {"system", "shell", "command"}
    return execute_bash_streaming


def register_manage_process_tool(mcp: FastMCP, bash_result_cls):
    """Register manage_bash_process tool for interacting with background processes."""

    @mcp.tool(
        description="""Poll, inspect, or kill a background process started with execute_bash_streaming(wait_ms=...).

## Actions

- **output** (default): Read new stdout/stderr since `offset`. Returns `next_offset` — pass it back on the next call for incremental reading. Use `offset=0` to get all output from the start.
- **status**: Check if the process is still running or exited. Returns exit code and output file sizes.
- **kill**: Send SIGTERM (then SIGKILL), return final accumulated output, and clean up.

## Typical polling loop

1. execute_bash_streaming(command="...", wait_ms=10000) → process_id, initial output, next_offset
2. manage_bash_process(process_id, action="output", offset=next_offset) → new output, next_offset
3. Repeat step 2 until status shows "exited", then read final output
4. Optionally: manage_bash_process(process_id, action="kill") to stop early"""
    )
    async def manage_bash_process(
        process_id: Annotated[str, Field(description="Process ID from execute_bash_streaming")],
        action: Annotated[str, Field(description="Action: output, kill, or status")] = "output",
        offset: Annotated[int, Field(description="Byte offset for incremental output reading")] = 0,
    ):
        """Manage a background bash process."""
        entry = _get_process(process_id)
        if entry is None:
            return bash_result_cls(
                success=False,
                command="",
                stdout="",
                stderr=f"Process {process_id} not found",
                return_code=-1,
                output=f"[Error] Process {process_id} not found",
            )

        stdout_path = os.path.join(entry.output_dir, "stdout.log")
        stderr_path = os.path.join(entry.output_dir, "stderr.log")

        if action == "status":
            async with entry.lock:
                exited = entry.exited
                exit_code = entry.exit_code
            stdout_size = os.path.getsize(stdout_path) if os.path.exists(stdout_path) else 0
            stderr_size = os.path.getsize(stderr_path) if os.path.exists(stderr_path) else 0
            status = "exited" if exited else "running"
            status_line = f"Process {process_id}: {status}"
            if exited:
                status_line += f" (exit code: {exit_code})"
            status_line += f"\nstdout: {stdout_size} bytes, stderr: {stderr_size} bytes"
            return bash_result_cls(
                success=True,
                command=entry.command,
                stdout="",
                stderr="",
                return_code=exit_code if exited else RETURN_CODE_RUNNING,
                output=status_line,
            )

        if action == "kill":
            async with entry.lock:
                if not entry.exited:
                    await _kill_process_group(entry.process)
                    entry.exited = True
                    entry.exit_code = entry.process.returncode

            # Read final output
            stdout_str, _ = _read_output_file(stdout_path)
            stderr_str, _ = _read_output_file(stderr_path)
            rc = entry.exit_code
            _cleanup_process(entry)

            stdout_str, stderr_str, output = _format_bash_output(stdout_str, stderr_str, rc)
            return bash_result_cls(
                success=rc == 0,
                command=entry.command,
                stdout=stdout_str,
                stderr=stderr_str,
                return_code=rc,
                output=output,
            )

        # action == "output" (default)
        stdout_str, next_stdout = _read_output_file(stdout_path, offset)
        stderr_str, next_stderr = _read_output_file(stderr_path, max(0, offset - (next_stdout - len(stdout_str.encode("utf-8")))))

        async with entry.lock:
            exited = entry.exited
            exit_code = entry.exit_code

        next_offset = max(next_stdout, next_stderr)
        header = f"[Process {process_id}: {'exited' if exited else 'running'}]"
        if exited:
            header += f" (exit code: {exit_code})"
        header += f"\n[next_offset={next_offset}]"

        output_parts = [header]
        if stdout_str.strip():
            output_parts.append(stdout_str.rstrip())
        if stderr_str.strip():
            output_parts.append(f"[stderr] {stderr_str.rstrip()}")
        output = "\n".join(output_parts)

        return bash_result_cls(
            success=True,
            command=entry.command,
            stdout=stdout_str,
            stderr=stderr_str,
            return_code=exit_code if exited else RETURN_CODE_RUNNING,
            output=output,
        )

    manage_bash_process.tags = {"system", "shell", "command"}
    return manage_bash_process
