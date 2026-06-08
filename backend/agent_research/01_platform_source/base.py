"""Base classes and types for the agent tool."""
from dataclasses import dataclass
from typing import Optional

@dataclass
class ToolResult:
    """Result from a tool operation."""
    output: Optional[str] = None
    error: Optional[str] = None
    system: Optional[str] = None

@dataclass
class CLIResult:
    """Result specifically for CLI operations."""
    output: Optional[str] = None
    error: Optional[str] = None

class ToolError(Exception):
    """Custom error class for tool operations."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message) 