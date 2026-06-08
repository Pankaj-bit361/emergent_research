"""Implementation of the agent cli."""
from enum import Enum
import json
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Literal, Tuple
from datetime import datetime, timezone

import requests

from .base import ToolError
from .config import AgentConfig
from .image_handler import get_screenshots, delete_screenshots
from ..file_editor.impl import EditTool
from ..utils.constant import GIT_STAGE_EXCLUSIONS, DEFAULT_SUCCESS_ENV_MESSAGE, DEFAULT_FAILURE_ENV_MESSAGE, ENV_FAILED_TRAJ
from ..utils.utils import create_trajectory
from ..utils.enums import AgentType, CommandExecutionMode

# Single logger setup at module level
logger = logging.getLogger("agent_tool")
logger.propagate = False
logger.setLevel(logging.INFO)

# Define single formatter
formatter = logging.Formatter('%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s')

# Remove any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)
try:
    # Create rotating file handler
    file_handler = RotatingFileHandler(
        "/var/log/e1_agent.log",
        maxBytes=10*1024*1024,  # 10MB per file
        backupCount=5            # Keep 5 backup files
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"Error creating log file: {e}")

# Setup single console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)

# Remove any existing basicConfig setup if it exists
Command = Literal["submit", "resume"]
class CallExecutionMode(Enum):
    EXECUTE_IN_SYNC = 'EXECUTE_IN_SYNC'
    ACCEPT_EXECUTION_REQUEST = 'ACCEPT_EXECUTION_REQUEST'
    EXECUTION_WITH_CACHED_LLM_RESPONSE = 'EXECUTION_WITH_CACHED_LLM_RESPONSE'

def truncate(content, max_chars, message_type='Observation'):
    """Truncate the middle of the observation content if it is too long."""
    if len(content) <= max_chars or max_chars == -1:
        return content
    # truncate the middle and include a message to the LLM about it
    half = max_chars // 2
    return (
        content[:half]
        + f'\n[... {message_type} truncated due to length ...]\n'
        + content[-half:]
    )

def set_task(payload, local_observation: str, prev_response):
    task = ''
    if prev_response.get('cmd_execution_mode',None) == CommandExecutionMode.TRANSITION_MAIN_TO_SUB.value:
        task = prev_response.get('action', '')
    else:
        task = local_observation

    payload['task'] = [{
        'message': task,
        'triggered_by': 'system'
    }]

def _check_terminal_state(data: Dict[str, Any]) -> tuple[bool, Any | None]:
    if data.get('pause_client'):
        return True, data.get('state')

    return False, data.get('state')

def get_initial_commit_id():
    initial_commit_id = Path("/root/.git_init_commit_hash").read_text()
    return initial_commit_id

class PodResourceMonitor:
    """Monitor pod resource usage with percentage-based thresholds."""

    def __init__(self, agent_tool: 'AgentTool'):
        self.agent_tool = agent_tool

    def get_memory_usage_detailed(self, job_id: str) -> Tuple[float, str]:
        """Get memory usage percentage and display message."""
        try:
            cmd = '''if [ -f /sys/fs/cgroup/memory.max ]; then
    max=$(cat /sys/fs/cgroup/memory.max)
    current=$(cat /sys/fs/cgroup/memory.current)
    inactive=$(awk '/^inactive_file/{print $2}' /sys/fs/cgroup/memory.stat)
    used=$((current - inactive))
    awk -v u=$used -v m=$max 'BEGIN{pct=u*100/m; printf "%.1f|Memory: %.2fGB/%.2fGB (%.1f%%)", pct, u/1024/1024/1024, m/1024/1024/1024, pct}'
else
    echo "0.0|Memory: N/A"
fi'''

            result, success = self.agent_tool.execute_bash_command(job_id, cmd)
            if success and result.strip():
                parts = result.strip().split('|', 1)
                if len(parts) == 2:
                    return float(parts[0]), parts[1]
        except Exception:
            pass
        return 0.0, ""

    def get_cpu_load_detailed(self, job_id: str) -> Tuple[float, str]:
        """Get CPU usage percentage and display message."""
        try:
            cmd = '''if [ -f /sys/fs/cgroup/cpu.max ]; then
    quota=$(cut -d' ' -f1 /sys/fs/cgroup/cpu.max)
    period=$(cut -d' ' -f2 /sys/fs/cgroup/cpu.max)
    if [ "$quota" = "max" ]; then
        echo "0.0|CPU: 0.0% (unlimited)"
    else
        start=$(awk '/usage_usec/{print $2}' /sys/fs/cgroup/cpu.stat)
        sleep 1
        end=$(awk '/usage_usec/{print $2}' /sys/fs/cgroup/cpu.stat)
        awk -v s=$start -v e=$end -v q=$quota -v p=$period 'BEGIN{limit=q/p; cores=(e-s)/1000000; pct=cores*100/limit; printf "%.1f|CPU: %.1f%% (%.3f/%.2f cores)", pct, pct, cores, limit}'
    fi
else
    echo "0.0|CPU: N/A"
fi'''

            result, success = self.agent_tool.execute_bash_command(job_id, cmd)
            if success and result.strip():
                parts = result.strip().split('|', 1)
                if len(parts) == 2:
                    return float(parts[0]), parts[1]
        except Exception:
            pass
        return 0.0, ""

    def get_storage_usage_detailed(self, job_id: str, path: str = '/app') -> Tuple[float, str]:
        """Get storage usage percentage and display message."""
        try:
            cmd = f'''if [ -d "{path}" ]; then
    df -h "{path}" | awk 'NR==2{{pct=$5; gsub(/%/,"",pct); printf "%.0f|Disk: %s/%s (%s)", pct, $3, $2, $5}}'
else
    echo "0.0|Disk: N/A"
fi'''

            result, success = self.agent_tool.execute_bash_command(job_id, cmd)
            if success and result.strip():
                parts = result.strip().split('|', 1)
                if len(parts) == 2:
                    return float(parts[0]), parts[1]
        except Exception:
            pass
        return 0.0, ""

    def check_thresholds(self, job_id: str, config: 'AgentConfig') -> Optional[str]:
        """Check resource thresholds and return warning if exceeded."""
        memory_pct, memory_output = self.get_memory_usage_detailed(job_id)
        cpu_pct, cpu_output = self.get_cpu_load_detailed(job_id)
        storage_pct, storage_output = self.get_storage_usage_detailed(job_id)

        logger.info(f"check_thresholds: memory: {memory_pct}% ({memory_output}), cpu: {cpu_pct}% ({cpu_output}), storage: {storage_pct}% ({storage_output})")

        warnings = []
        details = []
        parsing_failures = []

        if memory_pct > config.memory_threshold:
            warnings.append(f"Memory {memory_pct:.1f}%")
            if memory_output:
                details.append(memory_output)
        elif memory_pct == 0.0 and not memory_output:
            parsing_failures.append("memory")

        if cpu_pct > config.cpu_threshold:
            warnings.append(f"CPU {cpu_pct:.1f}%")
            if cpu_output:
                details.append(cpu_output)
        elif cpu_pct == 0.0 and not cpu_output:
            parsing_failures.append("CPU")

        if storage_pct > config.storage_threshold:
            warnings.append(f"Disk {storage_pct:.1f}%")
            if storage_output:
                details.append(storage_output)
        elif storage_pct == 0.0 and not storage_output:
            parsing_failures.append("storage")

        # Log parsing failures for debugging
        if parsing_failures:
            logger.warning(f"Resource monitoring parsing failures: {', '.join(parsing_failures)}")

        if warnings:
            warning_msg = f"\n🚨 RESOURCE WARNING: {' | '.join(warnings)}\n"
            if details:
                warning_msg += f"Current usage: {' | '.join(details)}\n"
            return warning_msg

        return None

class AgentTool:
    """Main implementation of the agent tool."""

    def __init__(self, config: Optional[AgentConfig] = None):
        """Initialize the agent tool."""
        self.config = config or AgentConfig.from_env()
        self.edit_tool = EditTool()
        self.session = self.setup_http_session()
        self._job_handler = None
        # Use the module-level logger
        self.logger = logger
        self.lockfile = '/tmp/agent_tool.lock'
        self.resource_monitor = PodResourceMonitor(self)

    def setup_http_session(self) -> requests.Session:
        """Setup HTTP session with minimal retry logic."""
        session = requests.Session()
        # Remove the retry adapter since we're handling retries manually
        return session

    def _refresh_session(self) -> None:
        """Refresh the HTTP session to handle connection corruption after long operations."""
        logger.info("Refreshing HTTP session due to connection corruption")
        self.session.close()  # Close existing connections
        self.session = self.setup_http_session()

    def execute_hooks_command(self, data, agent_name, job_id,work_space_dir):
        # Handle execution hooks from response
        execution_hooks = data.get('execution_hooks', {})
        if execution_hooks:
            hooks = data['execution_hooks']
            hook_type = hooks.get('type')

            if hooks.get('cmd'):
                hook_cmd = f"cd {work_space_dir} && {hooks.get('cmd')}"
            else:
                return execution_hooks

            if hook_type == 'init':
                # Execute init hooks before creating trajectory entry
                if hook_cmd:
                    result, success = self.handle_cmd_execution(job_id, hook_cmd, hook_type=hook_type)
                    hooks['cmd_response'] = result
                    hooks['success'] = success
                    execution_hooks = hooks  # Preserve for next iteration

            elif hook_type == 'finish' and agent_name != "EmergentAssistant":
                if hook_cmd:
                    result, success = self.handle_cmd_execution(job_id, hook_cmd, hook_type=hook_type)
                    hooks['cmd_response'] = result
                    hooks['success'] = success
                    execution_hooks = hooks
        return execution_hooks

    def submit(self, payload: Dict[str, Any], job_id: Optional[str] = None) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
        """Submit a task and handle the response loop."""
        prev_success = True
        execution_hooks = None  # Track execution hooks between iterations
        delete_screenshots()
        initial_commit_id = None
        human_timestamp = None

        is_him = False # the is temporary flag in future human intervention will not be coming from payload

        post_traj_payload = {}
        iteration = 0

        context_execution_request = {}
        context_execution_response = {}

        # Check if this is a continuation (payload has id)
        if payload.get('id'):
            work_space_dir = payload['payload'].get('work_space_dir') if payload['payload'].get('work_space_dir') else '/app'
            job_id = payload['id']

            human_timestamp = payload.get('payload', {}).get('human_timestamp')

            is_him = payload.get('payload', {}).get('is_him', False)
        else:
            context_execution_request = payload['payload'].get('context_execution_request') or {}
            # Original flow for new submissions
            work_space_dir = payload['payload'].get('work_space_dir') if payload['payload'].get('work_space_dir') else '/app'

            agent_name = "EmergentAssistant"

            # Create latest_job_details.json for rollback functionality
            client_ref_id = payload.get('client_ref_id')
            if client_ref_id:
                self.update_latest_job_details(client_ref_id, None, work_space_dir)

            # Initialize environment for fresh cases
            logger.info(f"Initializing environment for fresh case in work_space_dir: {work_space_dir}")
            initial_commit_id = get_initial_commit_id()
            if initial_commit_id:
                payload['payload']['initial_commit_id'] = initial_commit_id

        # Transform payload before making request
        transformed_payload = self.transform_payload_for_agent_service(payload)

        if is_him:
            transformed_payload['payload']['is_him'] = True

        if human_timestamp:
            transformed_payload['payload']['human_timestamp'] = human_timestamp

        # Handle this agent_name properly in HITL
        prev_response = None
        local_observation = None
        execution_hooks = {}
        lazy_llm_call_enabled = payload['payload'].get('lazy_llm_call_enabled', False)
        mock_llm = payload['payload'].get('mock_llm', False)
        proxy_url = payload['payload'].get('proxy_url', None)

        failure_observation = None
        response = None
        while iteration < self.config.max_iterations:

            logger.info(f"Starting iteration {iteration}")
            iteration += 1

            # Update payload if we have previous action
            if prev_response:
                observation = failure_observation if failure_observation is not None else local_observation
                set_task(transformed_payload['payload'], observation, prev_response.get('data', {}))
                transformed_payload['payload']['env_success'] = prev_success

                if job_id:
                    transformed_payload['id'] = job_id
                transformed_payload['payload']['execution_hooks'] = execution_hooks

                image_list = prev_response.get('data', {}).get('image_list')
                if prev_response.get('data', {}).get('image_list'):
                    self.add_image_list_to_payload(image_list, transformed_payload)

            screenshot_images = get_screenshots(max_images=5)
            logger.info(f"len(screenshot_images): {len(screenshot_images)}")

            if screenshot_images:
                self.add_screenshots_to_payload(screenshot_images, transformed_payload)

            if context_execution_response:
                transformed_payload['payload']['context_execution_response'] = context_execution_response

            if post_traj_payload:
                transformed_payload['post_traj_payload'] = post_traj_payload
                post_traj_payload = None

            if screenshot_images and transformed_payload.get('post_traj_payload') and transformed_payload['post_traj_payload'].get('traj_payload'):
                    transformed_payload['post_traj_payload']['traj_payload']['base64_image_list'] = transformed_payload['payload']['base64_image_list']

            attempt = 0
            max_retries = 3
            while attempt < max_retries:
                # Generate a new unique request_id for each request
                current_request_id = str(uuid.uuid4())
                transformed_payload['request_id'] = current_request_id

                # Pass retry info at root level
                transformed_payload['attempt'] = attempt
                transformed_payload['max_retries'] = max_retries

                logger.info(f"Generated new request_id: {current_request_id}, for client_ref_id: {transformed_payload.get('client_ref_id')}, attempt: {attempt}/{max_retries}")

                response = self._make_agent_request(
                    transformed_payload=transformed_payload,
                    lazy_llm_call_enabled=lazy_llm_call_enabled,
                    proxy_url=proxy_url,
                    mock_llm=mock_llm
                )

                if not response.get('retry_with_diff_request_id', False):
                    break

                attempt += 1
                # Retry with 1 then 6 then
                time.sleep(1+(attempt*5))

            # clear screenshots after making request
            delete_screenshots()

            # base64_image_list from payload can be image_list or screenshot_images
            base64_image_list = transformed_payload['payload'].pop('base64_image_list', [])
            if screenshot_images:
                base64_image_list = []

            # Update job_id if not set
            if not job_id:
                job_id = response.get('job_id')
                logger.info(f"Got job ID: {job_id}")
                client_ref_id = transformed_payload['client_ref_id']
                if not job_id:
                    logger.error("Job ID not found in response making trajectory for ENV_START_FAILED")

                    traj_entry = ENV_FAILED_TRAJ.copy()
                    traj_entry['error_ts'] = traj_entry['timestamp'] = datetime.now(timezone.utc).isoformat()
                    traj_entry['error_message'] = response.get('error_message', 'ENV_START_FAILED')
                    traj_entry['agent_run_id'] = client_ref_id
                    traj_entry['request_id'] = current_request_id

                    create_trajectory(traj_payload=traj_entry, base_url=self.config.base_url, auth_token=self.config.auth_token, commit_id=initial_commit_id, job_id=client_ref_id)
                    return None

            if self.break_loop_on_error(response, job_id):
                break

            # Process response
            data = response['data']
            local_observation = data['observation'] or ""

            env_success = data.get('env_success', True)

            cmd_mode = data.get('cmd_execution_mode')
            agent_name = data.get('agent_name') or 'EmergentAssistant'
            execution_hooks = self.execute_hooks_command(data, agent_name, job_id,work_space_dir)

            failure_observation = None

            if 'EXECUTION IN PROGRESS' in local_observation:
                if cmd_mode == CommandExecutionMode.EXECUTE_IN_ENV.value and data['action']:
                    logger.info(f"Handling lazy execution: {data['function_name']} with command: {data['action']}")
                    if self.config.is_mock_setup:
                        local_observation, env_success = data['mock_response'], data['mock_success']
                        #TODO add assert for mock command and actual command as well
                    else:
                        local_observation, env_success = self.handle_cmd_execution(
                            job_id,
                            data['action']
                        )
                    local_observation, cmd_mode, failure_observation = self._update_cmd_mode_for_edit(data.get('function_name'), data.get('agent_name'), local_observation, env_success, cmd_mode, data)
                    logger.info(f"local_observation: {local_observation} and env_success: {env_success} and cmd_mode: {cmd_mode} and failure_observation: {failure_observation}")
                else:
                    logger.info(f"Skipping LAZY EXECUTION for 'cmd_execution_mode': {data.get('cmd_execution_mode', 'None')} and {data.get('action', 'None')}")

            context_execution_response = {}
            context_execution_request = data.get('context_execution_request') or {}
            logger.info(f"context_execution_request: {context_execution_request}")
            for key, command in context_execution_request.items():
                result, success = self.execute_bash_command(job_id, command)
                if success:
                    context_execution_response[key] = result

            is_traj_terminal_state, terminal_state = _check_terminal_state(data)

            logger.info(f"is_traj_terminal_state: {is_traj_terminal_state}")
            if is_traj_terminal_state:
                logger.info(f"Received terminal state {terminal_state}, ending execution")
                break

            prev_success = env_success
            prev_response = response
            transformed_payload['resume'] = None
            is_him = False
            transformed_payload['payload']['is_him'] = False

            commit_id = self.git_commit(work_space_dir, request_id=current_request_id, job_id=job_id)
            post_traj_payload = {
                "job_id": job_id,
                "client_ref_id": job_id,
                "commit_id": commit_id,
                "request_id": current_request_id,
                "traj_payload": {
                    "observation": local_observation,
                    "base64_image_list": base64_image_list,
                    "cmd_execution_mode": cmd_mode,
                    "next_call_agent": data.get('next_call_agent', ''),
                    "env_success": env_success,
                    "execution_hooks": execution_hooks,
                    "attempt": attempt,
                    "max_retries": max_retries
                }
            }
        return transformed_payload, response

    def _update_cmd_mode_for_edit(self, function_name, agent_name, local_observation, env_success, cmd_mode, data):
        failure_observation = None
        if 'file_editor str_replace' in data['action'] and agent_name == "EmergentAssistant" and not env_success:
            logger.info("Updating cmd_mode for str_replace_editor in EmergentAssistant")
            failure_observation = local_observation
            local_observation = "EXECUTION IN PROGRESS"
            cmd_mode = CommandExecutionMode.TRANSITION_MAIN_TO_SUB.value
            data['next_call_agent'] = 'SkilledAssistant'
            try:
                data['context_execution_request'] = {data['action'].split(' ')[2]: f"file_editor view {data['action'].split(' ')[2]}"}
            except Exception:
                logger.warning(f"Could not find context_execution_request in {data['action']}")
            return local_observation, cmd_mode, failure_observation
        return local_observation, cmd_mode, failure_observation

    def make_request(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make HTTP request to the service with retries for specific status codes."""
        max_attempts = 3
        attempt = 0
        wait_time = 0.5

        retry_status_codes = {429, 502, 503, 504}
        retry_exceptions = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException
        )

        # Log the request payload
        logger.info(f"Request payload: {json.dumps(payload, indent=2)}")

        while attempt < max_attempts:
            try:
                logger.info(f"Attempt {attempt + 1}/{max_attempts}: Making POST request to base url, 1st call : {self.config.base_url}")
                response = self.session.post(
                    f"{self.config.base_url}/jobs/v0/submit/",
                    json=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {self.config.auth_token}'
                    },
                    timeout=(10.0, self.config.http_timeout_agent_service)
                )

                logger.info(f"Response status code: {response.status_code}")
                logger.info(f"Response: {response.json()}")

                if response.status_code == 500:

                    retry_with_diff_request_id = response.json().get('retry_with_diff_request_id', False)
                    retry = response.json().get('retry', False)

                    if retry:
                        if attempt == max_attempts - 1:
                            return {
                                "error": True,
                                "error_message": response.json().get('detail') if 'detail' in response.json() else response.json()
                            }
                        attempt += 1
                        time.sleep(wait_time)
                        wait_time = min(wait_time * 1.5, 2.0)
                        continue

                    return {
                        "error": True,
                        "error_message": response.json().get('detail') if 'detail' in response.json() else response.json(),
                        "retry_with_diff_request_id": retry_with_diff_request_id,
                    }

                if response.status_code in retry_status_codes:
                    if attempt == max_attempts - 1:
                        return {
                            "error": True,
                            "error_message": f"Service unavailable (HTTP {response.status_code}) after {max_attempts} attempts",
                        }
                    attempt += 1
                    time.sleep(wait_time)
                    wait_time = min(wait_time * 1.5, 2.0)
                    continue
                response.raise_for_status()
                return response.json()

            except retry_exceptions as e:
                error_msg = f"Connection error on attempt {attempt + 1}: {str(e)}"
                logger.warning(
                    f"{error_msg}. {'Retrying' if attempt < max_attempts - 1 else 'Giving up'}"
                )

                if attempt == max_attempts - 1:
                    logger.error(f"Final attempt failed: {str(e)}")
                    self._refresh_session()
                    return {
                        "error": True,
                        "error_message": error_msg
                    }

                attempt += 1
                time.sleep(wait_time)
                wait_time = min(wait_time * 1.5, 2.0)
                continue

            except Exception as e:
                error_msg = f"Non-retryable error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._refresh_session() # FAILSAFE: refresh session to avoid connection corruption
                return {
                    "error": True,
                    "error_message": error_msg
                }

    def execute_lazy_request(self, request_id: str, hash: str, proxy_url: str = None, mock_llm = False) -> Optional[Dict[str, Any]]:
        """Make HTTP request to the proxy with retries for specific status codes."""
        max_attempts = 3
        attempt = 0
        wait_time = 0.5

        retry_status_codes = {429, 502, 503, 504}
        retry_exceptions = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException
        )
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.config.auth_token}'
        }
        if mock_llm is True or mock_llm == 'true':
            headers['X_EMERGENT_MOCK_LLM'] = 'true'

        while attempt < max_attempts:
            try:
                logger.info(f"Attempt {attempt + 1}/{max_attempts}: Making POST request to LLM Proxy, base url : {proxy_url}")
                response = requests.get(
                    f"{proxy_url}/execute/lazy?request_id={request_id}&hash={hash}",
                    headers=headers,
                    timeout=self.config.http_timeout_llm_proxy
                )

                logger.info(f"Response status code: {response.status_code}")

                try:
                    response_data = response.json()
                except Exception as e:
                    logger.warning(f"Failed to parse response JSON: {str(e)}; response text: {response.text}")
                    response_data = response.text

                if response.status_code == 409:
                    logger.info("Received 409 status code, starting 409 polling...")
                    return self.poller_409(request_id, hash, proxy_url, mock_llm)

                if response.status_code == 500:
                    return {
                        "error": True,
                        "error_message": response_data
                    }

                if response.status_code in retry_status_codes:
                    if attempt == max_attempts - 1:
                        return {
                            "error": True,
                            "error_message": f"Service unavailable (HTTP {response.status_code}) after {max_attempts} attempts",
                        }
                    attempt += 1
                    time.sleep(wait_time)
                    wait_time = min(wait_time * 1.5, 2.0)
                    continue

                response.raise_for_status()
                return response.json()

            except retry_exceptions as e:
                error_msg = f"Connection error on attempt {attempt + 1}: {str(e)}"
                logger.warning(
                    f"{error_msg}. {'Retrying' if attempt < max_attempts - 1 else 'Giving up'}"
                )

                if attempt == max_attempts - 1:
                    logger.error(f"Final attempt failed: {str(e)}")
                    self._refresh_session()
                    return {
                        "error": True,
                        "error_message": error_msg
                    }

                attempt += 1
                time.sleep(wait_time)
                wait_time = min(wait_time * 1.5, 2.0)
                continue


            except Exception as e:
                error_msg = f"Non-retryable error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._refresh_session() # FAILSAFE: refresh session to avoid connection corruption
                return {
                    "error": True,
                    "error_message": error_msg
                }

    def poller_409(self, request_id: str, hash: str, proxy_url: str = None, mock_llm = False) -> Optional[Dict[str, Any]]:
        """Poll the lazy request endpoint when receiving 409 status code."""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.config.auth_token}'
        }
        time.sleep(self.config.poll_timeout)
        for attempt in range(self.config.poll_409_max_attempts):
            try:
                logger.info(f"409 Polling attempt {attempt + 1}/{self.config.poll_409_max_attempts} for request_id: {request_id}")
                response = requests.get(
                    f"{proxy_url}/execute/lazy?request_id={request_id}&hash={hash}",
                    headers=headers,
                    timeout=self.config.http_timeout_llm_proxy
                )

                logger.info(f"409 Poll attempt {attempt + 1} Response status code: {response.status_code}")

                if response.status_code != 409:
                    if response.status_code in [200,201]:
                        logger.info(f"409 Poll successful on attempt {attempt + 1}, status: {response.status_code}")
                        return response.json()
                    else:
                        # Handle non-healthy status codes
                        logger.error(f"409 Poll received non-healthy status {response.status_code} on attempt {attempt + 1}")
                        return {
                            "error": True,
                            "error_message": f"Service returned {response.status_code}: {response.json().get('detail', response.text) if response.status_code != 500 else response.text}"
                        }

                if attempt < self.config.poll_409_max_attempts - 1:
                    logger.info(f"409 Poll attempt {attempt + 1} still receiving 409, waiting {self.config.poll_timeout} seconds...")
                    time.sleep(self.config.poll_timeout)

            except Exception as e:
                logger.error(f"409 Poll attempt {attempt + 1} failed with exception: {str(e)}")
                if attempt < self.config.poll_409_max_attempts - 1:
                    time.sleep(self.config.poll_timeout)

        logger.error(f"409 polling exhausted all {self.config.poll_409_max_attempts} attempts, still receiving 409")
        return {
            "error": True,
            "error_message": f"Request still returning 409 after {self.config.poll_409_max_attempts} polling attempts"
        }

    def get_lazy_response(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make HTTP request to the proxy with retries for specific status codes."""
        max_attempts = 3
        attempt = 0
        wait_time = 0.5

        retry_status_codes = {429, 502, 503, 504}
        retry_exceptions = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException
        )

        while attempt < max_attempts:
            try:
                logger.info(f"Attempt {attempt + 1}/{max_attempts}: Making post request to base url, 3rd call : {self.config.base_url}")
                response = self.session.post(
                    f"{self.config.base_url}/jobs/v0/response/lazy",
                    json=data,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {self.config.auth_token}',
                    },
                    timeout=(10.0, self.config.http_timeout_agent_service)
                )

                logger.info(f"Response status code: {response.status_code}")
                logger.info(f"Response: {response.json()}")

                if response.status_code == 500:
                    retry_with_diff_request_id = response.json().get('retry_with_diff_request_id', False)
                    retry = response.json().get('retry', False)
                    if retry:
                        if attempt == max_attempts - 1:
                            return {
                                "error": True,
                                "error_message": response.json().get('detail') if 'detail' in response.json() else response.json()
                            }
                        attempt += 1
                        time.sleep(wait_time)
                        wait_time = min(wait_time * 1.5, 2.0)
                        continue
                    return {
                        "error": True,
                        "error_message": response.json().get('detail') if 'detail' in response.json() else response.json(),
                        "retry_with_diff_request_id": retry_with_diff_request_id,
                    }

                if response.status_code in retry_status_codes:
                    if attempt == max_attempts - 1:
                        return {
                            "error": True,
                            "error_message": f"Service unavailable (HTTP {response.status_code}) after {max_attempts} attempts",
                        }
                    attempt += 1
                    time.sleep(wait_time)
                    wait_time = min(wait_time * 1.5, 2.0)
                    continue

                response.raise_for_status()
                return response.json()

            except retry_exceptions as e:
                error_msg = f"Connection error on attempt {attempt + 1}: {str(e)}"
                logger.warning(
                    f"{error_msg}. {'Retrying' if attempt < max_attempts - 1 else 'Giving up'}"
                )

                if attempt == max_attempts - 1:
                    logger.error(f"Final attempt failed: {str(e)}")
                    self._refresh_session()
                    return {
                        "error": True,
                        "error_message": error_msg
                    }

                attempt += 1
                time.sleep(wait_time)
                wait_time = min(wait_time * 1.5, 2.0)
                continue

            except Exception as e:
                error_msg = f"Non-retryable error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._refresh_session() # FAILSAFE: refresh session to avoid connection corruption
                return {
                    "error": True,
                    "error_message": error_msg
                }

    def handle_cmd_execution(
        self,
        job_id: str,
        command: str,
        hook_type: str = None,
    ) -> tuple[str, bool]:
        """Handle command execution."""
        result, success = self.execute_bash_command(job_id, command)

        # Special handling for git commands that return commit hashes
        if hook_type == 'init':
            return self.handle_init_hook(result, success)

        if hook_type == 'finish':
            return self.handle_finish_hook(job_id, result, success)

        if result:
            result = truncate(result, 80000)

        if not result:
            result = DEFAULT_SUCCESS_ENV_MESSAGE if success else DEFAULT_FAILURE_ENV_MESSAGE

        # Check for resource usage warnings and append if thresholds exceeded
        resource_warning = self.resource_monitor.check_thresholds(job_id, self.config)
        if resource_warning:
            result += resource_warning

        return result, success

    def handle_init_hook(self, result, success) -> tuple[str, bool]:
        # Extract just the commit hash if present
        lines = result.strip().split('\n')
        commit_hash = next((line.strip() for line in lines if len(line.strip()) == 40), '')
        return commit_hash, success

    def handle_finish_hook(self, job_id: str, result, success) -> tuple[str, bool]:
        self.execute_bash_command(job_id, "rm -rf model.patch")
        return result, success

    def execute_bash_command(self, job_id: str, command: str) -> tuple[str, bool]:
        """Execute a bash command and return its output."""
        if self.config.plugin_lib_path_to_export:
            command = f"export PATH={self.config.plugin_lib_path_to_export}:$PATH && {command}"
        command_file = Path(self.config.base_path) / job_id / "command.sh"
        command_file.parent.mkdir(parents=True, exist_ok=True)
        command_file.write_text(command)
        command_file.chmod(0o755)

        try:
            result = subprocess.run(
                str(command_file),
                shell=True,
                capture_output=True,
                timeout=2*60
            )
            stdout = result.stdout.decode()
            stderr = result.stderr.decode()

            logger.info(f"Return code: {result.returncode}, stdout: {stdout}, stderr: {stderr}")

            if result.returncode != 0 and stderr:
                return stderr, False
            if stdout:
                return stdout, result.returncode == 0
            if stderr:  # Add this check to return stderr even if returncode is 0
                return stderr, result.returncode == 0
            return "", result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            logger.error(f"Command execution timed out: {exc}")
            return "Command did not run in 2 minutes, Either try again or run the process in background", False
        except Exception as e:
            return str(e), False

    def add_error_to_trajectory(self, job_id: str, response: Dict[str, Any]) -> None:
        try:
            error_entry = {}
            error_entry['error'] = response.get('error')
            error_entry['error_message'] = response.get('error_message')
            error_entry['error_ts'] = error_entry['timestamp'] = datetime.now(timezone.utc).isoformat()
            error_entry['type'] = 'error'

            response = self.session.post(
                f"{self.config.base_url}/trajectories/v0/error",
                json={
                    "job_id": job_id,
                    "payload": error_entry
                },
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self.config.auth_token}'
                },
                timeout=self.config.http_timeout_agent_service
            )
            response.raise_for_status()
            logger.info(f"Successfully added error to trajectory for job_id: {job_id}")
        except Exception as e:
            logger.error(f"Failed to add error to trajectory: {str(e)}", exc_info=True)
            # Don't raise the exception - we want to continue even if API call fails

    def break_loop_on_error(self, response: Dict[str, Any], job_id: str) -> bool:
        if response and response.get('error'):
            self.add_error_to_trajectory(job_id, response)
            logger.warning(f"Breaking loop on error: {response.get('error_message')}")
            return True
        return False

    @staticmethod
    def transform_payload_for_agent_service(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Transform input payload into agent-service format."""
        transformed_payload = payload.copy()
        task_message = payload['payload']['task']
        is_resume = bool(payload.get('resume'))

        # Initialize task list
        transformed_payload['payload']['task'] = []
        transformed_payload['payload']['ato'] = True

        # Case 1: Fresh start (no id)
        if not payload.get('id'):
            transformed_payload['payload']['task'] = [
                {
                    'message': task_message,
                    'triggered_by': 'system'
                }
            ]
            return transformed_payload

        # Case 3: Normal resume flow
        if is_resume:
            transformed_payload['payload']['task'] = [
                {
                    'message': task_message,
                    'triggered_by': 'human'
                }
            ]
            return transformed_payload

        # Case 4: Regular agent response
        transformed_payload['payload']['task'] = [
            {
                'message': task_message,
                'triggered_by': 'system'
            }
        ]
        return transformed_payload

    def _execute_git_command(self, work_space_dir: str, command: str, log_prefix: str = "GIT", job_id: Optional[str] = None) -> Tuple[str, bool]:
        """Execute a git command in the specified directory and return its output"""
        full_command = f"cd {work_space_dir} && {command}"
        logger.info(f"[{log_prefix}] Executing command: {full_command}")

        # Check if we can use execute_bash_command
        return self.execute_bash_command(job_id, full_command)

    def git_commit(self, work_space_dir: Optional[str] = None, request_id: Optional[str] = None, job_id=None) -> Optional[str]:
        """Get the latest commit ID from git repository. Also stages all changes and creates a commit if request_id is provided."""
        try:

            is_git_repo_cmd = "git rev-parse --is-inside-work-tree 2>/dev/null"
            output, success = self._execute_git_command(work_space_dir, is_git_repo_cmd, job_id=job_id)

            if not success:
                logger.error(f"[GIT] Command error output: {output}")
                return None

            # Stage all changes EXCEPT common package files and generated files
            stage_cmd = f"git add -A {GIT_STAGE_EXCLUSIONS}"
            stage_output, stage_success = self._execute_git_command(work_space_dir, stage_cmd, job_id=job_id)

            if not stage_success:
                logger.error(f"[GIT] Failed to stage changes: {stage_output}")
            else:
                logger.info("[GIT] Successfully staged changes")

            # Commit changes if there are any
            commit_msg = f"auto-commit for {request_id}"
            commit_cmd = f"git diff --staged --quiet || git commit -m '{commit_msg}'"
            commit_output, commit_success = self._execute_git_command(work_space_dir, commit_cmd, job_id=job_id)

            if commit_success:
                logger.info(f"[GIT] Successfully created commit with message: {commit_msg}")
            else:
                logger.error(f"[GIT] No new changes to commit or commit failed: {commit_output}")

            # Get the commit ID
            get_commit_id_cmd = "git rev-parse HEAD"
            commit_id_output, commit_id_success = self._execute_git_command(work_space_dir, get_commit_id_cmd, job_id=job_id)

            if commit_id_success:
                commit_id = commit_id_output.strip()
                logger.info(f"[GIT] Successfully retrieved latest commit ID: {commit_id}")
                return commit_id
            else:
                logger.error(f"[GIT] Failed to get commit ID: {commit_id_output}")

        except subprocess.SubprocessError as e:
            logger.error(f"[GIT] Subprocess error retrieving commit ID: {str(e)}")
        except Exception as e:
            logger.error(f"[GIT] Unexpected error retrieving commit ID: {str(e)}", exc_info=True)

        return None

    def add_image_list_to_payload(self, image_list, transformed_payload):
        logger.info(f"Adding image_list in payload.base64_image_list. Length: {len(image_list)}")
        transformed_payload['payload']['base64_image_list'] = []

        transformed_payload['payload']['base64_image_list'].extend([
            {
                "mime_type":'image/jpeg',
                "img_base64": img_base64
            }
            for img_base64 in image_list
        ])
        logger.info(f"Created image_list in payload.base64_image_list. Length: {len(transformed_payload['payload']['base64_image_list'])}")

    def add_screenshots_to_payload(self, screenshot_images, transformed_payload):
        """Add screenshot images to the payload.

        Args:
            screenshot_images: List of screenshot image data dictionaries
            transformed_payload: The payload to add the screenshots to
        """
        # Define mime type mapping
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp'
        }
        # Initialize the list if it doesn't exist
        if 'base64_image_list' not in transformed_payload['payload']:
            transformed_payload['payload']['base64_image_list'] = []

        transformed_payload['payload']['base64_image_list'].extend([
            {
                "mime_type": mime_types.get(img_data['extension'], 'image/jpeg'),
                "img_base64": img_data['base64']
            }
            for img_data in screenshot_images
        ])

    def _make_agent_request(
        self,
        transformed_payload: Dict[str, Any],
        lazy_llm_call_enabled: bool,
        proxy_url: Optional[str] = None,
        mock_llm: bool = False
    ) -> Dict[str, Any]:

        logger.info("Executing agent request...")

        try:
            # Step 1: Configure execution mode based on lazy call setting
            execution_mode = (
                CallExecutionMode.ACCEPT_EXECUTION_REQUEST.value
                if lazy_llm_call_enabled
                else CallExecutionMode.EXECUTE_IN_SYNC.value
            )
            transformed_payload['call_execution_mode'] = execution_mode

            # Step 2: Submit initial request
            logger.info(f"Submitting initial request with execution mode: {execution_mode}")
            initial_response = self.make_request(transformed_payload)

            # Step 3: Handle lazy execution if enabled and hash is available
            if lazy_llm_call_enabled:
                return self._handle_lazy_execution(
                    initial_response=initial_response,
                    transformed_payload=transformed_payload,
                    proxy_url=proxy_url,
                    mock_llm=mock_llm
                )

            # Step 4: Return synchronous response
            logger.info("Returning synchronous execution response")
            return initial_response

        except Exception as e:
            logger.error(f"Failed to execute agent request: {str(e)}", exc_info=True)
            raise

    def _handle_lazy_execution(
        self,
        initial_response: Dict[str, Any],
        transformed_payload: Dict[str, Any],
        proxy_url: Optional[str],
        mock_llm: bool
    ) -> Dict[str, Any]:

        request_hash = initial_response.get('hash')
        request_id = initial_response.get('request_id')

        if not (request_hash and request_id):
            logger.warning(
                f"Missing hash ({request_hash}) or request_id ({request_id}) "
                f"for lazy execution, returning initial response"
            )
            return initial_response

        logger.info(f"Executing lazy request with hash: {request_hash}, request_id: {request_id}")

        # Execute the lazy request
        lazy_response = self.execute_lazy_request(
            request_id=request_id,
            hash=request_hash,
            proxy_url=proxy_url,
            mock_llm=mock_llm
        )

        # Check if we got a valid hash back for cached execution
        cached_hash = lazy_response.get('hash') if lazy_response else None

        if cached_hash:
            logger.info(f"Using cached LLM response with hash: {cached_hash}")
            # Update payload for cached execution
            transformed_payload['payload']['hash'] = cached_hash
            transformed_payload['call_execution_mode'] = CallExecutionMode.EXECUTION_WITH_CACHED_LLM_RESPONSE.value

            # Get the final response with cached LLM data
            return self.get_lazy_response(transformed_payload)
        else:
            logger.info(f"No cached hash found in lazy response: {lazy_response}")
            return lazy_response

    def update_latest_job_details(self, job_id: str, initial_commit_id: Optional[str], work_space_dir: Optional[str]) -> None:
        latest_job_file = Path(self.config.base_path) / "latest_job_details.json"

        latest_job_details = {
            "job_id": job_id,
            "initial_commit_id": initial_commit_id,
            "work_space_dir": work_space_dir
        }

        logger.info(f"latest_job_details: {latest_job_details}")
        latest_job_file.write_text(json.dumps(latest_job_details, indent=2))
