import base64
import json
import shlex
import binascii
import logging

logger = logging.getLogger(__name__)

def process_str_replace(traj_str):
    args = shlex.split(traj_str)

    # Initialize variables to store the encoded strings
    old_str_encoded = None
    new_str_encoded = None
    
    # Find --old-str and --new-str in the arguments
    for i, arg in enumerate(args):
        if arg == '--old-str' and i + 1 < len(args):
            old_str_encoded = args[i + 1] if args[i + 1].strip() else ""
        elif arg == '--new-str' and i + 1 < len(args):
            new_str_encoded = args[i + 1] if args[i + 1].strip() else ""

    # Check if either string was not found
    if old_str_encoded is None or new_str_encoded is None:
        return traj_str

    # Decode the base64 strings
    try:
        old_str_decoded = base64.b64decode(old_str_encoded).decode('utf-8') if old_str_encoded else ""
        new_str_decoded = base64.b64decode(new_str_encoded).decode('utf-8') if new_str_encoded else ""
    except (binascii.Error, UnicodeDecodeError, Exception) as e:
        # If there's any decoding error, return the original string
        return traj_str

    # Create new command with decoded strings
    decoded_traj_str = []
    i = 0
    while i < len(args):
        if args[i] == '--old-str' and old_str_decoded:
            decoded_traj_str.extend(['--old-str', old_str_decoded])
            i += 2
        elif args[i] == '--new-str' and new_str_decoded:
            decoded_traj_str.extend(['--new-str', new_str_decoded])
            i += 2
        else:
            decoded_traj_str.append(args[i])
            i += 1

    return repr(' '.join(decoded_traj_str))


def process_create(traj_str):
    args = shlex.split(traj_str)

    # Initialize variable to store the encoded string
    file_text_encoded = None

    # Find --file-text in the arguments
    for i, arg in enumerate(args):
        if arg == '--file-text' and i + 1 < len(args):
            file_text_encoded = args[i + 1] if args[i + 1].strip() else ""
            break

    # Check if file-text was found
    if file_text_encoded is None or file_text_encoded == "":
        return traj_str

    # Decode the base64 string
    try:
        file_text_decoded = base64.b64decode(file_text_encoded).decode('utf-8') if file_text_encoded else ""
    except (binascii.Error, UnicodeDecodeError, Exception) as e:
        # If there's any decoding error, return the original string
        return traj_str

    # Create new command with decoded string
    decoded_traj_str = []
    i = 0
    while i < len(args):
        if args[i] == '--file-text':
            decoded_traj_str.extend(['--file-text', file_text_decoded])
            i += 2
        else:
            decoded_traj_str.append(args[i])
            i += 1
    return repr(' '.join(decoded_traj_str))

def process_bulk_file_writer(traj_str: str) -> str:
    logger.info("process_bulk_file_writer - Processing bulk file writer: %s", traj_str)
    def _find_matching_bracket(s: str, start: int) -> int:
        depth = 0
        for idx in range(start, len(s)):
            if s[idx] == '[':
                depth += 1
            elif s[idx] == ']':
                depth -= 1
                if depth == 0:
                    return idx
        raise ValueError("Unmatched '[' in string")
    first_bracket = traj_str.find('[')
    last_bracket = traj_str.rindex(']')
    
    if first_bracket == -1 or last_bracket == -1:
        raise ValueError("Invalid input format: missing brackets")
    
    try:
        # Extract the first JSON array (paths) with proper nested-bracket matching
        paths_start = first_bracket
        paths_end = _find_matching_bracket(traj_str, paths_start)
        paths_str = traj_str[paths_start:paths_end+1]

        # Extract the second JSON array (content) after the paths array
        content_start = traj_str.find('[', paths_end+1)
        content_end = _find_matching_bracket(traj_str, content_start)
        content_str = traj_str[content_start:content_end+1]
        
        logger.info("process_bulk_file_writer - Paths: %s, Content: %s", paths_str, content_str)
        content_array = json.loads(content_str)
        if not content_array or not isinstance(content_array, list):
            raise ValueError("Content array is empty or invalid")
            
        decoded_content = [base64.b64decode(content).decode('utf-8') for content in content_array]
        
        return f'bulk_file_creator {paths_str} {decoded_content}'
        
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format")
    except base64.binascii.Error:
        raise ValueError("Invalid base64 encoding")
    except UnicodeDecodeError:
        raise ValueError("Unable to decode content as UTF-8")  

def process_batch_tool(traj_str):
    args = shlex.split(traj_str)
    decoded_invocations = None
    for i, arg in enumerate(args):
        if arg == "--invocations":
            decoded_invocations = base64.b64decode(args[i+1]).decode('utf-8')
            break
    if decoded_invocations is None:
        return traj_str
    invocations = json.loads(decoded_invocations)
    actions=[]
    for invocation in invocations:
        if "action" in invocation:
            actions.append(process_trajectory_string(invocation["action"]))
    actions_str ="batch_tool --invocations " + str(actions)
    return actions_str

def process_trajectory_string(traj_str):
    try:
        if "file_editor str_replace" in traj_str:
            return process_str_replace(traj_str)
        elif "file_editor create" in traj_str:
            return process_create(traj_str)
        elif "bulk_file_creator" in traj_str:
            return process_bulk_file_writer(traj_str)
        elif "batch_tool" in traj_str:
            return process_batch_tool(traj_str)
        return traj_str
    except Exception as e:
        logger.error(f"Error processing trajectory string: {e}")
        # If any unexpected error occurs, return the original string
        return traj_str or ""