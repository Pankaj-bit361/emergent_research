"""Configuration management for the agent tool."""
import os
from dataclasses import dataclass

@dataclass
class AgentConfig:
    """Configuration for the agent tool."""
    base_url: str = "http://localhost:8009"
    auth_token: str = ""

    base_path: str = os.path.expanduser("~/runs")
    max_retries: int = 5
    emergent_base_path: str = os.path.expanduser("~/.emergent")
    plugin_lib_path_to_export: str = ''
    is_mock_setup: bool = False

    http_timeout: int = 1320 # 22 minutes
    http_timeout_llm_proxy: int = 9 * 60 # 9 minutes 
    http_timeout_agent_service: int = 500 
    max_iterations: int = 10000
    
    # 409 polling configuration
    poll_409_max_attempts: int = 11
    poll_timeout: int = 5*60  # timeout for each poll request
    
    # Resource monitoring thresholds (percentages)
    memory_threshold: float = 85.0  # % memory usage
    cpu_threshold: float = 80.0     # % CPU load
    storage_threshold: float = 90.0  # % disk usage

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Create configuration from environment variables."""
        config = cls(
            base_url=os.getenv("EMERGENT_BASE_URL", cls.base_url),
            auth_token=os.getenv("EMERGENT_AUTH_TOKEN", cls.auth_token),
            base_path=os.path.expanduser(os.getenv("EMERGENT_BASE_PATH", cls.base_path)),
            max_retries=int(os.getenv("EMERGENT_MAX_RETRIES", cls.max_retries)),
            http_timeout=int(os.getenv("EMERGENT_HTTP_TIMEOUT", cls.http_timeout)),
            http_timeout_agent_service=cls.http_timeout_agent_service,
            http_timeout_llm_proxy=cls.http_timeout_llm_proxy,
            max_iterations=int(os.getenv("EMERGENT_MAX_ITERATIONS", cls.max_iterations)),
            emergent_base_path = cls.emergent_base_path,
        )
        
        # Create base_path directory if it doesn't exist
        os.makedirs(config.base_path, exist_ok=True)
        
        return config

