"""System resource monitoring tools for pod environments."""
import json
import subprocess
from typing import Tuple
from plugins.tools.agent.logger import logger

# Bash commands for resource checks
MEMORY_CHECK_CMD = '''if [ -f /sys/fs/cgroup/memory.max ]; then
    max=$(cat /sys/fs/cgroup/memory.max)
    current=$(cat /sys/fs/cgroup/memory.current)
    inactive=$(awk '/^inactive_file/{print $2}' /sys/fs/cgroup/memory.stat)
    used=$((current - inactive))
    awk -v u=$used -v m=$max 'BEGIN{pct=u*100/m; printf "%.1f|%.2fGB/%.2fGB (%.1f%%)", pct, u/1024/1024/1024, m/1024/1024/1024, pct}'
else
    echo "0.0|Memory: N/A"
fi'''

CPU_CHECK_CMD = '''if [ -f /sys/fs/cgroup/cpu.max ]; then
    quota=$(cut -d' ' -f1 /sys/fs/cgroup/cpu.max)
    period=$(cut -d' ' -f2 /sys/fs/cgroup/cpu.max)
    cores=$(awk -v q=$quota -v p=$period 'BEGIN{printf "%.2f", q/p}')
    load=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)
    pct=$(awk -v l=$load -v c=$cores 'BEGIN{printf "%.1f", (l/c)*100}')
    echo "${pct}|load ${load}/${cores} cores (1-min avg)"
else
    echo "0.0|CPU: N/A"
fi'''

STORAGE_CHECK_CMD_TEMPLATE = '''if [ -d "{path}" ]; then
    df -h "{path}" | awk 'NR==2{{pct=$5; gsub(/%/,"",pct); printf "%.0f|%s/%s (%s)", pct, $3, $2, $5}}'
else
    echo "0.0|Disk: N/A"
fi'''


# simple internal function to execute bash 
# NOTE: not using mcp_execute_bash as it does too many checks and validations
def _execute_bash(command: str) -> Tuple[str, bool]:
    """Execute bash command and return result."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=10
        )
        stdout = result.stdout.decode()
        stderr = result.stderr.decode()

        if result.returncode != 0 and stderr:
            return stderr, False
        if stdout:
            return stdout, result.returncode == 0
        if stderr:
            return stderr, result.returncode == 0
        return "", result.returncode == 0
    except Exception as e:
        return str(e), False


def _parse_resource_output(command: str) -> Tuple[float, str]:
    """Execute command and parse percentage|details format."""
    try:
        result, success = _execute_bash(command)
        if success and result.strip():
            parts = result.strip().split('|', 1)
            if len(parts) == 2:
                return float(parts[0]), parts[1]
    except Exception:
        pass
    return 0.0, ""


def get_memory_usage() -> Tuple[float, str]:
    """Get memory usage percentage and display message."""
    return _parse_resource_output(MEMORY_CHECK_CMD)


def get_cpu_usage() -> Tuple[float, str]:
    """Get CPU usage percentage and display message."""
    return _parse_resource_output(CPU_CHECK_CMD)


def get_storage_usage(path: str = '/app') -> Tuple[float, str]:
    """Get storage usage percentage and display message."""
    cmd = STORAGE_CHECK_CMD_TEMPLATE.format(path=path)
    return _parse_resource_output(cmd)


def get_pod_resources() -> dict:
    """Get current pod resource usage.

    Returns:
        dict with structure:
        {
            'memory': {'percentage': 85.0, 'details': '6.8GB/8GB (85%)'},
            'cpu': {'percentage': 90.0, 'details': 'load 1.8/2.00 cores (1-min avg)'},
            'storage': {'percentage': 30.0, 'details': '3G/10G (30%)'}
        }
    """
    memory_pct, memory_output = get_memory_usage()
    cpu_pct, cpu_output = get_cpu_usage()
    storage_pct, storage_output = get_storage_usage()

    logger.info(f"Resource check: memory={memory_pct}%, cpu={cpu_pct}%, storage={storage_pct}%")
    

    result = {
        'memory': {
            'percentage': memory_pct,
            'details': memory_output
        },
        'cpu': {
            'percentage': cpu_pct,
            'details': cpu_output
        },
        'storage': {
            'percentage': storage_pct,
            'details': storage_output
        }
    }

    output = json.dumps(result)
    result['output'] = output

    return result
