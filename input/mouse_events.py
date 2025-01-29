"""
Mouse event processing and handling.
"""
from dataclasses import dataclass
import evdev
from BluetoothHID import logger, BluetoothHIDService
from constants.input_constants import (
    MOUSE_MIN_MOTION,
    MOUSE_MAX_MOTION,
    BUTTON_MAP
)


@dataclass
class MouseMotion:
    """Represents accumulated mouse motion."""
    x: int = 0
    y: int = 0

    def clear(self) -> None:
        """Reset motion values to zero."""
        self.x = 0
        self.y = 0

    def is_empty(self) -> bool:
        """Check if there is any accumulated motion."""
        return self.x == 0 and self.y == 0

    def clamp_values(self) -> None:
        """Clamp motion values to valid range."""
        self.x = max(MOUSE_MIN_MOTION, min(self.x, MOUSE_MAX_MOTION))
        self.y = max(MOUSE_MIN_MOTION, min(self.y, MOUSE_MAX_MOTION))


class MouseEventHandler:
    """Handles processing and forwarding of mouse input events."""

    def __init__(self, bthid_srv: BluetoothHIDService):
        """
        Initialize the mouse event handler.

        Args:
            bthid_srv: Bluetooth HID service to forward events to
        """
        self.bthid_srv = bthid_srv
        self.accumulated_motion = MouseMotion()

    def handle_motion_event(self, event: evdev.InputEvent) -> None:
        """
        Handle mouse motion event.

        Args:
            event: Input event containing motion data
        """
        motion = max(MOUSE_MIN_MOTION, min(event.value, MOUSE_MAX_MOTION))
        
        if event.code == evdev.ecodes.REL_X:
            self.accumulated_motion.x += motion
        elif event.code == evdev.ecodes.REL_Y:
            self.accumulated_motion.y += motion

    def handle_button_event(self, event: evdev.InputEvent) -> None:
        """
        Handle mouse button event.

        Args:
            event: Input event containing button data
        """
        try:
            # Get button name from event code
            button_code = event.code
            button_name = None
            
            # Try to get button name from ecodes
            try:
                button_name = evdev.ecodes.BTN[button_code]
            except KeyError:
                # Try to get name from KEY codes (some devices use KEY instead of BTN)
                try:
                    button_name = evdev.ecodes.KEY[button_code]
                except KeyError:
                    logger.warning(f"Unknown button code: {button_code}")
                    return

            # Check if this is a mouse button we support
            if button_name in BUTTON_MAP:
                button = BUTTON_MAP[button_name]
                logger.debug(f"Processing button {button_name} ({button.name})")
                if event.value == 1:  # Press
                    logger.debug(f"Mouse button {button.name} pressed")
                    self.bthid_srv.handle_button_press(button)
                else:  # Release
                    logger.debug(f"Mouse button {button.name} released")
                    self.bthid_srv.handle_button_release(button)
        except Exception as e:
            logger.error(f"Error processing button event: {e}")

    def flush_accumulated_motion(self) -> None:
        """Send any accumulated motion to the HID service."""
        if not self.accumulated_motion.is_empty():
            self.accumulated_motion.clamp_values()
            self.bthid_srv.handle_mouse_motion(
                self.accumulated_motion.x,
                self.accumulated_motion.y
            )
            self.accumulated_motion.clear()

    def process_event(self, event: evdev.InputEvent) -> None:
        """
        Process a single input event.

        Args:
            event: Input event to process
        """
        if event.type == evdev.ecodes.EV_REL:
            self.handle_motion_event(event)
            
        elif event.type == evdev.ecodes.EV_KEY:
            # Flush any accumulated motion before handling button event
            self.flush_accumulated_motion()
            self.handle_button_event(event)
            
        # Flush accumulated motion on sync events
        elif event.type == evdev.ecodes.EV_SYN:
            self.flush_accumulated_motion()
