"""
Device configuration storage following XDG Base Directory Specification.
"""

import os
import json
from typing import Optional
from pathlib import Path
from config import APP_NAME


def get_config_dir() -> Path:
    """
    Get XDG config directory following the specification:
    - Use $XDG_CONFIG_HOME if set
    - Otherwise use ~/.config

    Returns:
        Path: XDG config directory for this application
    """
    xdg_config = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config:
        base_config = Path(xdg_config)
    else:
        base_config = Path.home() / '.config'

    return base_config / APP_NAME


def save_last_device(device_mac: str) -> None:
    """
    Save the MAC address of the last connected device.

    Args:
        device_mac: Bluetooth MAC address to save

    Raises:
        OSError: If there's an error creating the config directory or writing the file
        json.JSONEncodeError: If there's an error encoding the data
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    config_file = config_dir / 'last_device.json'
    with open(config_file, 'w') as f:
        json.dump({'mac': device_mac}, f)


def get_last_device() -> Optional[str]:
    """
    Get the MAC address of the last connected device.

    Returns:
        str: MAC address if found
        None: If no previous device was saved or there was an error reading the file

    Raises:
        json.JSONDecodeError: If the config file contains invalid JSON
    """
    config_file = get_config_dir() / 'last_device.json'
    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
            return data.get('mac')
    except FileNotFoundError:
        return None
