#!/usr/bin/python3

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QFont, QColor
from PyQt5.QtCore import QTimer, Qt
from Xlib import display
from dbus.mainloop.glib import DBusGMainLoop
from BluetoothHID import logger
from tray_ui import TrayUI
from device_manager import DeviceManager
from keyboard_manager import KeyboardManager
from input.mouse_manager import MouseManager

from constants.input_constants import (
    ICON_SIZE,
    DEVICE_SCAN_INTERVAL,
    EVENT_CHECK_INTERVAL
)


def create_text_icon(text: str, color: QColor = QColor("#808080"), size: int = ICON_SIZE) -> QIcon:
    """Create an icon from text with specified color"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setPen(color)
    font = QFont()
    font.setPointSize(int(size * 0.8))  # Set font size to 80% of icon size
    painter.setFont(font)

    # Draw text centered
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()

    return QIcon(pixmap)


class BTHIDTrayApp:
    """Main application class that manages the system tray UI and Bluetooth HID functionality."""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # Initialize D-Bus
        DBusGMainLoop(set_as_default=True)

        # Initialize X11 display
        self.display = display.Display()
        self.root = self.display.screen().root

        # Initialize managers
        self.tray_ui = TrayUI(create_text_icon)
        self.device_mgr = DeviceManager()
        self.keyboard_mgr = KeyboardManager(self.display, self.root)
        self.mouse_manager = None

        # Setup UI
        self.tray_ui.add_exit_action(self.cleanup_and_exit)

        # Setup keyboard
        if not self.keyboard_mgr.setup():
            logger.error("Failed to setup keyboard manager")
            sys.exit(1)

        # Initial device scan
        self.scan_devices()

    def scan_devices(self) -> None:
        """
        Scan for available Bluetooth HID devices and update the system tray UI.
        Updates the tray icon state based on device availability and connection status.
        """
        devices = self.device_mgr.scan_devices()
        self.tray_ui.update_devices(
            devices,
            self.device_mgr.connected_device,
            self.connect_to_device
        )

        # Update UI state
        if self.device_mgr.connected_device:
            self.tray_ui.set_icon_state('connected')
        elif devices:
            self.tray_ui.set_icon_state('available')
        else:
            self.tray_ui.set_icon_state('inactive')

    def connect_to_device(self, device_mac: str) -> bool:
        """
        Attempt to connect to a Bluetooth HID device.

        Args:
            device_mac: MAC address of the device to connect to

        Returns:
            bool: True if connection was successful, False otherwise
        """
        logger.info(f"Attempting to connect to device {device_mac}")

        # Disconnect current device if any
        if self.device_mgr.connected_device:
            self.disconnect_current()

        # Connect new device
        if self.device_mgr.connect_device(device_mac):
            # Start input handling
            if self.keyboard_mgr.start_input_grab(self.device_mgr.bthid_srv):
                # Start mouse manager
                self.mouse_manager = MouseManager(self.device_mgr.bthid_srv)
                self.mouse_manager.start()

                # Update UI
                self.scan_devices()
                self.tray_ui.set_tooltip(f"EmuBTHID - Connected to {device_mac}")
                return True

        return False

    def disconnect_current(self) -> None:
        """
        Disconnect the currently connected device and update UI state.
        Stops input grabbing and updates the system tray icon.
        """
        # Stop input handlers
        self.keyboard_mgr.stop_input_grab()
        if self.mouse_manager:
            self.mouse_manager.stop()
            self.mouse_manager = None

        # Disconnect device
        self.device_mgr.disconnect_device()
        self.scan_devices()
        self.tray_ui.set_tooltip("EmuBTHID - Scanning...")

    def handle_hotkey(self) -> None:
        """
        Handle Win+G hotkey press event.
        Toggles connection state - disconnects if connected, connects to last device if disconnected.
        """
        if self.device_mgr.connected_device:
            logger.info("Hotkey triggered disconnect")
            self.disconnect_current()
        else:
            last_device = self.device_mgr.get_last_device()
            if last_device:
                logger.info(f"Hotkey triggered connect to {last_device}")
                self.connect_to_device(last_device)

    def check_events(self) -> None:
        """
        Check for X11 events and handle them appropriately.
        Processes keyboard events and handles hotkey combinations.
        Periodically logs input statistics.
        """
        try:
            while self.display.pending_events():
                event = self.display.next_event()
                result = self.keyboard_mgr.handle_event(event, self.device_mgr.bthid_srv)
                if result == "hotkey":
                    self.handle_hotkey()

            # Log stats periodically
            self.keyboard_mgr.log_stats()

        except Exception as e:
            logger.error(f"Error handling events: {e}")

    def cleanup_and_exit(self) -> None:
        """
        Clean up resources and exit the application.
        Disconnects devices, releases input grabs, and closes X11 display.
        """
        self.disconnect_current()
        self.keyboard_mgr.cleanup()
        self.display.close()
        self.app.quit()

    def run(self) -> int:
        """
        Run the application main loop.

        Sets up periodic device scanning and event checking timers.

        Returns:
            int: Application exit code
        """
        # Setup periodic device scanning
        timer = QTimer()
        timer.timeout.connect(self.scan_devices)
        timer.start(DEVICE_SCAN_INTERVAL)

        # Setup event checking
        event_timer = QTimer()
        event_timer.timeout.connect(self.check_events)
        event_timer.start(EVENT_CHECK_INTERVAL)

        return self.app.exec_()


if __name__ == '__main__':
    app = BTHIDTrayApp()
    sys.exit(app.run())
