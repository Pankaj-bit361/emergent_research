"""Shared logger configuration for agent tools."""

import logging
import sys
from pathlib import Path

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
    # Create simple file handler
    file_handler = logging.FileHandler("/var/log/e1_agent.log")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except:
    print("Could not create log file")

# Setup single console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)
