#!/usr/bin/python3

import sys
from BluetoothHID import BluetoothHIDService, get_default_adapter_address, logger
from evdev_xkb_map import evdev_xkb_map, modkeys
import keymap
from Xlib import X, display, Xutil
from dbus.mainloop.glib import DBusGMainLoop
from time import time

usbhid_map = {}
with open("keycode.txt") as f:
    for line in f.read().splitlines():
        if not line.startswith(";") and len(line) > 1:
            row = line.split(maxsplit=1)
            usbhid_keycode = int(row[0])
            usbhid_keyname = row[1]
            usbhid_map[usbhid_keycode] = usbhid_keyname


# Application window (only one)
class Window(object):
    def __init__(self, display):
        self.d = display
        self.objects = []

        # Find which screen to open the window on
        self.screen = self.d.screen()

        self.window = self.screen.root.create_window(
            50, 50, 640, 480, 2,
            self.screen.root_depth,
            X.InputOutput,
            X.CopyFromParent,

            # special attribute values
            background_pixel=self.screen.white_pixel,
            event_mask=(X.ExposureMask |
                        X.StructureNotifyMask |
                        X.ButtonPressMask |
                        X.ButtonReleaseMask |
                        X.Button1MotionMask |
                        X.KeyPressMask |
                        X.KeyReleaseMask),
            colormap=X.CopyFromParent,
        )

        self.gc = self.window.create_gc(
            foreground=self.screen.black_pixel,
            background=self.screen.white_pixel,
        )

        # Set some WM info
        self.WM_DELETE_WINDOW = self.d.intern_atom('WM_DELETE_WINDOW')
        self.WM_PROTOCOLS = self.d.intern_atom('WM_PROTOCOLS')

        self.window.set_wm_name('EmuBTHID')
        self.window.set_wm_icon_name('EmuBTHID')
        self.window.set_wm_protocols([self.WM_DELETE_WINDOW])
        self.window.set_wm_hints(flags=Xutil.StateHint,
                                 initial_state=Xutil.NormalState)

        self.window.set_wm_normal_hints(flags=(Xutil.PPosition | Xutil.PSize
                                               | Xutil.PMinSize),
                                        min_width=20,
                                        min_height=20)
        # Map the window, making it visible
        self.window.map()

    def grab(self):
        logger.debug("Input grabbed")
        self.window.grab_pointer(False, X.ButtonReleaseMask | X.ButtonPressMask | X.PointerMotionMask,
                                 X.GrabModeAsync, X.GrabModeAsync, self.window, X.NONE, X.CurrentTime)
        self.window.grab_keyboard(False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)

    def ungrab(self):
        logger.debug("Input ungrabbed")
        self.d.ungrab_pointer(X.CurrentTime)
        self.d.ungrab_keyboard(X.CurrentTime)

    # Main loop, handling events
    def loop(self, send_call_back):
        kbd_state = bytearray([
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
        mouse_state = bytearray([
            0xA1,
            0x02,  # Report ID
            0x00,  # mouse button, in this byte XXXXX(button2)(button1)(button0)
            0x00,  # X displacement
            0x00,  # Y displacement
        ])
        expose_count = 0
        grab_trigger_hint = ('KEY_LEFTCTRL', 'KEY_LEFTALT', 'KEY_LEFTSHIFT', 'KEY_B')
        grab_trigger = set(keymap.keytable[k] for k in grab_trigger_hint)
        grab_cnt = len(grab_trigger)
        grabbed = False
        geometry = self.window.get_geometry()
        prev_x = None
        prev_y = None
        hint_x = geometry.width // 5
        hint_y = geometry.height // 5
        hint_str = 'Press Ctrl+Alt+Shift+B to   Grab'.encode()
        last_stats_time = time()
        events_received = 0
        while 1:
            # Monitor stats every second
            current_time = time()
            if current_time - last_stats_time >= 1:
                pending = self.d.pending_events()
                logger.debug("Events received/pending: %d/%d",
                             events_received, pending)
                events_received = 0
                last_stats_time = current_time

            e = self.d.next_event()
            events_received += 1

            # Window has been destroyed, quit
            if e.type == X.DestroyNotify:
                logger.debug("Window destroyed")
                sys.exit(0)

            if e.type == X.KeyPress:
                usbhid_keycode = evdev_xkb_map[e.detail]
                if usbhid_keycode in modkeys:
                    kbd_state[2] |= modkeys[usbhid_keycode]
                else:
                    for i in range(4, 10):
                        if kbd_state[i] == 0x00:
                            kbd_state[i] = usbhid_keycode
                            break
                send_call_back(bytes(kbd_state))
                if usbhid_keycode in grab_trigger:
                    grab_cnt -= 1
                    if (grab_cnt == 0):
                        if grabbed:
                            self.ungrab()
                            grabbed = False
                            hint_str = 'Press Ctrl+Alt+Shift+B to   Grab'.encode()
                            self.window.image_text(self.gc, hint_x, hint_y, hint_str)
                        else:
                            self.grab()
                            grabbed = True
                            hint_str = 'Press Ctrl+Alt+Shift+B to UnGrab'.encode()
                            self.window.image_text(self.gc, hint_x, hint_y, hint_str)

            if e.type == X.KeyRelease:
                usbhid_keycode = evdev_xkb_map[e.detail]
                if usbhid_keycode in modkeys:
                    kbd_state[2] &= ~modkeys[usbhid_keycode]
                else:
                    for i in range(4, 10):
                        if kbd_state[i] == usbhid_keycode:
                            kbd_state[i] = 0x00
                            break
                if usbhid_keycode in grab_trigger:
                    grab_cnt += 1
                send_call_back(bytes(kbd_state))

            # Some part of the window has been exposed,
            # redraw all the objects.
            if e.type == X.Expose:
                expose_count += 1
                logger.debug("Window exposed")
                geometry = self.window.get_geometry()
                hint_x = geometry.width // 5
                hint_y = geometry.height // 5
                self.window.image_text(self.gc, hint_x, hint_y, hint_str)

            # Left button pressed, start to draw
            if e.type == X.ButtonPress:
                if (e.detail <= 3):
                    mouse_state[2] |= 1 << (e.detail - 1)
                send_call_back(bytes(mouse_state))

            if e.type == X.ButtonRelease:
                mouse_state[2] &= ~(1 << (e.detail - 1))
                send_call_back(bytes(mouse_state))

            if e.type == X.ClientMessage:
                if e.client_type == self.WM_PROTOCOLS:
                    fmt, data = e.data
                    if fmt == 32 and data[0] == self.WM_DELETE_WINDOW:
                        sys.exit(0)
            if e.type == X.MotionNotify:
                if prev_x is not None and prev_y is not None:
                    # Start with current movement
                    total_x = e.event_x - prev_x
                    total_y = e.event_y - prev_y
                    events_merged = 1

                    # Check for additional motion events
                    while self.d.pending_events() > 0:
                        next_e = self.d.next_event()
                        if next_e.type == X.MotionNotify:
                            total_x += next_e.event_x - e.event_x
                            total_y += next_e.event_y - e.event_y
                            e = next_e
                            events_merged += 1
                        else:
                            # Put non-motion event back in queue
                            self.d.put_back_event(next_e)
                            break

                    # Scale movement based on number of events merged
                    # This helps maintain responsiveness during high event rates
                    scale = 2.0 if events_merged <= 2 else (1.0 + (1.0 / events_merged))
                    pos_x = max(-128, min(int(total_x * scale), 127))
                    pos_y = max(-128, min(int(total_y * scale), 127))

                    # Update mouse state and send
                    mouse_state[3] = pos_x if pos_x >= 0 else (256 + pos_x)
                    mouse_state[4] = pos_y if pos_y >= 0 else (256 + pos_y)
                    send_call_back(bytes(mouse_state))

                    if events_merged > 1:
                        logger.debug("Merged %d mouse events, displacement: (%d,%d), scale: %.2f",
                                     events_merged, pos_x, pos_y, scale)
                if e.event_x == geometry.width - 1:
                    self.window.warp_pointer(1, e.event_y)
                    prev_x = 1
                elif e.event_x == 0:
                    self.window.warp_pointer(geometry.width - 2, e.event_y)
                    prev_x = geometry.width - 2
                else:
                    prev_x = e.event_x
                if e.event_y == geometry.height - 1:
                    self.window.warp_pointer(e.event_x, 1)
                    prev_y = 1
                elif e.event_y == 0:
                    self.window.warp_pointer(e.event_x, geometry.height - 2)
                    prev_y = geometry.height - 2
                else:
                    prev_y = e.event_y


if __name__ == '__main__':
    DBusGMainLoop(set_as_default=True)
    service_record = open("sdp_record_kbd.xml").read()
    d = display.Display()
    d.change_keyboard_control(auto_repeat_mode=X.AutoRepeatModeOff)
    try:
        controller_mac = get_default_adapter_address()
        logger.info("Using Bluetooth controller: %s", controller_mac)
        bthid_srv = BluetoothHIDService(service_record, controller_mac)
        Window(d).loop(bthid_srv.send)
    finally:
        d.change_keyboard_control(auto_repeat_mode=X.AutoRepeatModeOn)
        d.get_keyboard_control()
        d.ungrab_keyboard(X.CurrentTime)
        d.ungrab_pointer(X.CurrentTime)
        logger.debug("Exit")
