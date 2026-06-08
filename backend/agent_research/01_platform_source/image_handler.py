import base64
import os
from pathlib import Path
from .config import AgentConfig


def image_to_base64(filepath):
    try:
        with open(filepath, "rb") as image_file:
            # Read the image file as binary data
            binary_data = image_file.read()
            # Convert binary data to Base64 string
            base64_string = base64.b64encode(binary_data).decode("utf-8")
            return base64_string
    except FileNotFoundError:
        print("File not found. Please check the file path.")
    except Exception as e:
        return print(f"An error occurred: {e}")
    finally:
        os.remove(filepath)
    return None


def get_screenshots(max_images: int = None, name_filter: str = None):
    """
    Get screenshots from the screenshots directory with configurable filters.
    
    Args:
        max_images (int, optional): Maximum number of most recent images to return
        name_filter (str, optional): String that must be present in filename
        
    Returns:
        list: List of dictionaries containing base64 encoded images and their extensions
    """
    try:
        config = AgentConfig.from_env()
        screenshots_dir = Path(config.emergent_base_path) / '.screenshots'
        base64_images = []
        # Common image file extensions
        valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

        if max_images is not None and max_images <= 0:
            return []
        
        if os.path.exists(screenshots_dir):
            # Get all valid image files with their creation times
            image_files = []
            for filename in os.listdir(screenshots_dir):
                file_path = os.path.join(screenshots_dir, filename)
                extension = os.path.splitext(filename)[1].lower()
                
                # Apply filters
                if not os.path.isfile(file_path) or extension not in valid_extensions:
                    continue
                    
                # Apply name filter if specified
                if name_filter and name_filter.lower() not in filename.lower():
                    continue
                
                # Get file creation time for sorting
                creation_time = os.path.getctime(file_path)
                image_files.append((file_path, filename, extension, creation_time))
            
            # Sort by creation time (newest first)
            image_files.sort(key=lambda x: x[3], reverse=True)
                        # Handle empty image_files case
            if not image_files:
                return []
            # Apply max_images limit if specified
            if max_images is not None:
                if max_images > len(image_files):
                    max_images = len(image_files)
                
                image_files = image_files[:max_images]
            # Convert filtered images to base64
            for file_path, filename, extension, _ in image_files:
                base64_string = image_to_base64(file_path)
                if base64_string:  # Only append if conversion was successful
                    base64_images.append({
                        'base64': base64_string,
                        'extension': extension
                    })
        
        return base64_images
    except Exception as e:
        print(f"Error while getting screenshots: {e}")
        return []

def delete_screenshots():
    try:
        config = AgentConfig.from_env()
        screenshots_dir = Path(config.emergent_base_path) / '.screenshots'
        # Check if directory exists
        if os.path.exists(screenshots_dir):
            # Iterate through all files in the directory
            for filename in os.listdir(screenshots_dir):
                file_path = os.path.join(screenshots_dir, filename)
                # Check if it's a file (not a subdirectory)
                if os.path.isfile(file_path):
                    os.remove(file_path)
    except Exception as e:
        print(f"Error while deleting screenshots: {e}")

