"""
Keyboard input handling and event processing.
"""

from typing import Optional, Any
import time
from Xlib import X, XK, display
from BluetoothHID import BluetoothHIDService, logger
from evdev_xkb_map import evdev_xkb_map, modkeys
from config import STATS_INTERVAL


class KeyboardManager:
    """
    Manages X11 keyboard input handling and event processing.
    Handles keyboard input grabbing and forwards events to connected devices.
    """

    def __init__(self, display_obj: display.Display, root: Any):
        """
        Initialize keyboard manager.

        Args:
            display_obj: X11 display connection
            root: X11 root window
        """
        self.display = display_obj
        self.root = root
        self.kbd_events = 0
        self.last_stats_time = time.time()

        # Get keycodes
        self.win_l_keycode = self.display.keysym_to_keycode(XK.XK_Super_L)
        self.win_r_keycode = self.display.keysym_to_keycode(XK.XK_Super_R)
        self.g_keycode = self.display.keysym_to_keycode(XK.XK_g)

        # Hotkey state
        self.win_pressed = False
        self.g_pressed = False

    def setup(self) -> bool:
        """
        Setup initial key grabs for hotkey handling.

        Returns:
            bool: True if setup was successful, False otherwise
        """
        try:
            for win_keycode in [self.win_l_keycode, self.win_r_keycode]:
                if win_keycode:
                    self.root.grab_key(
                        win_keycode,
                        X.AnyModifier,
                        True,
                        X.GrabModeAsync,
                        X.GrabModeAsync
                    )
            self.display.sync()
            logger.info("Successfully grabbed hotkeys")
            return True
        except Exception as e:
            logger.error(f"Failed to grab hotkeys: {e}")
            return False

    def start_input_grab(self, bthid_srv: BluetoothHIDService) -> bool:
        """
        Start grabbing keyboard input.

        Args:
            bthid_srv: BluetoothHID service to forward input events to

        Returns:
            bool: True if input grab was successful, False otherwise
        """
        try:
            self.root.grab_keyboard(True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
            self.display.sync()
            logger.info("Successfully grabbed keyboard")
            return True
        except Exception as e:
            logger.error(f"Failed to grab input: {e}")
            return False

    def stop_input_grab(self) -> None:
        """Stop grabbing input and release keyboard grab."""
        try:
            self.display.ungrab_keyboard(X.CurrentTime)
            self.display.sync()
        except Exception as e:
            logger.error(f"Error releasing keyboard: {e}")

    def _handle_modifier_keys(self, event: Any, bthid_srv: Optional[BluetoothHIDService]) -> None:
        """
        Handle modifier key events (Shift, Ctrl, Alt, Win).
        Updates modifier state and forwards to HID service.

        Args:
            event: X11 key event
            bthid_srv: BluetoothHID service to forward events to
        """
        if event.detail in [self.win_l_keycode, self.win_r_keycode]:
            is_press = event.type == X.KeyPress
            self.win_pressed = is_press

            # Forward Win key
            if bthid_srv:
                try:
                    keycode = evdev_xkb_map[event.detail]
                    if is_press:
                        bthid_srv.handle_key_press(keycode, modkeys)
                    else:
                        bthid_srv.handle_key_release(keycode, modkeys)
                    self.kbd_events += 1
                except KeyError:
                    logger.debug(f"Unknown Win keycode: {event.detail}")

    def _handle_hotkey_combination(self, event: Any, bthid_srv: Optional[BluetoothHIDService]) -> Optional[str]:
        """
        Handle Win+G hotkey combination detection.

        Args:
            event: X11 key event
            bthid_srv: BluetoothHID service to forward non-hotkey events to

        Returns:
            str: "hotkey" if hotkey combination was detected, None otherwise
        """
        if event.detail == self.g_keycode:
            is_press = event.type == X.KeyPress
            self.g_pressed = is_press

            # Return hotkey event if combination complete
            if is_press and self.win_pressed:
                logger.info("Hotkey combination detected")
                return "hotkey"

            # Forward G key if not hotkey
            if not self.win_pressed and bthid_srv:
                try:
                    keycode = evdev_xkb_map[event.detail]
                    if is_press:
                        bthid_srv.handle_key_press(keycode, modkeys)
                    else:
                        bthid_srv.handle_key_release(keycode, modkeys)
                    self.kbd_events += 1
                except KeyError:
                    logger.debug(f"Unknown G keycode: {event.detail}")
        return None

    def _forward_regular_input(self, event: Any, bthid_srv: Optional[BluetoothHIDService]) -> None:
        """
        Forward regular key input to HID service.

        Args:
            event: X11 key event
            bthid_srv: BluetoothHID service to forward events to
        """
        if not bthid_srv:
            return

        try:
            keycode = evdev_xkb_map[event.detail]
            if event.type == X.KeyPress:
                bthid_srv.handle_key_press(keycode, modkeys)
            else:
                bthid_srv.handle_key_release(keycode, modkeys)
            self.kbd_events += 1
        except KeyError:
            logger.debug(f"Unknown keycode: {event.detail}")

    def handle_event(self, event: Any, bthid_srv: Optional[BluetoothHIDService]) -> Optional[str]:
        """
        Handle an X11 keyboard event.

        Args:
            event: X11 event to process
            bthid_srv: BluetoothHID service to forward events to, if connected

        Returns:
            str: "hotkey" if hotkey combination was detected, None otherwise
        """
        try:
            if event.type not in [X.KeyPress, X.KeyRelease]:
                return None

            # Handle modifier keys first
            if event.detail in [self.win_l_keycode, self.win_r_keycode]:
                self._handle_modifier_keys(event, bthid_srv)
                return None

            # Check for hotkey combination
            if event.detail == self.g_keycode:
                result = self._handle_hotkey_combination(event, bthid_srv)
                if result:
                    return result

            # Handle regular keys
            if event.detail not in [self.win_l_keycode, self.win_r_keycode, self.g_keycode]:
                self._forward_regular_input(event, bthid_srv)

        except Exception as e:
            logger.error(f"Error handling event: {e}")

        return None

    def log_stats(self) -> None:
        """Log keyboard event statistics if threshold time has passed."""
        current_time = time.time()
        if current_time - self.last_stats_time >= STATS_INTERVAL and self.kbd_events > 0:
            events_per_sec = self.kbd_events / STATS_INTERVAL
            logger.info(f"Keyboard events per second: {events_per_sec:.1f}")
            self.kbd_events = 0
            self.last_stats_time = current_time

    def cleanup(self) -> None:
        """Clean up input handlers and release all key grabs."""
        self.stop_input_grab()
        try:
            for win_keycode in [self.win_l_keycode, self.win_r_keycode]:
                if win_keycode:
                    self.root.ungrab_key(win_keycode, X.AnyModifier)
            self.root.ungrab_key(self.g_keycode, X.AnyModifier)
            self.display.sync()
        except Exception as e:
            logger.error(f"Error releasing hotkeys: {e}")
