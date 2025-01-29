"""
Mouse device management and coordination.
"""
from typing import Optional, Dict
import threading
import time
import fcntl
from evdev.device import InputDevice
from BluetoothHID import logger, BluetoothHIDService
from constants.input_constants import (
    STATS_INTERVAL,
    RECOVERY_DELAY,
    EVIOCGRAB
)
from input.device_capabilities import DeviceCapabilityChecker
from input.mouse_events import MouseEventHandler


class MouseManager:
    """Manages mouse devices and coordinates event handling."""

    def __init__(self, bthid_srv: BluetoothHIDService):
        """
        Initialize the mouse manager.

        Args:
            bthid_srv: Bluetooth HID service to forward events to
        """
        self.bthid_srv = bthid_srv
        self.event_handler = MouseEventHandler(bthid_srv)
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.mouse_events = 0
        self.last_stats_time = time.time()
        
        # Device tracking
        self.movement_devices: Dict[str, InputDevice] = {}  # path -> device
        self.button_devices: Dict[str, InputDevice] = {}    # path -> device

    def _grab_device(self, device: InputDevice, device_type: str) -> bool:
        """
        Attempt to grab exclusive access to a device.

        Args:
            device: Input device to grab
            device_type: Type of device for logging

        Returns:
            bool: True if device was grabbed successfully
        """
        if device.fd < 0:
            logger.error(f"Invalid file descriptor for {device.name}")
            return False

        try:
            # Try evdev's grab first
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

    def _setup_devices(self) -> bool:
        """
        Find and set up mouse input devices.

        Returns:
            bool: True if any devices were set up successfully
        """
        mouse_devices = DeviceCapabilityChecker.find_mouse_devices()
        if not mouse_devices:
            return False

        # Sort devices by capability
        movement_candidates = []
        button_candidates = []
        combined_candidates = []

        for device, caps in mouse_devices:
            has_movement = caps.has_movement
            has_buttons = len(caps.button_capabilities) > 0
            
            if has_movement and has_buttons:
                combined_candidates.append((device, caps))
            elif has_movement:
                movement_candidates.append((device, caps))
            elif has_buttons:
                button_candidates.append((device, caps))

        # Try to find a suitable combined device
        if combined_candidates:
            # Prefer HARPOON device if available
            harpoon = next(
                ((dev, caps) for dev, caps in combined_candidates if "HARPOON" in dev.name),
                None
            )
            if harpoon:
                device, _ = harpoon
                if self._grab_device(device, "combined"):
                    logger.info(f"Using HARPOON device for all input: {device.name}")
                    self.movement_devices[device.path] = device
                    self.button_devices[device.path] = device
                    return True

            # Try first combined device
            device, _ = combined_candidates[0]
            if self._grab_device(device, "combined"):
                logger.info(f"Using combined device for all input: {device.name}")
                self.movement_devices[device.path] = device
                self.button_devices[device.path] = device
                return True

        # If no combined device works, try separate devices
        success = False

        # Try to grab movement device
        if movement_candidates:
            device, _ = movement_candidates[0]
            if self._grab_device(device, "movement"):
                logger.info(f"Using device for movement: {device.name}")
                self.movement_devices[device.path] = device
                success = True

        # Try to grab button device
        if button_candidates:
            device, _ = button_candidates[0]
            if self._grab_device(device, "buttons"):
                logger.info(f"Using device for buttons: {device.name}")
                self.button_devices[device.path] = device
                success = True

        if not success:
            logger.error("Failed to grab any mouse input devices")
            
        return success

    def _event_loop(self) -> None:
        """Main event processing loop."""
        while self.running:
            try:
                # Process events from all unique devices
                unique_devices = {}
                for device in self.movement_devices.values():
                    unique_devices[device.path] = device
                for device in self.button_devices.values():
                    unique_devices[device.path] = device
                
                for device in unique_devices.values():
                    try:
                        for event in device.read():
                            self.event_handler.process_event(event)
                            self.mouse_events += 1

                    except BlockingIOError:
                        continue
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
                self._release_devices()
                if not self._setup_devices():
                    logger.error("Failed to recover mouse devices")
                    break

    def _release_devices(self) -> None:
        """Release all grabbed devices."""
        # Get unique devices by path
        unique_devices = {}
        for device in self.movement_devices.values():
            unique_devices[device.path] = device
        for device in self.button_devices.values():
            unique_devices[device.path] = device
            
        for device in unique_devices.values():
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

    def start(self) -> None:
        """Start mouse input handling."""
        if self.thread and self.thread.is_alive():
            logger.warning("Mouse manager already running")
            return

        if not self._setup_devices():
            logger.error("No mouse devices available")
            return

        self.running = True
        self.thread = threading.Thread(target=self._event_loop)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Mouse manager started")

    def stop(self) -> None:
        """Stop mouse input handling and clean up resources."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

        self._release_devices()
        logger.info("Mouse manager stopped")
