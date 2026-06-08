"""FastAPI server for the agent tool."""
import hashlib
import json
import sys
import signal
import shutil
import threading
import concurrent.futures
import subprocess
import asyncio
import time
import mimetypes
import os
import tarfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import uvicorn


from plugins.tools.agent.base import ToolError
from plugins.tools.agent.logger import logger
from plugins.tools.utils.constant import GIT_STAGE_EXCLUSIONS
from plugins.tools.utils.utils import remove_stale_git_locks
# Time the MCP import
_mcp_import_start = time.time()
from plugins.tools.agent.mcp_server import get_mcp_server
_mcp_import_time = time.time() - _mcp_import_start

_agent_import_start = time.time()
from plugins.tools.agent.impl_ato import AgentTool as AgentToolATO
from plugins.tools.agent.config import AgentConfig
_agent_import_time = time.time() - _agent_import_start

logger.info("Starting agent server")
logger.info(f"AgentTool import took {_agent_import_time:.2f} seconds")
logger.info(f"MCP import took {_mcp_import_time:.2f} seconds")

# Create global MCP server instance
_mcp_init_start = time.time()
mcp_server = get_mcp_server("Agent-Tools")
tool_mcp_app = mcp_server.mcp.http_app()
logger.info(f"MCP server initialization took {time.time() - _mcp_init_start:.2f} seconds")

app = FastAPI(title="Agent Tool API", description="API for executing agent tasks", lifespan=tool_mcp_app.lifespan)

# Mount MCP tools under /tools path (idempotency handled via MCP middleware hooks)
app.mount("/tools", tool_mcp_app)

# Global lock variable with mutex
is_task_running = False
task_lock = threading.Lock()

# Create a thread pool executor for running background tasks
thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)

class AgentRequest(BaseModel):
    """Request model for agent execution."""
    command: str
    args_path: Optional[str] = None
    auth_token: Optional[str] = None
    base_url: Optional[str] = None
    plugin_lib_path_to_export: str = ''
    is_mock_setup: bool = False
    ato: Optional[bool] = False
    payload: Optional[Dict[str, Any]] = None

class CommandRequest(BaseModel):
    """Request model for command execution."""
    commands: List[str]
    cwd: Optional[str] = None
    timeout: Optional[int] = 300  # 5 minutes default

class DownloadFileRequest(BaseModel):
    """Request model for file download."""
    file_paths: List[str]  # Support batch download of multiple files
    timeout: Optional[int] = 300


class UploadInitRequest(BaseModel):
    """Request model for internal chunked uploads."""

    upload_id: Optional[str] = None
    target_path: str = "/root/workspace"
    archive_format: str = "tar.gz"
    archive_sha256: Optional[str] = None
    total_chunks: Optional[int] = None
    reset: bool = False
    extract: bool = True


class UploadCompleteRequest(BaseModel):
    """Request model for completing an internal chunked upload."""

    target_path: Optional[str] = None
    archive_sha256: Optional[str] = None
    total_chunks: Optional[int] = None
    reset: Optional[bool] = None
    extract: Optional[bool] = None


class GitCommitRequest(BaseModel):
    """Request model for git commit."""
    work_space_dir: str = "/app"
    request_id: Optional[str] = None
    job_id: Optional[str] = None
    # Off by default; the caller sets to True per request to enable the
    # stale-lock cleanup before subprocess git commands run.
    cleanup_stale_locks: bool = False


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


def _upload_root() -> Path:
    return Path(os.environ.get("INTERNAL_UPLOAD_ROOT", "/tmp/internal-upload"))


def _upload_dir(upload_id: str) -> Path:
    safe = upload_id.strip()
    if not safe or not all(ch.isalnum() or ch in "-_" for ch in safe):
        raise HTTPException(status_code=400, detail="Invalid upload_id")
    return _upload_root() / safe


def _metadata_path(upload_id: str) -> Path:
    return _upload_dir(upload_id) / "metadata.json"


def _chunk_path(upload_id: str, index: int) -> Path:
    if index < 0:
        raise HTTPException(status_code=400, detail="Chunk index must be non-negative")
    return _upload_dir(upload_id) / "chunks" / f"{index:08d}.part"


def _read_upload_metadata(upload_id: str) -> dict:
    path = _metadata_path(upload_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Upload not found: {upload_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_upload_metadata(upload_id: str, metadata: dict) -> None:
    directory = _upload_dir(upload_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chunks").mkdir(parents=True, exist_ok=True)
    _metadata_path(upload_id).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _clear_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _allowed_upload_target_roots() -> list[Path]:
    raw = os.environ.get(
        "INTERNAL_UPLOAD_ALLOWED_TARGET_ROOTS",
        "/root/workspace:/app/workspace:/workspace",
    )
    roots = []
    for item in raw.split(":"):
        item = item.strip()
        if item:
            roots.append(Path(item).resolve(strict=False))
    return roots


def _safe_upload_target_path(target_path: str) -> Path:
    target = Path(target_path or "/root/workspace")
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="target_path must be absolute")
    resolved = target.resolve(strict=False)
    for root in _allowed_upload_target_roots():
        if os.path.commonpath([str(root), str(resolved)]) == str(root):
            return resolved
    raise HTTPException(
        status_code=400,
        detail="target_path must be under an allowed workspace root",
    )


def _validate_tar_member(target: Path, member: tarfile.TarInfo) -> None:
    member_name = member.name
    if member_name.startswith("/") or "\x00" in member_name:
        raise HTTPException(
            status_code=400, detail=f"Unsafe archive member: {member_name}"
        )
    destination = (target / member_name).resolve()
    target_resolved = target.resolve()
    if os.path.commonpath([str(target_resolved), str(destination)]) != str(
        target_resolved
    ):
        raise HTTPException(
            status_code=400, detail=f"Unsafe archive member: {member_name}"
        )
    if member.issym() or member.islnk() or member.isdev():
        raise HTTPException(
            status_code=400, detail=f"Unsupported archive member: {member_name}"
        )


def _extract_tar_gz(archive_path: Path, target_path: str, reset: bool) -> int:
    target = _safe_upload_target_path(target_path)

    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            _validate_tar_member(target, member)
        if reset:
            staging = archive_path.parent / "extract-staging"
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            for member in members:
                _validate_tar_member(staging, member)
            archive.extractall(staging)
            _clear_directory(target)
            for child in staging.iterdir():
                shutil.move(str(child), target / child.name)
            shutil.rmtree(staging)
        else:
            target.mkdir(parents=True, exist_ok=True)
            archive.extractall(target)
        return len(members)


@app.post("/internal/upload/init")
async def internal_upload_init(body: UploadInitRequest):
    """Initialize a generic internal chunked upload."""
    if body.archive_format not in {"tar.gz", "tgz"}:
        raise HTTPException(status_code=400, detail="Only tar.gz uploads are supported")
    upload_id = body.upload_id or str(uuid.uuid4())
    upload_directory = _upload_dir(upload_id)
    if upload_directory.exists():
        shutil.rmtree(upload_directory)
    metadata = {
        "upload_id": upload_id,
        "target_path": body.target_path,
        "archive_format": body.archive_format,
        "archive_sha256": body.archive_sha256 or "",
        "total_chunks": body.total_chunks or 0,
        "reset": body.reset,
        "extract": body.extract,
        "created_at": int(time.time()),
    }
    _write_upload_metadata(upload_id, metadata)
    return {"upload_id": upload_id, "status": "initialized"}


@app.put("/internal/upload/{upload_id}/chunks/{index}")
async def internal_upload_chunk(upload_id: str, index: int, request: Request):
    """Store one binary upload chunk."""
    _read_upload_metadata(upload_id)
    data = await request.body()
    chunk_sha = hashlib.sha256(data).hexdigest()
    expected_sha = request.headers.get("X-Chunk-SHA256", "").strip().lower()
    if expected_sha and expected_sha != chunk_sha:
        raise HTTPException(status_code=400, detail="Chunk SHA-256 mismatch")
    path = _chunk_path(upload_id, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "upload_id": upload_id,
        "index": index,
        "bytes": len(data),
        "sha256": chunk_sha,
    }


@app.post("/internal/upload/{upload_id}/complete")
async def internal_upload_complete(
    upload_id: str,
    body: UploadCompleteRequest,
):
    """Assemble a chunked upload and optionally extract it."""
    metadata = _read_upload_metadata(upload_id)
    total_chunks = body.total_chunks or int(metadata.get("total_chunks") or 0)
    if total_chunks <= 0:
        raise HTTPException(status_code=400, detail="total_chunks is required")

    upload_directory = _upload_dir(upload_id)
    archive_path = upload_directory / "upload.tar.gz"
    sha = hashlib.sha256()
    total_bytes = 0
    with archive_path.open("wb") as output:
        for index in range(total_chunks):
            chunk = _chunk_path(upload_id, index)
            if not chunk.exists():
                raise HTTPException(status_code=400, detail=f"Missing chunk {index}")
            data = chunk.read_bytes()
            output.write(data)
            sha.update(data)
            total_bytes += len(data)

    actual_sha = sha.hexdigest()
    expected_sha = (
        body.archive_sha256 or metadata.get("archive_sha256") or ""
    ).strip().lower()
    if expected_sha and expected_sha != actual_sha:
        raise HTTPException(status_code=400, detail="Archive SHA-256 mismatch")

    should_extract = (
        metadata.get("extract", True) if body.extract is None else body.extract
    )
    member_count = 0
    target_path = body.target_path or metadata.get("target_path") or "/root/workspace"
    if should_extract:
        reset = bool(metadata.get("reset", False) if body.reset is None else body.reset)
        member_count = _extract_tar_gz(archive_path, target_path, reset)

    metadata.update(
        {
            "completed_at": int(time.time()),
            "archive_bytes": total_bytes,
            "archive_sha256": actual_sha,
            "target_path": target_path,
            "member_count": member_count,
            "status": "complete",
        }
    )
    _write_upload_metadata(upload_id, metadata)
    return {
        "upload_id": upload_id,
        "status": "complete",
        "archive_bytes": total_bytes,
        "archive_sha256": actual_sha,
        "target_path": target_path,
        "member_count": member_count,
    }


@app.delete("/internal/upload/{upload_id}")
async def internal_upload_delete(upload_id: str):
    """Delete upload staging files."""
    directory = _upload_dir(upload_id)
    if directory.exists():
        shutil.rmtree(directory)
    return {"upload_id": upload_id, "status": "deleted"}


def execute_agent_api(
        command: str,
        args_path: Optional[str] = None,
        auth_token: Optional[str] = None,
        base_url: Optional[str] = None,
        plugin_lib_path_to_export: str = '',
        is_mock_setup: bool = False,
        payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Execute agent tool via API endpoint."""
    try:
        # Map subcommands to internal commands
        cmd_map = {
            "submit_task": "submit",
            "resume_task": "resume"
        }
        logger.info(f"command: {command}")
        internal_command = cmd_map.get(command)
        if not internal_command:
            raise ToolError(f"Unknown command: {command}. Use 'submit_task' or 'resume_task'")

        agent_tool = AgentToolATO(AgentConfig(
            auth_token=auth_token,
            base_url=base_url,
            is_mock_setup=is_mock_setup,
            plugin_lib_path_to_export=plugin_lib_path_to_export,
        ))

        if payload is not None:
            logger.info("Using provided payload")
        else:
            logger.info(f"Loading payload from: {args_path}")
            payload = json.load(open(args_path))

        result = agent_tool.submit(payload)
        return str(result) if result else "Task completed successfully"

    except Exception as e:
        logger.error(f"Error executing agent task: {str(e)}", exc_info=True)
        return f"Error executing agent task: {str(e)}"

def run_agent_task_thread(request: AgentRequest):
    """Run agent task in a separate thread."""
    global is_task_running
    try:
        logger.info("Starting long-running task  in thread...")
        # Keep the sleep to simulate a long-running task

        result = execute_agent_api(
            command=request.command,
            args_path=request.args_path,
            auth_token=request.auth_token,
            base_url=request.base_url,
            plugin_lib_path_to_export=request.plugin_lib_path_to_export,
            is_mock_setup=request.is_mock_setup,
            payload=request.payload
        )
        logger.info(f"Task completed with result: {result}")
        return result
    except Exception as e:
        logger.error(f"Task failed: {str(e)}", exc_info=True)
        raise e
    finally:
        with task_lock:
            is_task_running = False
        logger.info("Task completed, released lock")

@app.post("/execute")
async def execute_agent(request: AgentRequest):
    """Execute an agent task asynchronously using a separate thread."""
    global is_task_running

    with task_lock:
        if is_task_running:
            raise HTTPException(
                status_code=409,
                detail="Another task is currently running. Please try again later."
            )

        is_task_running = True
        logger.info("Task started, acquired lock")

    # Submit the task to the thread pool instead of using FastAPI's background tasks
    thread_pool.submit(run_agent_task_thread, request)
    return {"status": "accepted"}

@app.get("/status")
async def get_status():
    """Get the current status of the agent."""
    # logger.info(f"Status check: is_task_running = {is_task_running}")
    return {"is_task_running": is_task_running}

@app.post("/run-command")
async def run_command(request: CommandRequest):
    """Execute a shell command and return the output without blocking the event loop."""
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,  # Use default thread pool
            lambda: subprocess.run(
                request.commands,
                capture_output=True,
                text=True,
                cwd=request.cwd,
                timeout=request.timeout
            )
        )
        return {
            "status": "success",
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": request.commands
        }

    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {request.timeout} seconds: {request.commands}")
        raise HTTPException(
            status_code=408,
            detail=f"Command timed out after {request.timeout} seconds"
        )
    except Exception as e:
        logger.error(f"Error executing command: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error executing command: {str(e)}"
        )

@app.post("/download-file")
async def download_file(request: DownloadFileRequest):
    """Stream file content directly without loading into memory."""
    
    # Only support single file streaming
    if len(request.file_paths) != 1:
        raise HTTPException(
            status_code=400,
            detail="Streaming only supports single file downloads"
        )
    
    file_path = request.file_paths[0]
    
    # Check if file exists and is readable
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {file_path}"
        )
    
    if not os.path.isfile(file_path):
        raise HTTPException(
            status_code=400,
            detail=f"Path is not a file: {file_path}"
        )
    
    # Get file size for Content-Length header
    try:
        file_size = os.path.getsize(file_path)
    except Exception as e:
        logger.error(f"Error getting file size for {file_path}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error accessing file: {str(e)}"
        )
    
    # Detect content type
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = "application/octet-stream"
    
    # Create an async generator that yields file chunks with proper error handling
    async def iterfile():
        """Async generator function to read file in chunks."""
        bytes_read = 0
        chunk_size = 65536  # 64KB chunks
        
        try:
            # Use run_in_executor for async file reading
            # IMPORTANT: Open and read file entirely within the executor to avoid thread safety issues
            loop = asyncio.get_running_loop()
            
            def read_file_chunk(path, offset, size):
                """Thread-safe file reading - opens, seeks, reads, and closes file."""
                with open(path, 'rb') as f:
                    f.seek(offset)
                    return f.read(size)
            
            while bytes_read < file_size:
                # Each read is self-contained with its own file handle
                chunk = await loop.run_in_executor(
                    None, 
                    read_file_chunk, 
                    file_path, 
                    bytes_read, 
                    min(chunk_size, file_size - bytes_read)
                )
                if not chunk:
                    break
                bytes_read += len(chunk)
                yield chunk
            
            # Verify we read the entire file
            if bytes_read < file_size:
                logger.error(f"File read incomplete: {bytes_read}/{file_size} bytes for {file_path}")
                # Client will detect truncation from Content-Length mismatch
                
        except Exception as e:
            logger.error(f"Error streaming file {file_path}: {str(e)}", exc_info=True)
            # The streaming has started, we can't change status code
            # But the client will detect truncation from Content-Length
            raise  # This will cause connection to close
    
    # Return streaming response with Content-Length for error detection
    return StreamingResponse(
        iterfile(),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{os.path.basename(file_path)}"',
            "Content-Length": str(file_size)
        }
    )

@app.post("/git-commit")
async def git_commit(request: GitCommitRequest):
    """Create git commit and return commit ID."""
    try:
        loop = asyncio.get_running_loop()

        def execute_git_commands():
            """Execute git commands synchronously."""
            work_dir = request.work_space_dir
            request_id = request.request_id or "manual-commit"

            if request.cleanup_stale_locks:
                remove_stale_git_locks(work_dir)

            # Check if git repo
            result = subprocess.run(
                f"cd {work_dir} && git rev-parse --is-inside-work-tree 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"Not a git repository: {work_dir}")
                return None

            # Stage changes
            stage_cmd = f"cd {work_dir} && git add -A {GIT_STAGE_EXCLUSIONS}"
            stage_result = subprocess.run(
                stage_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )

            if stage_result.returncode != 0:
                logger.error(f"Failed to stage: {stage_result.stderr}")
            else:
                logger.info("Staged changes successfully")

            # Commit changes
            commit_msg = f"auto-commit for {request_id}"
            commit_cmd = f"cd {work_dir} && git diff --staged --quiet || git commit -m '{commit_msg}'"
            commit_result = subprocess.run(
                commit_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )

            if commit_result.returncode == 0:
                logger.info(f"Created commit: {commit_msg}")
            else:
                logger.info("No changes to commit")

            # Get commit ID
            get_commit_result = subprocess.run(
                f"cd {work_dir} && git rev-parse HEAD",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            if get_commit_result.returncode == 0:
                commit_id = get_commit_result.stdout.strip()
                logger.info(f"Latest commit ID: {commit_id}")
                return commit_id
            else:
                logger.error(f"Failed to get commit ID: {get_commit_result.stderr}")
                return None

        # Run in executor to avoid blocking
        commit_id = await loop.run_in_executor(None, execute_git_commands)

        if not commit_id:
            raise HTTPException(
                status_code=500,
                detail="Failed to create or retrieve commit"
            )

        return {
            "status": "success",
            "commit_id": commit_id
        }

    except subprocess.TimeoutExpired:
        logger.error("Git command timed out")
        raise HTTPException(
            status_code=408,
            detail="Git command timed out"
        )
    except Exception as e:
        logger.error(f"Error in git commit: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

_shutting_down = False

def handle_shutdown(_signum, _frame):
    """Handle shutdown signals gracefully.

    Instead of sys.exit(0) which kills in-flight MCP tool executions
    (causing ClosedResourceError crashes), we let uvicorn's own graceful
    shutdown drain active requests before exiting.
    """
    global _shutting_down
    if _shutting_down:
        # Second signal — force exit
        logger.warning("Forced shutdown (second signal)")
        thread_pool.shutdown(wait=False)
        sys.exit(1)
    _shutting_down = True
    logger.info("Received shutdown signal, letting uvicorn drain in-flight requests...")
    thread_pool.shutdown(wait=False)
    # Raise KeyboardInterrupt on the main thread to trigger uvicorn's
    # graceful shutdown instead of immediately killing the process.
    raise KeyboardInterrupt

def start_server(host: str = "0.0.0.0", port: int = 8010):
    """Start the FastAPI server."""
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        workers=1  # Single worker as requested
    )

if __name__ == "__main__":
    start_server()
