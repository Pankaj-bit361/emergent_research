"""MCP resource monitoring middleware using FastMCP."""
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from plugins.tools.agent.logger import logger
from plugins.tools.agent.system_tools import get_pod_resources

# Resource thresholds (in percentage)
MEMORY_THRESHOLD = 80
CPU_THRESHOLD = 80
STORAGE_WARNING_THRESHOLD = 75  # Warning starts at 75%
STORAGE_CRITICAL_THRESHOLD = 90  # Critical at 90%

# Flag to disable CPU check
ENABLE_CPU_CHECK = False


class MCPResourceMonitorMiddleware(Middleware):
    """Monitor pod resources and append warnings to tool results if thresholds exceeded."""

    def _format_warning(self, resources: dict) -> str | None:
        """Format resource warning from resources dict."""
        warnings = []

        memory = resources['memory']
        if memory['percentage'] > MEMORY_THRESHOLD:
            warnings.append(f"Memory: {memory['details']}")

        if ENABLE_CPU_CHECK:
            cpu = resources['cpu']
            if cpu['percentage'] > CPU_THRESHOLD:
                warnings.append(f"CPU: {cpu['details']}")

        storage = resources['storage']
        if storage['percentage'] > STORAGE_CRITICAL_THRESHOLD:
            warnings.append(f"Storage: {storage['details']} CRITICAL - Clear the storage immediately!")
        elif storage['percentage'] > STORAGE_WARNING_THRESHOLD:
            warnings.append(f"Storage: {storage['details']}")

        if warnings:
            warning_msg = "\n<system_reminder>\n"
            warning_msg += "RESOURCE WARNING:\n"
            warning_msg += '\n'.join(warnings) + '\n'
            warning_msg += "NOTE: This is an automated reminder. Please do not mention this in your response.\n"
            warning_msg += "</system_reminder>\n"
            return warning_msg

        return None

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Hook into tool execution to append resource warnings."""
        # Execute the tool first
        result = await call_next(context)

        # Get pod resources from system_tools
        resources = get_pod_resources()

        # Format warning based on thresholds
        resource_warning = self._format_warning(resources)

        # If thresholds exceeded, append warning to result
        if resource_warning:
            logger.info("Resource threshold exceeded, appending warning")
            result = self._append_warning_to_result(result, resource_warning)

        return result

    def _append_warning_to_result(self, result: ToolResult, warning: str) -> ToolResult:
        """Append resource warning to ToolResult output field (always text)."""
        # append warning to result only if it has structured_content with 'output' field
        if result.structured_content and isinstance(result.structured_content, dict):
            if 'output' in result.structured_content:
                # Append warning to output field (always text)
                result.structured_content['output'] = result.structured_content['output'] + warning
                return result

        return result
