"""
Protocol-specific constants for HID and Bluetooth.
"""

# HID Report IDs
HID_REPORT_KEYBOARD = 0x01
HID_REPORT_MOUSE = 0x02

# Bluetooth PSM values
BT_CTRL_PSM = 0x0011  # Control channel PSM
BT_INTR_PSM = 0x0013  # Interrupt channel PSM

# HID Protocol UUIDs
HID_UUID = "00001124-0000-1000-8000-00805f9b34fb"

# Mouse Protocol Limits
MOUSE_MIN_MOTION = -128
MOUSE_MAX_MOTION = 127
