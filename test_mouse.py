#!/usr/bin/env python3
"""
Mouse input test utility.
Helps verify mouse device detection and shows real-time mouse events.

Usage:
1. Run the script: sudo python3 test_mouse.py
2. Move your mouse around - you should see X/Y coordinates change
3. Click mouse buttons - you should see button press/release events
4. Press Ctrl+C to exit

The script will:
- List all input devices
- Show why each device is accepted/rejected as a mouse
- Display real-time mouse events when a device is found
"""

import evdev
from evdev import ecodes, InputDevice
import sys
import select
import fcntl
import os
import stat
from typing import List

# IOCTL commands
try:
    # Try to get EVIOCGRAB from evdev if available
    from evdev.device import EVIOCGRAB
except ImportError:
    # Fall back to our own definition
    EVIOCGRAB = 1074021776  # 0x40044590


def test_mouse_device(device: InputDevice) -> bool:
    """
    Test if a device is a mouse by checking its capabilities.

    Args:
        device: Input device to test

    Returns:
        bool: True if device appears to be a mouse
    """
    caps = device.capabilities(verbose=True)
    print(f"  Raw capabilities: {caps}")

    # Check for mouse capabilities
    has_movement = False
    has_buttons = False

    # Check relative movement (X/Y)
    if ('EV_REL', evdev.ecodes.EV_REL) in caps:
        rel_caps = caps[('EV_REL', evdev.ecodes.EV_REL)]
        print(f"  Movement axes: {rel_caps}")
        # Look for REL_X (0) and REL_Y (1)
        rel_names = []
        for cap in rel_caps:
            if isinstance(cap[0], (list, tuple)):
                rel_names.extend(cap[0])
            else:
                rel_names.append(cap[0])
        print(f"  Movement names: {rel_names}")
        has_x = 'REL_X' in rel_names
        has_y = 'REL_Y' in rel_names
        has_movement = has_x and has_y
        print(f"  Has X axis: {has_x}")
        print(f"  Has Y axis: {has_y}")

    # Check mouse buttons
    if ('EV_KEY', evdev.ecodes.EV_KEY) in caps:
        key_caps = caps[('EV_KEY', evdev.ecodes.EV_KEY)]
        print(f"  Key capabilities: {key_caps}")
        # Look for any mouse button names
        key_names = []
        for cap in key_caps:
            if isinstance(cap[0], (list, tuple)):
                key_names.extend(cap[0])
            else:
                key_names.append(cap[0])
        print(f"  Button names: {key_names}")
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
        has_buttons = len(found_buttons) > 0
        if found_buttons:
            print(f"  Found mouse buttons: {', '.join(found_buttons)}")
        else:
            print("  No mouse buttons found")

    # Report capabilities
    if has_movement:
        print("  Has movement (REL_X/REL_Y)")
    if has_buttons:
        print("  Has mouse buttons")
    if has_movement and not has_buttons:
        print("  Note: Has movement but no mouse buttons")
    if has_buttons and not has_movement:
        print("  Note: Has mouse buttons but no movement")

    # A device is useful if it has either movement or buttons
    is_useful = has_movement or has_buttons
    print(f"  Can use device: {is_useful} (movement={has_movement}, buttons={has_buttons})")
    return is_useful


def find_mouse_devices() -> List[InputDevice]:
    """
    Find all mouse devices in the system.

    Returns:
        List of mouse input devices
    """
    print("Scanning input devices...")
    devices = [InputDevice(path) for path in evdev.list_devices()]

    print(f"\nFound {len(devices)} input devices:")
    mouse_devices = []

    for device in devices:
        print(f"\nTesting device: {device.name}")
        print(f"  Path: {device.path}")
        print(f"  Info: bus=0x{device.info.bustype:04x}, vendor=0x{device.info.vendor:04x}, product=0x{device.info.product:04x}")

        if test_mouse_device(device):
            mouse_devices.append(device)

    return mouse_devices


def monitor_mouse(mouse: InputDevice) -> None:
    """
    Monitor and display mouse events in real-time.

    Args:
        mouse: Mouse input device to monitor
    """
    print(f"\nMonitoring mouse: {mouse.name}")
    print(f"Device path: {mouse.path}")
    try:
        print(f"File descriptor: {mouse.fd}")

        # Test device access and status
        flags = fcntl.fcntl(mouse.fd, fcntl.F_GETFL)
        print(f"File descriptor flags: 0x{flags:x}")
        is_nonblocking = bool(flags & os.O_NONBLOCK)
        print(f"Non-blocking mode: {is_nonblocking}")
        # Check both path and fd stats
        path_stat = os.stat(mouse.path)
        fd_stat = os.fstat(mouse.fd)
        print(f"Device path mode: {stat.filemode(path_stat.st_mode)} (0o{path_stat.st_mode:o})")
        print(f"Device fd mode: {stat.filemode(fd_stat.st_mode)} (0o{fd_stat.st_mode:o})")
        print(f"Device inode: {fd_stat.st_ino}")
        print(f"Device type: {'Character device' if stat.S_ISCHR(fd_stat.st_mode) else 'Other'}")
        readable = os.access(mouse.path, os.R_OK)
        writable = os.access(mouse.path, os.W_OK)
        print(f"Device access - read: {readable}, write: {writable}")

        # Try to grab device
        try:
            # First try evdev's grab() if available
            if hasattr(mouse, 'grab'):
                mouse.grab()
                print("Successfully grabbed device using evdev grab()")
            else:
                # Fall back to direct IOCTL
                fcntl.ioctl(mouse.fd, EVIOCGRAB, 1)
                print("Successfully grabbed device using EVIOCGRAB")
        except Exception as e:
            print(f"Error grabbing device: {e}")
            print("Continuing without exclusive access")
    except Exception as e:
        print(f"Error with device: {e}")
        print("Continuing without exclusive access")
    print("Move mouse or click buttons (Ctrl+C to exit)")

    # Button name mapping
    buttons = {
        ecodes.BTN_LEFT: "Left",
        ecodes.BTN_MOUSE: "Left",  # Alias for BTN_LEFT
        ecodes.BTN_RIGHT: "Right",
        ecodes.BTN_MIDDLE: "Middle",
        ecodes.BTN_SIDE: "Side",
        ecodes.BTN_EXTRA: "Extra",
        ecodes.BTN_FORWARD: "Forward",
        ecodes.BTN_BACK: "Back"
    }

    # Test device readiness and events
    print("\nTesting device readiness...")
    try:
        # Try to set non-blocking mode
        old_flags = fcntl.fcntl(mouse.fd, fcntl.F_GETFL)
        fcntl.fcntl(mouse.fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)
        new_flags = fcntl.fcntl(mouse.fd, fcntl.F_GETFL)
        is_nonblocking = bool(new_flags & os.O_NONBLOCK)
        print(f"Set non-blocking mode (before: 0x{old_flags:x}, after: 0x{new_flags:x}, success: {is_nonblocking})")
    except Exception as e:
        print(f"Error setting non-blocking mode: {e}")

    r, w, x = select.select([mouse.fd], [], [], 0.1)
    if r:
        print("Device is ready for reading")
    else:
        print("Warning: Device not ready for reading")

    # Monitor events using async read loop
    print("\nWaiting for events (press Ctrl+C to exit)...")
    try:
        # Use evdev's async read loop
        for event in mouse.async_read_loop():
            event_type = ecodes.EV[event.type] if event.type in ecodes.EV else f"Unknown({event.type})"
            event_code = None
            if event.type == ecodes.EV_REL:
                event_code = ecodes.REL[event.code] if event.code in ecodes.REL else f"Unknown({event.code})"
            elif event.type == ecodes.EV_KEY:
                event_code = ecodes.KEY[event.code] if event.code in ecodes.KEY else f"Unknown({event.code})"
            elif event.type == ecodes.EV_SYN:
                event_code = ecodes.SYN[event.code] if event.code in ecodes.SYN else f"Unknown({event.code})"
            else:
                event_code = f"code={event.code}"
            print(f"Event: type={event_type}, code={event_code}, value={event.value}")

            # Skip SYN events for output
            if event.type == ecodes.EV_SYN:
                continue
            if event.type == ecodes.EV_REL:
                if event.code == ecodes.REL_X:
                    print(f"X: {event.value:4d}", end=' ')
                elif event.code == ecodes.REL_Y:
                    print(f"Y: {event.value:4d}", end=' ')
                print()
            elif event.type == ecodes.EV_KEY:
                if event.code in buttons:
                    btn = buttons[event.code]
                    state = "Pressed" if event.value == 1 else "Released"
                    print(f"{btn} button {state}")
    except Exception as e:
        print(f"Error reading events: {e}")


def main() -> None:
    """Main entry point."""
    try:
        mouse_devices = find_mouse_devices()

        if not mouse_devices:
            print("\nNo usable mouse devices found!")
            sys.exit(1)

        # Find devices with movement capabilities
        movement_devices = []
        for device in mouse_devices:
            rel_caps = device.capabilities(verbose=True)[('EV_REL', evdev.ecodes.EV_REL)]
            rel_names = []
            for cap in rel_caps:
                if isinstance(cap[0], (list, tuple)):
                    rel_names.extend(cap[0])
                else:
                    rel_names.append(cap[0])
            if 'REL_X' in rel_names and 'REL_Y' in rel_names:
                movement_devices.append(device)

        # Find devices with button capabilities
        button_devices = []
        for device in mouse_devices:
            if ('EV_KEY', evdev.ecodes.EV_KEY) in device.capabilities(verbose=True):
                key_caps = device.capabilities(verbose=True)[('EV_KEY', evdev.ecodes.EV_KEY)]
                key_names = []
                for cap in key_caps:
                    if isinstance(cap[0], (list, tuple)):
                        key_names.extend(cap[0])
                    else:
                        key_names.append(cap[0])
                if any(name in ['BTN_LEFT', 'BTN_MOUSE'] for name in key_names):
                    button_devices.append(device)

        print(f"\nFound {len(mouse_devices)} usable mouse devices:")
        print(f"- {len(movement_devices)} devices with movement")
        print(f"- {len(button_devices)} devices with buttons")

        # Choose monitoring device
        print("\nAvailable movement devices:")
        for i, device in enumerate(movement_devices):
            print(f"{i+1}. {device.name} ({device.path})")

        print("\nAvailable button devices:")
        for i, device in enumerate(button_devices):
            print(f"{i+1}. {device.name} ({device.path})")

        # Find devices that appear in both lists
        combined_devices = []
        for mdev in movement_devices:
            for bdev in button_devices:
                if mdev.path == bdev.path:  # Compare paths instead of devices
                    combined_devices.append(mdev)
                    break

        if combined_devices:
            # Try to find HARPOON device first as it's the actual mouse
            harpoon = next((d for d in combined_devices if "HARPOON" in d.name), None)
            if harpoon:
                monitor_device = harpoon
                print(f"\nUsing HARPOON device: {monitor_device.name} ({monitor_device.path})")
            else:
                monitor_device = combined_devices[0]
                print(f"\nUsing combined movement+buttons device: {monitor_device.name} ({monitor_device.path})")
        else:
            monitor_device = movement_devices[0] if movement_devices else mouse_devices[0]
            print(f"\nUsing movement-only device: {monitor_device.name} ({monitor_device.path})")

        monitor_mouse(monitor_device)

    except KeyboardInterrupt:
        print("\nExiting...")
        try:
            monitor_device.ungrab()
            print("Released device grab")
        except Exception as e:
            print(f"Error releasing device grab: {e}")
    except PermissionError:
        print("\nError: Need root permissions to access input devices")
        print("Run with: sudo python3 test_mouse.py")


if __name__ == '__main__':
    main()
