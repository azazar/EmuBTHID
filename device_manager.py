"""
Bluetooth device management and connection handling.
"""

from typing import List, Optional, Tuple
import dbus
from BluetoothHID import BluetoothHIDService, get_default_adapter_address, logger
from device_store import save_last_device, get_last_device
from protocol import HID_UUID
from dbus_constants import BLUEZ_SERVICE


class DeviceManager:
    """
    Manages Bluetooth HID device connections and state.
    Handles device scanning, connection/disconnection, and maintains device state.
    """

    def __init__(self):
        """Initialize the device manager."""
        self.service_record = open("sdp_record_kbd.xml").read()
        self.controller_mac = get_default_adapter_address()
        self.bthid_srv: Optional[BluetoothHIDService] = None
        self.connected_device: Optional[str] = None

    def scan_devices(self) -> List[Tuple[str, str]]:
        """
        Scan for available Bluetooth HID devices.

        Returns:
            List of (name, mac_address) tuples for available paired HID devices

        Raises:
            DBusException: If there's an error communicating with BlueZ
        """
        try:
            bus = dbus.SystemBus()
            manager = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            objects = manager.GetManagedObjects()
            # Skip logging BlueZ objects count

            devices = []
            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue

                props = interfaces["org.bluez.Device1"]
                if "Address" not in props:
                    continue

                name = str(props.get("Name", props["Address"]))
                addr = str(props["Address"])

                if props.get("Paired", False):
                    uuids = props.get("UUIDs", [])
                    is_hid = (
                        HID_UUID in uuids or
                        any(uuid.startswith("00001130") for uuid in uuids) or
                        any(uuid.startswith("00001132") for uuid in uuids)
                    )
                    if is_hid:
                        logger.info(f"Found HID device: {name} ({addr})")
                        devices.append((name, addr))

            return devices
        except Exception as e:
            logger.warning(f"Error scanning devices: {e}")
            return []

    def connect_device(self, device_mac: str) -> bool:
        """
        Connect to a Bluetooth HID device.

        Args:
            device_mac: MAC address of the device to connect to

        Returns:
            bool: True if connection was successful, False otherwise

        Raises:
            BluetoothError: If there's an error establishing the connection
        """
        try:
            self.bthid_srv = BluetoothHIDService(self.service_record, device_mac)
            self.connected_device = device_mac
            save_last_device(device_mac)
            return True
        except Exception as e:
            logger.warning(f"Failed to connect: {e}")
            self.bthid_srv = None
            self.connected_device = None
            return False

    def disconnect_device(self) -> None:
        """
        Disconnect the currently connected device.
        Cleans up the BluetoothHID service and resets connection state.
        """
        if self.bthid_srv:
            try:
                self.bthid_srv.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
            self.bthid_srv = None
            self.connected_device = None

    def get_last_device(self) -> Optional[str]:
        """
        Get the MAC address of the last connected device.

        Returns:
            str: MAC address of last connected device, or None if no previous connection
        """
        return get_last_device()
