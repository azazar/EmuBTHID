import dbus
import dbus.service
import os
import socket
import logging
from time import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger('bthid')


# Only log unique messages for these common events
class DuplicateFilter(logging.Filter):
    def __init__(self):
        self.last_log = {}

    def filter(self, record):
        # Allow through if not a duplicate in the last 5 seconds
        current_time = time()
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
    def __init__(self, bus, path):
        super(BluetoothHIDProfile, self).__init__(bus, path)
        self.fd = -1

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        raise NotImplementedError("Release")

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Cancel(self):
        raise NotImplementedError("Cancel")

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        self.fd = fd.take()
        logger.info("New Connection from (%s, %d)", path, self.fd)
        for k, v in properties.items():
            if k == "Version" or k == "Features":
                logger.info("    %s = 0x%04x", k, v)
            else:
                logger.info("    %s = %s", k, v)

    @dbus.service.method("org.bluez.Profile1",
                         in_signature="o", out_signature="")
    def RequestDisconnection(self, path):
        logger.info("RequestDisconnection(%s)", path)

        if (self.fd > 0):
            os.close(self.fd)
            self.fd = -1


def error_handler(e):
    raise RuntimeError(str(e))


class BluetoothHIDService(object):
    PROFILE_PATH = "/org/bluez/bthid_profile"
    HOST = 0
    PORT = 1

    def __init__(self, service_record, MAC):
        # Initialize state tracking
        self.overflow_count = 0
        self.last_send_time = time()
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

        sock_control = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        sock_control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock_inter = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        sock_inter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock_control.bind((self.SELFMAC, self.P_CTRL))
        sock_inter.bind((self.SELFMAC, self.P_INTR))
        manager.RegisterProfile(self.PROFILE_PATH, "00001124-0000-1000-8000-00805f9b34fb", opts)
        logger.info("HID Profile registered")
        sock_control.listen(1)
        sock_inter.listen(1)
        logger.info("Waiting for connection at controller %s (verify MAC in bluetoothctl)", MAC)
        self.ccontrol, cinfo = sock_control.accept()
        logger.info("Control channel connected to %s", cinfo[self.HOST])
        self.cinter, cinfo = sock_inter.accept()
        logger.info("Interrupt channel connected to %s", cinfo[self.HOST])

    def send(self, bytes_buf):
        try:
            # Try to send with non-blocking socket
            self.cinter.setblocking(False)
            bytes_sent = self.cinter.send(bytes_buf)

            if bytes_sent < len(bytes_buf):
                self.overflow_count += 1
                if self.overflow_count == 1:  # Only log first occurrence
                    logger.warning("Buffer overflow detected - some events may be delayed")
            else:
                if self.overflow_count > 0:
                    logger.info(f"Buffer recovered after {self.overflow_count} overflow events")
                    self.overflow_count = 0

            # Track successful send
            self.last_send_time = time()

        except socket.error as e:
            if e.errno == socket.EAGAIN or e.errno == socket.EWOULDBLOCK:
                self.overflow_count += 1
                if self.overflow_count == 1:
                    logger.warning("Send buffer full - some events may be delayed")
            else:
                logger.error(f"Socket error: {e}")
        finally:
            # Reset to blocking mode
            self.cinter.setblocking(True)
