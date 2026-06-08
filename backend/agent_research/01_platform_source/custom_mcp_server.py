"""Simplified MCP Server using direct tool registration.

This module demonstrates the FastMCP-aligned approach:
- No adapter pattern needed
- Direct import of mcp instance with registered tools
- Simplified server management
"""

import uvicorn
import sys
import json
import asyncio
import logging
import signal
import shutil

from fastmcp import Client, FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,  # This is the default, but shown here for clarity
)
logger = logging.getLogger(__name__)


def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Received shutdown signal, shutting down gracefully...")
    sys.exit(0)

def prepare_mcp_config(mcp_config: dict) -> dict:
    valid_servers = {}
    for name, config in mcp_config['mcpServers'].items():
        if 'command' in config:
            command = config['command']
            try:
                full_path = shutil.which(command)
                if full_path:
                    config['command'] = full_path
                    valid_servers[name] = config
                    logger.info(f"Resolved {command} to full path: {full_path}")
                else:
                    logger.warning(f"Could not find full path for {command}, removing from config")
            except Exception as e:
                logger.error(f"Error resolving path for {command}: {e}, removing from config")
        else:
            valid_servers[name] = config
    
    mcp_config['mcpServers'] = valid_servers
    return mcp_config

async def validate_mcp_servers(mcp_config: dict) -> dict:
    """
    Validate MCP servers individually and return config with only working servers.
    
    Args:
        mcp_config: Full MCP configuration with potentially failing servers
        
    Returns:
        dict: Configuration containing only successfully validated servers
    """
    if 'mcpServers' not in mcp_config:
        logger.warning("No mcpServers found in config")
        return mcp_config
    
    async def validate_single_server(server_name: str, server_config: dict) -> tuple[str, dict, bool, str]:
        """Validate a single MCP server and return result."""
        try:
            logger.info(f"Validating MCP server: {server_name}")
            
            # Create a temporary config with just this server
            test_config = {'mcpServers': {server_name: server_config}}
            
            # Try to create a client and validate it can list tools (tests API keys)
            try:
                test_client = Client(test_config)
                # Actually test the connection and API key by listing tools
                async with test_client:
                    await asyncio.wait_for(test_client.list_tools(), timeout=10.0)
                logger.info(f"✓ MCP server {server_name} validated successfully (tools accessible)")
                return server_name, server_config, True, ""
            except asyncio.TimeoutError:
                error_msg = f"{server_name} (timeout)"
                logger.warning(f"✗ MCP server {server_name} validation timed out")
                return server_name, server_config, False, error_msg
            except Exception as e:
                error_msg = f"{server_name} ({str(e)[:100]})"
                logger.warning(f"✗ MCP server {server_name} validation failed: {e}")
                return server_name, server_config, False, error_msg
                
        except Exception as e:
            error_msg = f"{server_name} (config error: {str(e)[:100]})"
            logger.error(f"✗ MCP server {server_name} config error: {e}")
            return server_name, server_config, False, error_msg
    
    # Run all validations in parallel
    logger.info(f"🚀 Starting parallel validation of {len(mcp_config['mcpServers'])} servers")
    validation_tasks = [
        validate_single_server(name, config) 
        for name, config in mcp_config['mcpServers'].items()
    ]
    
    # Wait for all validations to complete
    validation_results = await asyncio.gather(*validation_tasks, return_exceptions=True)
    
    # Process results
    working_servers = {}
    failed_servers = []
    
    for result in validation_results:
        if isinstance(result, Exception):
            failed_servers.append(f"Unknown server (exception: {str(result)[:100]})")
            logger.error(f"Validation task failed with exception: {result}")
        else:
            server_name, server_config, success, error_msg = result
            if success:
                working_servers[server_name] = server_config
            else:
                failed_servers.append(error_msg)
    
    # Log results
    logger.info(f"MCP server validation complete:")
    logger.info(f"  ✓ Working servers ({len(working_servers)}): {list(working_servers.keys())}")
    if failed_servers:
        logger.warning(f"  ✗ Failed servers ({len(failed_servers)}): {failed_servers}")
    
    # Return empty servers config if no servers work - allow server to start with no external MCP servers
    if not working_servers:
        logger.warning("No MCP servers passed validation - returning config with empty servers")
        return {
            **mcp_config,
            'mcpServers': {}
        }
    
    # Return config with only working servers
    validated_config = {
        **mcp_config,
        'mcpServers': working_servers
    }
    
    return validated_config

async def start_server(mcp_config: dict, host: str = "0.0.0.0", port: int = 8012):
    logger.info(f"Creating MCP server with config containing {len(mcp_config.get('mcpServers', {}))} servers")

    # Validate servers and get config with only working ones
    validated_config = await validate_mcp_servers(mcp_config)
    
    # Check if we have any working MCP servers
    if not validated_config.get('mcpServers', {}):
        logger.info("No working MCP servers found - exiting gracefully")
        return
    
    # This ensures session based tools work.
    async with Client(validated_config) as client:
        proxy = FastMCP.as_proxy(client)
        tools = await proxy.get_tools()
        logger.info(f"Found {len(tools)} working tools from validated MCP servers")
        app = proxy.http_app('/tools/mcp')

        """Start the FastAPI server."""
        # Register signal handlers
        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

        logger.info(f"Starting server on {host}:{port}")
        
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=True,
            workers=1  # Single worker as requested
        )
        server = uvicorn.Server(config)
        await server.serve()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python custom_mcp_server.py <mcp_config_path>")
        sys.exit(1)
    mcp_config_path = sys.argv[1]
    with open(mcp_config_path, "r") as f:
        mcp_config = json.load(f)
        mcp_config = prepare_mcp_config(mcp_config)
        asyncio.run(start_server(mcp_config))
