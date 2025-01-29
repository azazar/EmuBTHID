"""
Constants related to input device handling and configuration.
"""
from enum import IntEnum

# IOCTL Commands
EVIOCGRAB = 1074021776  # 0x40044590

# Mouse Motion Limits
MOUSE_MIN_MOTION = -127
MOUSE_MAX_MOTION = 127

# Timing Constants (milliseconds)
DEVICE_SCAN_INTERVAL = 5000
EVENT_CHECK_INTERVAL = 10
STATS_INTERVAL = 60  # seconds
RECOVERY_DELAY = 1.0  # seconds


class MouseButton(IntEnum):
    """Enumeration of mouse button indices."""
    LEFT = 1
    RIGHT = 2
    MIDDLE = 3
    SIDE = 4
    EXTRA = 5
    FORWARD = 6
    BACK = 7


# Button code to index mapping
BUTTON_MAP = {
    'BTN_LEFT': MouseButton.LEFT,
    'BTN_MOUSE': MouseButton.LEFT,  # Alias for BTN_LEFT
    'BTN_RIGHT': MouseButton.RIGHT,
    'BTN_MIDDLE': MouseButton.MIDDLE,
    'BTN_SIDE': MouseButton.SIDE,
    'BTN_EXTRA': MouseButton.EXTRA,
    'BTN_FORWARD': MouseButton.FORWARD,
    'BTN_BACK': MouseButton.BACK
}


# UI Constants
ICON_SIZE = 24
ICON_FONT_SIZE = 20
