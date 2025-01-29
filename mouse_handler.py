"""
Mouse input handling and event processing.
"""

from typing import List
import threading
import evdev
import time
import fcntl
from evdev.device import InputDevice
from BluetoothHID import logger, BluetoothHIDService

from config import (
    STATS_INTERVAL,
    RECOVERY_DELAY
)
from protocol import MOUSE_MIN_MOTION, MOUSE_MAX_MOTION

# IOCTL commands
try:
    # Try to get EVIOCGRAB from evdev if available
    from evdev.device import EVIOCGRAB
except ImportError:
    # Fall back to our own definition
    EVIOCGRAB = 1074021776  # 0x40044590


class MouseHandler:
    """
    Handles mouse input events and forwards them to a Bluetooth HID service.
    Captures mouse movements and button presses from multiple input devices.
    """

    def __init__(self, bthid_srv: BluetoothHIDService):
        self.bthid_srv = bthid_srv
        self.movement_devices: List[InputDevice] = []  # Devices with REL_X/REL_Y
        self.button_devices: List[InputDevice] = []    # Devices with mouse buttons
        self.running = False
        self.thread = None
        self.mouse_events = 0
        self.last_stats_time = time.time()

    def find_mouse_devices(self) -> bool:
        """
        Find all input devices with mouse-like capabilities.
        Looks for devices with movement axes and/or mouse buttons.

        Returns:
            bool: True if any mouse-like devices were found
        """
        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            logger.debug(f"Found {len(devices)} input devices")

            for device in devices:
                capabilities = device.capabilities(verbose=True)
                logger.debug(f"Checking device: {device.name}")

                # Check for movement capabilities (REL_X/REL_Y)
                if ('EV_REL', evdev.ecodes.EV_REL) in capabilities:
                    rel_caps = capabilities[('EV_REL', evdev.ecodes.EV_REL)]
                    rel_names = []
                    for cap in rel_caps:
                        if isinstance(cap[0], (list, tuple)):
                            rel_names.extend(cap[0])
                        else:
                            rel_names.append(cap[0])
                    has_x = 'REL_X' in rel_names
                    has_y = 'REL_Y' in rel_names
                    has_movement = has_x and has_y
                    if has_movement:
                        logger.debug(f"Found movement device: {device.name}")
                        self.movement_devices.append(device)

                # Check for button capabilities
                if ('EV_KEY', evdev.ecodes.EV_KEY) in capabilities:
                    key_caps = capabilities[('EV_KEY', evdev.ecodes.EV_KEY)] 
                    key_names = []
                    for cap in key_caps:
                        if isinstance(cap[0], (list, tuple)):
                            key_names.extend(cap[0])
                        else:
                            key_names.append(cap[0])
                    mouse_buttons = [
                        'BTN_LEFT', 'BTN_MOUSE',  # Same button
                        'BTN_RIGHT',
                        'BTN_MIDDLE',
                        'BTN_SIDE',
                        'BTN_EXTRA',
                        'BTN_FORWARD',
                        'BTN_BACK'
                    ]
                    found_buttons = []
                    for name in key_names:
                        if name in mouse_buttons:
                            found_buttons.append(name)
                    if found_buttons:
                        logger.debug(f"Found button device: {device.name} with buttons: {', '.join(found_buttons)}")
                        self.button_devices.append(device)

            if not self.movement_devices and not self.button_devices:
                logger.warning("No mouse-like devices found")
                return False

            logger.info(f"Found {len(self.movement_devices)} movement devices and {len(self.button_devices)} button devices")
            return True

        except Exception as e:
            logger.error(f"Error finding mouse devices: {e}")
            return False

    def grab_device(self, device: InputDevice, device_type: str) -> bool:
        """
        Attempt to grab a single device using various methods.

        Args:
            device: The input device to grab
            device_type: Type of device ("movement" or "button") for logging

        Returns:
            bool: True if device was grabbed or can be used without grab
        """
        if device.fd < 0:
            logger.error(f"Invalid file descriptor for {device.name}")
            return False

        try:
            # First try evdev's grab
            try:
                device.grab()
                logger.info(f"Grabbed {device_type} device using evdev grab: {device.name}")
                return True
            except Exception as e:
                logger.warning(f"Evdev grab failed for {device.name}, trying EVIOCGRAB: {e}")

                try:
                    # Try EVIOCGRAB
                    fcntl.ioctl(device.fd, EVIOCGRAB, 1)
                    logger.info(f"Grabbed {device_type} device using EVIOCGRAB: {device.name}")
                    return True
                except Exception as e:
                    logger.warning(f"EVIOCGRAB failed for {device.name}, using non-exclusive mode: {e}")
                    # Continue without exclusive access
                    logger.info(f"Using {device_type} device without grab: {device.name}")
                    return True

        except Exception as e:
            logger.error(f"Error grabbing {device_type} device {device.name}: {e}")
            return False

    def grab_devices(self) -> bool:
        """
        Attempt to grab all mouse devices.

        Returns:
            bool: True if at least one device was grabbed or usable
        """
        grabbed_any = False

        # Find devices that have both movement and buttons
        combined_devices = []
        for mdev in self.movement_devices:
            for bdev in self.button_devices:
                if mdev.path == bdev.path:
                    combined_devices.append(mdev)
                    break

        # Try to grab HARPOON device first if available
        harpoon = next((d for d in combined_devices if "HARPOON" in d.name), None)
        if harpoon:
            if self.grab_device(harpoon, "combined"):
                grabbed_any = True
                logger.info(f"Using HARPOON device for movement and buttons: {harpoon.name}")
                # Keep only HARPOON device
                self.movement_devices = [harpoon]
                self.button_devices = [harpoon]
                return True

        # Otherwise try other combined devices
        if combined_devices:
            for device in combined_devices:
                if self.grab_device(device, "combined"):
                    grabbed_any = True
                    logger.info(f"Using combined device for movement and buttons: {device.name}")
                    # Keep only this combined device
                    self.movement_devices = [device]
                    self.button_devices = [device]
                    return True

        # If no combined devices work, try individual devices
        for device in self.movement_devices:
            if self.grab_device(device, "movement"):
                grabbed_any = True

        for device in self.button_devices:
            if self.grab_device(device, "button"):
                grabbed_any = True

        return grabbed_any

    def start(self) -> None:
        """
        Start mouse event handling in a separate thread.
        Finds and grabs mouse devices, then starts monitoring their events.
        """
        if self.thread and self.thread.is_alive():
            logger.warning("Mouse handler already running")
            return

        # Find mouse devices
        if not self.find_mouse_devices():
            logger.error("No mouse devices available")
            return

        # Try to grab devices
        if not self.grab_devices():
            logger.error("Failed to grab any mouse devices")
            return

        self.running = True
        self.thread = threading.Thread(target=self._event_loop)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Mouse handler started")

    def stop(self) -> None:
        """
        Stop mouse event handling and clean up resources.
        Stops the event loop and releases all grabbed devices.
        """
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

        # Release all devices
        for device in self.movement_devices + self.button_devices:
            try:
                try:
                    device.ungrab()
                except Exception as e:
                    logger.warning(f"Failed to ungrab device {device.name}: {e}")
                    try:
                        fcntl.ioctl(device.fd, EVIOCGRAB, 0)
                    except Exception as e:
                        logger.warning(f"Failed to release EVIOCGRAB for {device.name}: {e}")
                device.close()
            except Exception as e:
                logger.error(f"Error releasing device {device.name}: {e}")

        self.movement_devices.clear()
        self.button_devices.clear()
        logger.info("Mouse handler stopped")

    def _event_loop(self) -> None:
        """
        Main event loop for mouse handling.
        Monitors events from all movement and button devices.
        """
        while self.running:
            try:
                # Process events from all devices
                for device in self.movement_devices + self.button_devices:
                    try:
                        for event in device.read():
                            if event.type == evdev.ecodes.EV_REL:  # Mouse movement
                                x_motion = 0
                                y_motion = 0
                                if event.code == evdev.ecodes.REL_X:
                                    # Clamp motion value
                                    x_motion = max(MOUSE_MIN_MOTION, min(event.value, MOUSE_MAX_MOTION))
                                    self.bthid_srv.handle_mouse_motion(x_motion, 0)
                                    self.mouse_events += 1
                                elif event.code == evdev.ecodes.REL_Y:
                                    # Clamp motion value
                                    y_motion = max(MOUSE_MIN_MOTION, min(event.value, MOUSE_MAX_MOTION))
                                    self.bthid_srv.handle_mouse_motion(0, y_motion)
                                    self.mouse_events += 1
                            elif event.type == evdev.ecodes.EV_KEY:
                                # Map button codes to 1-based indices
                                button_map = {
                                    evdev.ecodes.BTN_LEFT: 1,
                                    evdev.ecodes.BTN_MOUSE: 1,  # Alias for BTN_LEFT
                                    evdev.ecodes.BTN_RIGHT: 2,
                                    evdev.ecodes.BTN_MIDDLE: 3,
                                    evdev.ecodes.BTN_SIDE: 4,
                                    evdev.ecodes.BTN_EXTRA: 5,
                                    evdev.ecodes.BTN_FORWARD: 6,
                                    evdev.ecodes.BTN_BACK: 7
                                }
                                if event.code in button_map:
                                    button = button_map[event.code]
                                    if event.value == 1:  # Press
                                        logger.debug(f"Mouse button {button} pressed")
                                        self.bthid_srv.handle_button_press(button)
                                    else:  # Release
                                        logger.debug(f"Mouse button {button} released")
                                        self.bthid_srv.handle_button_release(button)
                                    self.mouse_events += 1
                    except BlockingIOError:
                        continue  # No events available
                    except OSError as e:
                        if e.errno == 11:  # Resource temporarily unavailable
                            continue
                        logger.error(f"Error reading from device {device.name}: {e}")
                        continue

                # Log stats if needed
                current_time = time.time()
                if current_time - self.last_stats_time >= STATS_INTERVAL and self.mouse_events > 0:
                    events_per_sec = self.mouse_events / STATS_INTERVAL
                    logger.info(f"Mouse events per second: {events_per_sec:.1f}")
                    self.mouse_events = 0
                    self.last_stats_time = current_time

            except Exception as e:
                logger.error(f"Error in mouse event loop: {e}")
                # Try to recover
                time.sleep(RECOVERY_DELAY)
                if not self.running:
                    break

                # Try to reopen devices
                self.movement_devices.clear()
                self.button_devices.clear()
                if not self.find_mouse_devices() or not self.grab_devices():
                    logger.error("Failed to recover mouse devices")
                    break
