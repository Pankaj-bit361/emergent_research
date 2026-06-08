"""Todo management tools for MCP.

This module provides todo list functionality with read/write operations.
Outputs formatted markdown for better readability.
Persists todos to disk for survival across restarts.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


# ============================================================================
# Data Models
# ============================================================================

class TodoItem(BaseModel):
    """Individual todo item model."""
    content: str = Field(description="Brief description of the task")
    status: str = Field(description="Current status of the task: pending, in_progress, completed, cancelled")


class TodoWriteResult(BaseModel):
    """Result of a todo write operation."""
    success: bool
    todo_count: int = Field(description="Number of incomplete todos")
    output: str = Field(description="Markdown representation of todos")

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


class TodoReadResult(BaseModel):
    """Result of a todo read operation."""
    success: bool
    todo_count: int = Field(description="Number of incomplete todos")
    todos: List[TodoItem]
    output: str = Field(description="Markdown representation of todos")

    def __str__(self) -> str:
        """Return text representation for upper methods."""
        return self.output


# ============================================================================
# Storage and Persistence
# ============================================================================

TODOS_FILE_PATH = os.getenv('TODOS_FILE_PATH', '/app/.emergent/emergent_todos.json')

def ensure_todos_directory():
    """Ensure the todos directory exists. Called lazily when needed."""
    global TODOS_FILE_PATH
    try:
        Path(TODOS_FILE_PATH).parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        # If we can't create the directory (e.g., in tests or read-only filesystem),
        # try to use a temp directory instead
        import tempfile
        temp_dir = tempfile.gettempdir()
        TODOS_FILE_PATH = os.path.join(temp_dir, 'emergent_todos.json')
        Path(TODOS_FILE_PATH).parent.mkdir(parents=True, exist_ok=True)

# Module-level storage for todos (loaded from disk on import)
_todo_list: List[TodoItem] = []


# ============================================================================
# Persistence Functions
# ============================================================================

def save_todos_to_file(todos: List[TodoItem]) -> bool:
    """
    Save todos to persistent storage.

    Args:
        todos: List of TodoItem objects to save

    Returns:
        True if save was successful, False otherwise
    """
    try:
        # Ensure directory exists before saving
        ensure_todos_directory()

        # Convert TodoItems to dicts for JSON serialization
        todo_dicts = [todo.model_dump() for todo in todos]

        # Write to file with pretty formatting
        with open(TODOS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(todo_dicts, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"Error saving todos to {TODOS_FILE_PATH}: {e}")
        return False


def load_todos_from_file() -> List[TodoItem]:
    """
    Load todos from persistent storage.

    Returns:
        List of TodoItem objects loaded from file, or empty list if file doesn't exist
    """
    try:
        # Ensure directory exists before checking file
        ensure_todos_directory()

        if not Path(TODOS_FILE_PATH).exists():
            return []

        with open(TODOS_FILE_PATH, 'r', encoding='utf-8') as f:
            todo_dicts = json.load(f)

        # Convert dicts back to TodoItem objects
        todos = []
        for todo_dict in todo_dicts:
            try:
                todos.append(TodoItem(**todo_dict))
            except Exception as e:
                print(f"Skipping invalid todo: {todo_dict}, error: {e}")

        return todos
    except json.JSONDecodeError as e:
        print(f"Error parsing todos file {TODOS_FILE_PATH}: {e}")
        return []
    except Exception as e:
        print(f"Error loading todos from {TODOS_FILE_PATH}: {e}")
        return []


# Load todos on module import
_todo_list = load_todos_from_file()


# ============================================================================
# Helper Functions
# ============================================================================

def format_todos_as_markdown(todos: List[TodoItem]) -> str:
    """
    Format todos as a markdown list.

    Args:
        todos: List of TodoItem objects

    Returns:
        Formatted markdown string
    """
    if not todos:
        return "*No todos currently in the list*"

    lines = ["## Todo List\n"]

    # Group by status
    status_groups = {
        "in_progress": [],
        "pending": [],
        "completed": [],
        "cancelled": []
    }

    for todo in todos:
        status_groups.get(todo.status, status_groups["pending"]).append(todo)

    # Format in progress items first
    if status_groups["in_progress"]:
        lines.append("### In Progress")
        for todo in status_groups["in_progress"]:
            lines.append(f"- [ ] {todo.content}")
        lines.append("")

    # Then pending items
    if status_groups["pending"]:
        lines.append("### Pending")
        for todo in status_groups["pending"]:
            lines.append(f"- [ ] {todo.content}")
        lines.append("")

    # Then completed items
    if status_groups["completed"]:
        lines.append("### Completed")
        for todo in status_groups["completed"]:
            lines.append(f"- [x] ~~{todo.content}~~")
        lines.append("")

    # Finally cancelled items
    if status_groups["cancelled"]:
        lines.append("### Cancelled")
        for todo in status_groups["cancelled"]:
            lines.append(f"- [x] ~~{todo.content}~~")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Tool Implementations
# ============================================================================

def write_todos(todo_items: List[TodoItem]) -> TodoWriteResult:
    """
    Update the todo list with new items and persist to disk.

    Args:
        todo_items: List of TodoItem objects with content and status

    Returns:
        TodoWriteResult with success status and markdown formatted output
    """
    global _todo_list

    try:
        # Ensure all items are TodoItem objects
        if not all(isinstance(item, TodoItem) for item in todo_items):
            raise TypeError("All items must be TodoItem objects")

        # Update the global todo list
        _todo_list = todo_items.copy()

        # Save to persistent storage
        save_success = save_todos_to_file(_todo_list)
        if not save_success:
            # Log warning but don't fail the operation
            print(f"Warning: Could not persist todos to {TODOS_FILE_PATH}")

        # Count incomplete todos
        incomplete_count = sum(
            1 for todo in _todo_list
            if todo.status not in ["completed", "cancelled"]
        )

        # Create markdown output
        markdown_output = format_todos_as_markdown(_todo_list)

        return TodoWriteResult(
            success=True,
            todo_count=incomplete_count,
            output=markdown_output
        )

    except Exception as e:
        return TodoWriteResult(
            success=False,
            todo_count=0,
            output=f"Error writing todos: {str(e)}"
        )


def read_todos() -> TodoReadResult:
    """
    Read the current todo list from memory (loaded from disk on import).

    Returns:
        TodoReadResult with current todos and markdown formatted output
    """
    global _todo_list

    try:
        # Count incomplete todos
        incomplete_count = sum(
            1 for todo in _todo_list
            if todo.status not in ["completed", "cancelled"]
        )

        # Create markdown output
        markdown_output = format_todos_as_markdown(_todo_list)

        # Add persistence info to output
        if _todo_list:
            markdown_output += f"\n\n_Persisted to: {TODOS_FILE_PATH}_"

        return TodoReadResult(
            success=True,
            todo_count=incomplete_count,
            todos=_todo_list,
            output=markdown_output
        )

    except Exception as e:
        return TodoReadResult(
            success=False,
            todo_count=0,
            todos=[],
            output=f"Error reading todos: {str(e)}"
        )