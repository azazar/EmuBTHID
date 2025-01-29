"""
Logging configuration and custom filters.
"""

import os
import time
import logging
import resource
from config import DEFAULT_LOG_LEVEL

# Configure logging with microsecond precision
logging.basicConfig(
    format='%(asctime)s.%(msecs)06d [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    level=getattr(logging, os.environ.get('LOGLEVEL', DEFAULT_LOG_LEVEL))
)

logger = logging.getLogger('bthid')


def log_resource_usage():
    """
    Log memory usage if it has changed significantly.
    Tracks changes in memory usage and logs warnings if usage increases by more than 10%.
    """
    usage = resource.getrusage(resource.RUSAGE_SELF)
    current_mem = usage.ru_maxrss
    if not hasattr(log_resource_usage, 'last_mem'):
        log_resource_usage.last_mem = current_mem

    # Log if memory usage has increased by more than 10%
    if current_mem > log_resource_usage.last_mem * 1.1:
        logger.warning('Memory usage increased to %d KB (was %d KB)',
                       current_mem, log_resource_usage.last_mem)
        log_resource_usage.last_mem = current_mem


class DuplicateFilter(logging.Filter):
    """
    Filter that prevents duplicate log messages within a short time window.
    Only allows unique messages through, or repeats after a timeout.
    """
    def __init__(self, timeout: float = 5.0):
        """
        Initialize the filter.

        Args:
            timeout: Number of seconds to suppress duplicate messages
        """
        super().__init__()
        self.timeout = timeout
        self.last_log = {}

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log records to prevent duplicates.

        Args:
            record: The log record to check

        Returns:
            bool: True if the message should be logged, False to suppress
        """
        current_time = time.time()
        msg_key = (record.levelno, record.msg)

        # Allow through if not a duplicate in the timeout window
        if msg_key not in self.last_log or current_time - self.last_log[msg_key] > self.timeout:
            self.last_log[msg_key] = current_time
            return True
        return False


# Add duplicate filtering to logger
logger.addFilter(DuplicateFilter())
