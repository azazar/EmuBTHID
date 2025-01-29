"""
System tray UI management.
"""

from typing import Callable, Dict, Optional
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon, QColor
from logging_config import logger


class TrayUI:
    """
    System tray UI manager that handles the application's presence in the system tray.
    Provides device connection status and menu options.
    """

    def __init__(self, create_icon_func: Callable[[str, QColor, int], QIcon]):
        """
        Initialize the system tray UI.

        Args:
            create_icon_func: Function to create tray icons with specified text and color
        """
        self.create_icon = create_icon_func
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.create_icon("⛓️"))
        self.tray.setToolTip("EmuBTHID - Scanning...")
        self.tray.setVisible(True)

        self.menu = QMenu()
        self.device_actions: Dict[str, QAction] = {}
        self.tray.setContextMenu(self.menu)

    def set_icon_state(self, state: str) -> None:
        """
        Update the system tray icon based on connection state.

        Args:
            state: One of 'connected', 'available', or 'inactive'
        """
        colors = {
            'connected': QColor("#00FF00"),  # Green
            'available': QColor("#0000FF"),  # Blue
            'inactive': QColor("#808080"),   # Gray
        }
        if state not in colors:
            logger.warning(f"Invalid icon state: {state}")
            state = 'inactive'
        self.tray.setIcon(self.create_icon("⛓️", colors[state]))

    def set_tooltip(self, text: str) -> None:
        """
        Update the system tray icon tooltip text.

        Args:
            text: New tooltip text to display
        """
        self.tray.setToolTip(text)

    def update_devices(
            self,
            devices: list[tuple[str, str]],
            connected_device: Optional[str],
            on_connect: Callable[[str], None]
    ) -> None:
        """
        Update the system tray menu with available devices.

        Args:
            devices: List of (name, mac_address) tuples for available devices
            connected_device: MAC address of currently connected device, if any
            on_connect: Callback function to handle device connection requests
        """
        # Clear existing items
        for action in self.device_actions.values():
            self.menu.removeAction(action)
        self.device_actions.clear()

        # Add devices
        for name, addr in devices:
            action = QAction(f"{name} ({addr})", parent=self.menu)
            action.triggered.connect(lambda checked, a=addr: on_connect(a))

            if addr == connected_device:
                action.setCheckable(True)
                action.setChecked(True)

            self.menu.insertAction(
                self.menu.actions()[0] if self.menu.actions() else None,
                action
            )
            self.device_actions[addr] = action

    def add_exit_action(self, callback: Callable[[], None]) -> None:
        """
        Add an exit option to the system tray menu.

        Args:
            callback: Function to call when exit is selected
        """
        self.menu.addSeparator()
        exit_action = QAction("Exit", parent=self.menu)
        exit_action.triggered.connect(callback)
        self.menu.addAction(exit_action)
