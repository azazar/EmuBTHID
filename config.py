"""
Application configuration and timing constants.
"""

# Application identity
APP_NAME = "emubthid"
DEFAULT_LOG_LEVEL = "INFO"

# Input timing
MOUSE_POLL_TIMEOUT = 0.01  # seconds between mouse event checks
MOTION_UPDATE_THRESHOLD = 0.01  # seconds between motion updates
STATS_INTERVAL = 10.0  # seconds between stats logging

# Error recovery
RECOVERY_DELAY = 0.1  # seconds to wait during error recovery
RECOVERY_THRESHOLD = 0.1  # seconds without overflow to consider recovered

# Connection handling
CONNECTION_TIMEOUT = 5.0  # seconds to wait for connection
RECONNECT_DELAY = 1.0  # seconds to wait between connection attempts
