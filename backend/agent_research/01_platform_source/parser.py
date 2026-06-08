"""Command parser for file_editor commands."""
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

class FileEditorParser:
    """Parser for file_editor commands."""

    @staticmethod
    def parse_command(command: str) -> Dict[str, Any]:
        """Parse a file_editor command string into method arguments."""
        parser = argparse.ArgumentParser(description='File Editor Command Parser')
        parser.add_argument('command', choices=['str_replace', 'view', 'create', 'insert'])
        parser.add_argument('path', type=str)

        # Optional arguments matching __call__ method parameters
        parser.add_argument('--file-text', type=str, help='Content for file creation')
        parser.add_argument('--view-range-start', type=int, help='Start line for view range')
        parser.add_argument('--view-range-end', type=int, help='End line for view range')
        parser.add_argument('--old-str', type=str, help='String to replace')
        parser.add_argument('--new-str', type=str, help='Replacement string')
        parser.add_argument('--insert-line', type=int, help='Line number for insertion')
        parser.add_argument('--status', action='store_true', help='Get supervisor status after operation')
        parser.add_argument('--capture-logs-frontend', action='store_true', help='Capture frontend debug logs')
        parser.add_argument('--capture-logs-backend', action='store_true', help='Capture backend debug logs')

        # Split command string but preserve quoted strings
        import shlex
        args = parser.parse_args(shlex.split(command.replace('file_editor ', '', 1)))

        # Convert to dictionary
        result = {
            'command': args.command,
            'path': Path(args.path)
        }

        # Add optional arguments if present
        if args.file_text is not None:
            result['file_text'] = args.file_text
        if args.view_range_start is not None and args.view_range_end is not None:
            result['view_range'] = [args.view_range_start, args.view_range_end]
        if args.old_str is not None:
            result['old_str'] = args.old_str
        if args.new_str is not None:
            result['new_str'] = args.new_str
        if args.insert_line is not None:
            result['insert_line'] = args.insert_line
        if args.status:
            result['status'] = True
        if args.capture_logs_frontend:
            result['capture_logs_frontend'] = True
        if args.capture_logs_backend:
            result['capture_logs_backend'] = True

        return result