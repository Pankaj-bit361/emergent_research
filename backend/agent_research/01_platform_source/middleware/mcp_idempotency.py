"""MCP idempotency middleware using FastMCP hooks."""
from cachetools import LRUCache
from fastmcp.server.middleware import Middleware, MiddlewareContext
from plugins.tools.agent.logger import logger

# LRU cache configuration
MAX_CACHE_SIZE = 30  # Maximum number of cached results

# Global LRU cache instance (thread-safe for single worker)
_cache: LRUCache = LRUCache(maxsize=MAX_CACHE_SIZE)


class MCPIdempotencyMiddleware(Middleware):
    """Cache MCP tool results by request_id to prevent duplicate execution."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Hook into tool execution to cache results by request_id."""
        # Extract request_id from tool arguments
        request_id = None
        if hasattr(context, 'message') and hasattr(context.message, 'arguments'):
            arguments = context.message.arguments or {}
            request_id = arguments.get('request_id')
            arguments.pop('request_id', None)
            context.message.arguments = arguments

        # No request_id = no caching, just execute
        if not request_id:
            return await call_next(context)

        # Check cache
        if request_id in _cache:
            logger.info(f"Cache HIT: {request_id}")
            return _cache[request_id]

        # Execute tool
        logger.info(f"Cache MISS: {request_id}")
        result = await call_next(context)

        # Cache the result
        _cache[request_id] = result
        logger.info(f"Cached result for: {request_id}")

        return result


def get_cache() -> LRUCache:
    """Get cache for testing."""
    return _cache
