import dbus
import dbus.service
import os
import socket
import logging
import resource
import time as time_module
import dbus.exceptions
from device_store import save_last_device

# Configure logging with microsecond precision
logging.basicConfig(
    format='%(asctime)s.%(msecs)06d [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    level=getattr(logging, os.environ.get('LOGLEVEL', 'INFO'))
)
logger = logging.getLogger('bthid')


def log_resource_usage():
    """Log memory usage if it has changed significantly"""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    current_mem = usage.ru_maxrss
    if not hasattr(log_resource_usage, 'last_mem'):
        log_resource_usage.last_mem = current_mem

    # Log if memory usage has increased by more than 10%
    if current_mem > log_resource_usage.last_mem * 1.1:
        logger.warning('Memory usage increased to %d KB (was %d KB)',
                       current_mem, log_resource_usage.last_mem)
        log_resource_usage.last_mem = current_mem


# Only log unique messages for these common events
class DuplicateFilter(logging.Filter):
    def __init__(self):
        self.last_log = {}

    def filter(self, record):
        # Allow through if not a duplicate in the last 5 seconds
        current_time = time_module.time()
        msg_key = (record.levelno, record.msg)
        if msg_key not in self.last_log or \
           current_time - self.last_log[msg_key] > 5:
            self.last_log[msg_key] = current_time
            return True
        return False


logger.addFilter(DuplicateFilter())


def get_default_adapter_address():
    """Get the MAC address of the default Bluetooth adapter"""
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    objects = manager.GetManagedObjects()

    for path, interfaces in objects.items():
        if "org.bluez.Adapter1" not in interfaces:
            continue
        adapter = dbus.Interface(bus.get_object("org.bluez", path), "org.bluez.Adapter1")
        properties = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
        address = properties.Get("org.bluez.Adapter1", "Address")
        return address

    raise RuntimeError("No Bluetooth adapter found")


class BluetoothHIDProfile(dbus.service.Object):
    _instance = None
    _bus = None
    _path = None

    def __new__(cls, bus, path):
        if cls._instance is None:
            cls._instance = super(BluetoothHIDProfile, cls).__new__(cls)
            cls._bus = bus
            cls._path = path
        return cls._instance

    def __init__(self, bus, path):
        if not hasattr(self, '_initialized'):
            try:
                super(BluetoothHIDProfile, self).__init__(bus, path)
                self.fd = -1
                self._initialized = True
            except Exception as e:
                logger.error(f"Failed to initialize BluetoothHIDProfile: {e}")
                raise

    @classmethod
    def cleanup(cls):
        """Clean up the singleton instance"""
        if cls._instance is not None:
            try:
                # Remove from D-Bus
                cls._instance.remove_from_connection()
                # Reset instance
                cls._instance = None
            except Exception as e:
                logger.error(f"Error cleaning up BluetoothHIDProfile: {e}")

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        try:
            if self.fd > 0:
                os.close(self.fd)
                self.fd = -1
        except Exception as e:
            logger.error(f"Error in Release: {e}")
            raise

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Cancel(self):
        try:
            if self.fd > 0:
                os.close(self.fd)
                self.fd = -1
        except Exception as e:
            logger.error(f"Error in Cancel: {e}")
            raise

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        try:
            logger.info(f"New connection request from {path}")
            self.fd = fd.take()
            logger.info("Connection established successfully")
        except Exception as e:
            logger.error(f"Failed to establish connection: {e}")
            if self.fd > 0:
                try:
                    os.close(self.fd)
                except OSError as close_err:
                    logger.error(f"Error closing file descriptor: {close_err}")
                self.fd = -1
            raise

    @dbus.service.method("org.bluez.Profile1",
                         in_signature="o", out_signature="")
    def RequestDisconnection(self, path):
        logger.info(f"Disconnection requested for {path}")
        try:
            if self.fd > 0:
                os.close(self.fd)
                self.fd = -1
            logger.info("Disconnection complete")
        except Exception as e:
            logger.error(f"Error during disconnection: {e}")
            raise


def error_handler(e):
    raise RuntimeError(str(e))


class BluetoothHIDService(object):
    PROFILE_PATH = "/org/bluez/bthid_profile"
    HOST = 0
    PORT = 1

    def __init__(self, service_record, MAC):
        logger.info("Initializing BluetoothHIDService...")
        # Initialize state tracking
        self.overflow_count = 0
        self.events_sent = 0
        self.connected_device = None
        self.last_stats_time = time_module.time()
        self.last_overflow_time = 0
        self.recovery_threshold = 0.1  # 100ms without overflow to consider recovered

        # Initialize HID state
        self.kbd_state = bytearray([
            0xA1,
            0x01,  # Report ID
            0x00,  # Modifier keys
            0x00,  # preserve
            0x00,  # 6 key
            0x00,
            0x00,
            0x00,
            0x00,
            0x00
        ])
        self.mouse_state = bytearray([
            0xA1,
            0x02,  # Report ID
            0x00,  # mouse button, in this byte XXXXX(button2)(button1)(button0)
            0x00,  # X displacement
            0x00,  # Y displacement
        ])
        self.P_CTRL = 0x0011
        self.P_INTR = 0x0013
        self.SELFMAC = MAC
        bus = dbus.SystemBus()
        bluez_obj = bus.get_object("org.bluez", "/org/bluez")
        manager = dbus.Interface(bluez_obj, "org.bluez.ProfileManager1")

        BluetoothHIDProfile(bus, self.PROFILE_PATH)
        opts = {
            "ServiceRecord": service_record,
            "Name": "BTKeyboardProfile",
            "RequireAuthentication": False,
            "RequireAuthorization": False,
            "Service": "MY BTKBD",
            "Role": "server"
        }

        sock_control = None
        sock_inter = None
        try:
            sock_control = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
            sock_control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            sock_inter = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
            sock_inter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Get device path from BlueZ
            bus = dbus.SystemBus()
            manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
            objects = manager.GetManagedObjects()
            device_path = None
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    props = interfaces["org.bluez.Device1"]
                    if props.get("Address") == MAC:
                        device_path = path
                        break

            if not device_path:
                raise RuntimeError(f"Device {MAC} not found")

            # Connect to device
            device = dbus.Interface(bus.get_object("org.bluez", device_path), "org.bluez.Device1")
            props = dbus.Interface(bus.get_object("org.bluez", device_path), "org.freedesktop.DBus.Properties")

            # Get adapter properties
            adapter_path = device_path[:device_path.rfind('/')]
            adapter = dbus.Interface(bus.get_object("org.bluez", adapter_path), "org.bluez.Adapter1")
            adapter_props = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
            adapter_addr = adapter_props.Get("org.bluez.Adapter1", "Address")
            self.SELFMAC = adapter_addr

            # Bind sockets to the correct adapter address
            sock_control.bind((self.SELFMAC, self.P_CTRL))
            sock_inter.bind((self.SELFMAC, self.P_INTR))

            # Check if device is already connected to another service
            try:
                if props.Get("org.bluez.Device1", "Connected"):
                    logger.info("Device is already connected, attempting to disconnect first...")
                    try:
                        device.Disconnect()
                        time_module.sleep(1)  # Wait for disconnect to complete
                    except dbus.exceptions.DBusException as e:
                        if "org.bluez.Error.Failed" not in str(e):  # Ignore if already disconnected
                            raise
            except dbus.exceptions.DBusException as e:
                logger.error(f"Error checking device connection state: {e}")
                raise

            # Connect via BlueZ
            try:
                logger.info(f"Connecting to device {MAC}...")
                device.Connect()

                # Wait for connection to establish
                max_wait = 5  # seconds
                start_time = time_module.time()
                while time_module.time() - start_time < max_wait:
                    if props.Get("org.bluez.Device1", "Connected"):
                        logger.info("Device connected via BlueZ")
                        break
                    time_module.sleep(0.1)
                else:
                    raise TimeoutError("BlueZ connection timed out")

                # Wait for BlueZ connection to stabilize
                time_module.sleep(1)
            except dbus.exceptions.DBusException as e:
                if "org.bluez.Error.AlreadyConnected" in str(e):
                    logger.info("Device already connected via BlueZ")
                else:
                    logger.error(f"BlueZ connection error: {e}")
                    raise

            # Register HID Profile after device is connected
            try:
                # Get ProfileManager1 interface
                profile_manager = dbus.Interface(
                    bus.get_object("org.bluez", "/org/bluez"),
                    "org.bluez.ProfileManager1"
                )

                # Try to unregister any existing profile first
                try:
                    profile_manager.UnregisterProfile(self.PROFILE_PATH)
                except dbus.exceptions.DBusException as e:
                    if "org.bluez.Error.DoesNotExist" not in str(e):
                        logger.warning(f"Error unregistering profile: {e}")

                # Register new profile with retry
                max_retries = 3
                retry_delay = 0.5
                last_error = None

                for attempt in range(max_retries):
                    try:
                        profile_manager.RegisterProfile(self.PROFILE_PATH, "00001124-0000-1000-8000-00805f9b34fb", opts)
                        logger.info("HID Profile registered successfully")
                        break
                    except dbus.exceptions.DBusException as e:
                        last_error = e
                        if "org.bluez.Error.AlreadyExists" in str(e):
                            logger.warning("HID Profile already registered, attempting to use existing profile")
                            break
                        elif attempt < max_retries - 1:
                            logger.warning(f"Profile registration attempt {attempt + 1} failed, retrying in {retry_delay}s")
                            time_module.sleep(retry_delay)
                        else:
                            logger.error(f"Failed to register HID Profile after {max_retries} attempts")
                            raise last_error

                # Wait for profile registration to take effect
                time_module.sleep(0.5)
            except Exception as e:
                logger.error(f"Failed to register HID Profile: {e}")
                raise

            # Set socket timeouts
            sock_control.settimeout(5)
            sock_inter.settimeout(5)

            try:
                sock_control.connect((MAC, self.P_CTRL))
                self.ccontrol = sock_control
                logger.info("Control channel connected")
            except socket.timeout:
                logger.error("Control channel connection timed out")
                raise
            except socket.error as e:
                logger.error(f"Failed to connect control channel: {e}")
                raise

            # Wait for control channel to stabilize
            time_module.sleep(0.5)

            try:
                sock_inter.connect((MAC, self.P_INTR))
                self.cinter = sock_inter
                logger.info("Interrupt channel connected")
            except socket.timeout:
                logger.error("Interrupt channel connection timed out")
                if hasattr(self, 'ccontrol'):
                    self.ccontrol.close()
                    delattr(self, 'ccontrol')
                raise
            except socket.error as e:
                logger.error(f"Failed to connect interrupt channel: {e}")
                if hasattr(self, 'ccontrol'):
                    self.ccontrol.close()
                    delattr(self, 'ccontrol')
                raise

            self.connected_device = MAC
            save_last_device(MAC)
            logger.info(f"Successfully connected and saved device {MAC}")
        except socket.error as e:
            logger.error(f"Socket error during connection: {e}")
            raise
        except dbus.exceptions.DBusException as e:
            logger.error(f"D-Bus error during connection: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            raise
        finally:
            # Clean up sockets if connection failed
            if not hasattr(self, 'ccontrol') and sock_control:
                try:
                    sock_control.close()
                except socket.error as e:
                    logger.error(f"Error closing control socket: {e}")
            if not hasattr(self, 'cinter') and sock_inter:
                try:
                    sock_inter.close()
                except socket.error as e:
                    logger.error(f"Error closing interrupt socket: {e}")

    def handle_key_press(self, keycode, modkeys):
        """Handle keyboard key press"""
        if keycode in modkeys:
            self.kbd_state[2] |= modkeys[keycode]
        else:
            for i in range(4, 10):
                if self.kbd_state[i] == 0x00:
                    self.kbd_state[i] = keycode
                    break
        self.send(bytes(self.kbd_state))

    def handle_key_release(self, keycode, modkeys):
        """Handle keyboard key release"""
        if keycode in modkeys:
            self.kbd_state[2] &= ~modkeys[keycode]
        else:
            for i in range(4, 10):
                if self.kbd_state[i] == keycode:
                    self.kbd_state[i] = 0x00
                    break
        self.send(bytes(self.kbd_state))

    def handle_button_press(self, button):
        """Handle mouse button press"""
        if button <= 3:
            self.mouse_state[2] |= 1 << (button - 1)
        self.send(bytes(self.mouse_state))

    def handle_button_release(self, button):
        """Handle mouse button release"""
        self.mouse_state[2] &= ~(1 << (button - 1))
        self.send(bytes(self.mouse_state))

    def handle_mouse_motion(self, x, y):
        """Handle mouse motion"""
        self.mouse_state[3] = x if x >= 0 else (256 + x)
        self.mouse_state[4] = y if y >= 0 else (256 + y)
        self.send(bytes(self.mouse_state))

    def cleanup(self):
        """Clean up resources and close connections"""
        logger.info("Cleaning up BluetoothHIDService...")
        try:
            if hasattr(self, 'ccontrol'):
                try:
                    self.ccontrol.close()
                except socket.error as e:
                    logger.error(f"Error closing control channel: {e}")

            if hasattr(self, 'cinter'):
                try:
                    self.cinter.close()
                except socket.error as e:
                    logger.error(f"Error closing interrupt channel: {e}")

            # Disconnect device via BlueZ
            try:
                if self.connected_device:
                    bus = dbus.SystemBus()
                    manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
                    objects = manager.GetManagedObjects()
                    for path, interfaces in objects.items():
                        if "org.bluez.Device1" in interfaces:
                            props = interfaces["org.bluez.Device1"]
                            if props.get("Address") == self.connected_device:
                                device = dbus.Interface(bus.get_object("org.bluez", path), "org.bluez.Device1")
                                try:
                                    device.Disconnect()
                                except dbus.exceptions.DBusException as e:
                                    if "org.bluez.Error.Failed" not in str(e):
                                        raise
                                break
            except Exception as e:
                logger.error(f"Error disconnecting device via BlueZ: {e}")

            # Clean up BluetoothHIDProfile
            BluetoothHIDProfile.cleanup()

            # Wait for cleanup to take effect
            time_module.sleep(1)

            # Unregister HID Profile
            try:
                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/org/bluez"),
                    "org.bluez.ProfileManager1"
                )

                try:
                    manager.UnregisterProfile(self.PROFILE_PATH)
                except dbus.exceptions.DBusException as e:
                    if "org.bluez.Error.DoesNotExist" not in str(e):
                        raise
            except Exception as e:
                logger.error(f"Error unregistering HID Profile: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            self.connected_device = None
            logger.info("Cleanup complete")

    def send(self, bytes_buf):
        """Send HID report with overflow detection"""
        current_time = time_module.time()
        try:
            # Try non-blocking send
            self.cinter.setblocking(False)
            send_start = time_module.time()
            bytes_sent = self.cinter.send(bytes_buf)
            send_time = time_module.time() - send_start

            if bytes_sent < len(bytes_buf):
                self.overflow_count += 1
                self.last_overflow_time = current_time
                if self.overflow_count == 1:  # Only log first occurrence
                    logger.warning("Buffer overflow detected - some events may be delayed")
            else:
                # Only consider buffer recovered after a period without overflow
                if self.overflow_count > 0 and (current_time - self.last_overflow_time) > self.recovery_threshold:
                    logger.info(f"Buffer recovered after {self.overflow_count} overflow events")
                    self.overflow_count = 0
                if send_time > 0.001:  # Log if send takes more than 1ms
                    logger.warning("Slow send operation: %.3fms", send_time * 1000)

            # Track successful send and update stats
            self.events_sent += 1
            if current_time - self.last_stats_time >= 1:
                logger.info("Events sent: %d", self.events_sent)
                self.events_sent = 0
                self.last_stats_time = current_time

        except socket.error as e:
            if e.errno == socket.EAGAIN or e.errno == socket.EWOULDBLOCK:
                self.overflow_count += 1
                self.last_overflow_time = current_time
                if self.overflow_count == 1:
                    logger.warning("Send buffer full - some events may be delayed")
            else:
                logger.error(f"Socket error: {e}")
        finally:
            # Reset to blocking mode
            self.cinter.setblocking(True)
