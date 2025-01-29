"""
Device capability checking and validation.
"""
from typing import List, Set, Tuple
from dataclasses import dataclass
import evdev
from evdev.device import InputDevice
from BluetoothHID import logger


@dataclass
class DeviceCapabilities:
    """Data class representing device input capabilities."""
    has_x_axis: bool = False
    has_y_axis: bool = False
    button_capabilities: Set[str] = None

    def __post_init__(self):
        if self.button_capabilities is None:
            self.button_capabilities = set()

    @property
    def has_movement(self) -> bool:
        """Check if device has both X and Y axis movement."""
        return self.has_x_axis and self.has_y_axis

    @property
    def has_buttons(self) -> bool:
        """Check if device has any mouse buttons."""
        return len(self.button_capabilities) > 0


class DeviceCapabilityChecker:
    """Handles device capability detection and validation."""

    MOUSE_BUTTONS = {
        'BTN_LEFT', 'BTN_MOUSE',  # Same button
        'BTN_RIGHT', 'BTN_MIDDLE',
        'BTN_SIDE', 'BTN_EXTRA',
        'BTN_FORWARD', 'BTN_BACK'
    }

    @staticmethod
    def get_capability_names(capabilities: dict, event_type: str) -> Set[str]:
        """
        Extract capability names from evdev capabilities dict.

        Args:
            capabilities: Device capabilities dictionary
            event_type: Event type to extract capabilities for

        Returns:
            Set of capability names
        """
        names = set()
        if (event_type, getattr(evdev.ecodes, event_type)) in capabilities:
            caps = capabilities[(event_type, getattr(evdev.ecodes, event_type))]
            for cap in caps:
                if isinstance(cap[0], (list, tuple)):
                    names.update(cap[0])
                else:
                    names.add(cap[0])
        return names

    @classmethod
    def check_device_capabilities(cls, device: InputDevice) -> DeviceCapabilities:
        """
        Check input device capabilities.

        Args:
            device: Input device to check capabilities for

        Returns:
            DeviceCapabilities object with detected capabilities
        """
        capabilities = device.capabilities(verbose=True)
        logger.debug(f"Checking capabilities for device: {device.name}")

        # Check movement capabilities
        rel_names = cls.get_capability_names(capabilities, 'EV_REL')
        has_x = 'REL_X' in rel_names
        has_y = 'REL_Y' in rel_names

        # Check button capabilities
        key_names = cls.get_capability_names(capabilities, 'EV_KEY')
        button_capabilities = key_names.intersection(cls.MOUSE_BUTTONS)

        return DeviceCapabilities(
            has_x_axis=has_x,
            has_y_axis=has_y,
            button_capabilities=button_capabilities
        )

    @classmethod
    def find_mouse_devices(cls) -> List[Tuple[InputDevice, DeviceCapabilities]]:
        """
        Find all input devices with mouse-like capabilities.

        Returns:
            List of tuples containing (device, capabilities)
        """
        mouse_devices = []

        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            logger.debug(f"Found {len(devices)} input devices")

            for device in devices:
                capabilities = cls.check_device_capabilities(device)
                
                # Only add devices that have either movement or buttons
                if capabilities.has_movement or len(capabilities.button_capabilities) > 0:
                    logger.debug(
                        f"Found mouse device: {device.name} "
                        f"(movement: {capabilities.has_movement}, buttons: "
                        f"{sorted(list(capabilities.button_capabilities))})"
                    )
                    mouse_devices.append((device, capabilities))

            return mouse_devices

        except Exception as e:
            logger.error(f"Error finding mouse devices: {e}")
            return []
