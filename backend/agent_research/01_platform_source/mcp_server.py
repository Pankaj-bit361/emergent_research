"""Simplified MCP Server using direct tool registration.

This module demonstrates the FastMCP-aligned approach:
- No adapter pattern needed
- Direct import of mcp instance with registered tools
- Simplified server management
"""

import asyncio
import logging
from typing import Optional

from plugins.tools.agent.mcp_tools import mcp
from fastmcp import FastMCP
# from fastmcp.server.proxy import ProxyClient
from fastmcp.client.transports import StdioTransport



from fastmcp import FastMCP

logger = logging.getLogger(__name__)


class MCPToolServer:
    """
    Simplified MCP Tool Server following FastMCP best practices.

    This class manages the FastMCP server instance that has tools
    registered directly via decorators, eliminating the adapter pattern.
    """

    def __init__(self, server_name: str = "Emergent-Tools"):
        """
        Initialize the MCP Tool Server.

        Args:
            server_name: Name for the server (already set in mcp_tools.py)
        """
        self.server_name = server_name
        self.mcp = mcp  # Use the pre-configured FastMCP instance
        self._is_warmed = False
        self._warmed_tools = None


    async def pre_warm(self):
        """
        Pre-warm MCP connections by listing tools.
        This triggers the lazy initialization of proxy connections.
        """
        if self._is_warmed:
            return self._warmed_tools

        logger.info("Pre-warming MCP server connections...")
        try:
            # This call will establish StdioTransport connections
            # and download npx packages if not cached
            tools = await self.mcp.get_tools()
            self._warmed_tools = tools
            self._is_warmed = True
            logger.info(f"Pre-warmed {len(tools)} tools successfully")
            return self._warmed_tools
        except Exception as e:
            logger.error(f"Failed to pre-warm MCP connections: {e}")
            return {}

    def trigger_pre_warm(self):
        """
        Trigger pre-warming in the background without waiting.
        Call this during server startup to establish connections early.
        """
        import asyncio

        async def _background_pre_warm():
            try:
                await self.pre_warm()
            except Exception as e:
                logger.error(f"Background pre-warm failed: {e}")

        # Try to get the current event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule the pre-warm task without waiting
                asyncio.create_task(_background_pre_warm())
                logger.info("Scheduled background pre-warming of MCP connections")
            else:
                # If no loop is running, create a task for when one starts
                loop.run_until_complete(_background_pre_warm())
        except RuntimeError:
            # No event loop exists yet, create and run
            asyncio.run(_background_pre_warm())

    def _get_tool_names_sync(self) -> list[str]:
        """
        Synchronously get tool names (for initialization).

        Returns:
            List of registered tool names
        """
        # Use the synchronous _tool_manager to get tools directly
        if hasattr(self.mcp, '_tool_manager') and hasattr(self.mcp._tool_manager, 'tools'):
            return list(self.mcp._tool_manager.tools.keys())
        return []

    async def get_tool_names_async(self) -> list[str]:
        """
        Asynchronously get list of all available tool names.

        Returns:
            List of registered tool names
        """
        # Use FastMCP's built-in async method to get registered tools
        tools = await self.mcp.get_tools()
        return list(tools.keys())

    def get_tool_names(self) -> list[str]:
        """
        Get list of all available tool names (synchronous wrapper).

        Returns:
            List of registered tool names
        """
        # Try to get from tool manager directly (sync access)
        if hasattr(self.mcp, '_tool_manager') and hasattr(self.mcp._tool_manager, 'tools'):
            return list(self.mcp._tool_manager.tools.keys())

        # Fallback to async method if needed
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is already running, we can't use run_until_complete
                # Return empty list or cached value
                return self._get_tool_names_sync()
            else:
                return loop.run_until_complete(self.get_tool_names_async())
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self.get_tool_names_async())

    def is_warmed(self) -> bool:
        """Check if the server connections have been pre-warmed."""
        return self._is_warmed

    def get_stats(self) -> dict:
        """
        Get server statistics.

        Returns:
            Dictionary with server stats
        """
        tool_names = self.get_tool_names()

        # Group tools by category based on their function names
        file_tools = [t for t in tool_names if not t.startswith("lint_")]
        lint_tools = [t for t in tool_names if t.startswith("lint_")]

        return {
            "server_name": self.server_name,
            "total_tools": len(tool_names),
            "categories": {
                "file_operations": file_tools,
                "linting": lint_tools
            },
            "all_tools": tool_names
        }

    def run(self):
        """
        Run the MCP server.

        This starts the FastMCP server to handle incoming requests.
        """
        logger.info(f"Starting MCP server: {self.server_name}")
        self.mcp.run()

# Global instance for reuse
_mcp_server: Optional[MCPToolServer] = None


def get_mcp_server(server_name: str = "Emergent-Tools", pre_warm: bool = True) -> MCPToolServer:
    """
    Get or create the global MCP server instance.

    This follows the singleton pattern for server management.

    Args:
        server_name: Name for the server (only used on first creation)
        pre_warm: Whether to trigger background pre-warming on creation (default: True)

    Returns:
        MCPToolServer instance
    """
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPToolServer(server_name)
        if pre_warm:
            _mcp_server.trigger_pre_warm()
    return _mcp_server

if __name__ == "__main__":
    server = get_mcp_server()
    print(f"Server stats: {server.get_stats()}")
    server.run()