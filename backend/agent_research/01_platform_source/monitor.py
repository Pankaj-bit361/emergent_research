# monitor.py
import logging
import time
from datetime import datetime

import requests
import typer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["PUT", "GET", "POST"]  # include PUT so it will retry on PUT failures
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def is_e1_agent_running(server_url: str = "http://localhost:8010"):
    """Check if e1_agent is running using the status API endpoint"""
    try:
        status_url = f"{server_url}/status"
        response = session.get(status_url, timeout=5, verify=False)
        if response.status_code == 200:
            return response.json().get("is_task_running", False)
        logger.error(f"Failed to get status: {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Error checking e1_agent status: {e}")
        return False

def send_heartbeat(base_url: str, entity_id: str, status: str):
    """Send heartbeat to server with retry mechanism"""
    try:
        payload = {
            'entity_id': entity_id,
            'status': status,
            'timestamp': datetime.utcnow().isoformat()
        }

        heartbeat_url = f"{base_url}/heartbeat/v0/"
        logger.info(f"Sending heartbeat to: {heartbeat_url}")

        response = session.put(heartbeat_url, json=payload, timeout=5, verify=False)
        if response.status_code != 200:
            logger.error(f"Failed to send heartbeat: {response.status_code}")
        else:
            logger.info(f"Heartbeat sent: {status}")
            return True

    except Exception as e:
        logger.error(f"Error sending heartbeat: {e}")
    return False

def cli(
    entity_id: str = typer.Argument(..., help="Entity ID to monitor"),
    base_url: str = typer.Argument(..., help="Base URL for heartbeat"),
    interval: int = typer.Option(5, "--interval", "-i", help="Heartbeat interval in seconds"),
    heartbeat_interval_minutes: int = typer.Option(5, "--heartbeat-interval", "-h", help="Heartbeat interval in minutes")
):
    """Monitor e1_agent process and send heartbeats"""
    logger.info(f"Starting monitor for entity: {entity_id}")
    logger.info(f"Base URL: {base_url}")
    logger.info(f"Interval: {interval}")
    logger.info(f"Heartbeat interval: {heartbeat_interval_minutes} minutes")

    last_status = None  # Track the last status
    last_heartbeat_time = time.time()  # Track the last heartbeat time
    heartbeat_interval_seconds = heartbeat_interval_minutes * 60

    while True:
        try:
            current_status = "running" if is_e1_agent_running() else "stopped"
            current_time = time.time()

            # Send heartbeat if status has changed, it's the first check, or heartbeat interval has passed
            should_send_heartbeat = (
                current_status != last_status or
                (current_time - last_heartbeat_time) >= heartbeat_interval_seconds
            )

            if should_send_heartbeat:
                if current_status != last_status:
                    logger.info(f"Status changed from {last_status} to {current_status}")
                else:
                    logger.info(f"Sending periodic heartbeat after {heartbeat_interval_minutes} minutes")

                if send_heartbeat(base_url, entity_id, current_status):
                    last_status = current_status
                    last_heartbeat_time = current_time
            else:
                logger.debug(f"Status unchanged: {current_status}")

        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")

        time.sleep(interval)

def main():
    typer.run(cli)

if __name__ == "__main__":
    main()