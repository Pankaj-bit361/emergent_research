import os
import fcntl
import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger("lock_decorator")
logger.propagate = False
logger.setLevel(logging.INFO)

def with_lock(lockfile: str, failure_return=None):
    """Decorator to acquire and release a lock around a function call."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            fd = None
            try:
                fd = os.open(lockfile, os.O_CREAT | os.O_RDWR)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.info(f"Acquired lock: {lockfile}")
                result = func(*args, **kwargs)
                return result
            except IOError:
                logger.error("Another instance is already running")
                if failure_return is not None:
                    return failure_return
                raise
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    logger.info(f"Released lock: {lockfile}")
        return wrapper
    return decorator 