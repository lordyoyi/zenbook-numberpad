#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""NumberPad daemon for the ASUS Zenbook 14 UX3405CA (PixArt ASUP1415 093A:300C).

Hold the top-right icon to toggle the NumberPad. While it is on, taps on the
grid type keys, drags and multi-finger gestures still move the pointer, and a
tap on the top-left icon cycles the backlight brightness.

No dependencies: evdev/uinput/hidraw are driven with plain ioctls. Needs root
(hidraw feature report + uinput + EVIOCGRAB). Run with --debug to log taps.
"""
import fcntl
import glob
import os
import select
import signal
import struct
import sys
import time

# ---- tunables ---------------------------------------------------------------
HID_ID = "0018:093A:300C"
TOUCHPAD_NAME = "ASUP1415:00 093A:300C Touchpad"

HOLD_SECONDS = 0.6        # hold on the top-right icon to toggle
TAP_MAX_SECONDS = 0.5     # longer stationary touches type nothing
MOVE_THRESHOLD = 120      # device units (pad is 3996 x 2242); beyond this a touch is a pointer drag
ICON_W, ICON_H = 300, 250  # corner icon hit boxes
# grid margins inside the pad, device units
TOP, BOTTOM, LEFT, RIGHT = 200, 80, 200, 200

BRIGHTNESS = [2, 4, 6, 8]  # levels cycled by the left icon (hardware has 1..8)
LED_SYSFS = "/sys/class/leds/asus::numberpad/brightness"  # present with the hid-multitouch patch

# ---- linux input constants --------------------------------------------------
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
ABS_X, ABS_Y = 0x00, 0x01
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39
BTN_LEFT, BTN_TOUCH = 0x110, 0x14A
BTN_TOOL = [0x145, 0x14D, 0x14E, 0x14F, 0x148]  # finger, double, triple, quad, quint
INPUT_PROP_POINTER, INPUT_PROP_BUTTONPAD = 0, 2
KEY_LEFTSHIFT, KEY_5 = 42, 6

# Top-row digits and KEY_DOT rather than KP_* so the result does not depend on
# NumLock. The operators use KP_* codes, which are NumLock-independent.
_D = {str(n): c for n, c in zip("1234567890", range(2, 12))}
BKSP, SLASH, STAR, MINUS, PLUS, DOT, ENTER, EQUAL, PERCENT = 14, 98, 55, 74, 78, 52, 96, 117, "percent"
KEYS = [
    [_D["7"], _D["8"], _D["9"], SLASH, BKSP],
    [_D["4"], _D["5"], _D["6"], STAR, BKSP],   # backspace is one tall key spanning two rows
    [_D["1"], _D["2"], _D["3"], MINUS, PERCENT],
    [_D["0"], DOT, ENTER, PLUS, EQUAL],
]

EVENT = struct.Struct("llHHi")
EVIOCGRAB = 0x40044590


def EVIOCGABS(axis):
    return 0x80184540 + axis


UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
UI_DEV_SETUP, UI_ABS_SETUP = 0x405C5503, 0x401C5504
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT, UI_SET_PROPBIT = 0x40045564, 0x40045565, 0x40045567, 0x4004556E

DEBUG = "--debug" in sys.argv


def log(*a):
    if DEBUG:
        print(*a, flush=True)


# ---- device discovery -------------------------------------------------------
def find_event_node():
    name = None
    for line in open("/proc/bus/input/devices"):
        if line.startswith("N:"):
            name = line.split('"')[1]
        elif line.startswith("H:") and name == TOUCHPAD_NAME:
            for tok in line.split("=", 1)[1].split():
                if tok.startswith("event"):
                    return "/dev/input/" + tok
    sys.exit(f"touchpad '{TOUCHPAD_NAME}' not found")


def find_hidraw():
    for dev in glob.glob(f"/sys/bus/hid/devices/{HID_ID}.*/hidraw/hidraw*"):
        return "/dev/" + os.path.basename(dev)
    sys.exit(f"no hidraw node for {HID_ID}")


# ---- backlight --------------------------------------------------------------
class Backlight:
    """Level 0 is off, 1..8 on. Uses the kernel LED class device when the
    patched hid-multitouch provides it, else the vendor feature report via hidraw."""

    def set(self, level):
        if os.path.exists(LED_SYSFS):
            with open(LED_SYSFS, "w") as f:
                f.write(str(level))
        elif level:
            self._hidraw(0x01)
            self._hidraw(0x40 + level)
        else:
            self._hidraw(0x00)

    def _hidraw(self, value):
        # vendor feature report 0x0D (usage page 0xFF00, usage 0x06)
        buf = bytearray([0x0D, 0x14, 0x03, value, 0xAD])
        with open(find_hidraw(), "rb+", buffering=0) as f:
            fcntl.ioctl(f, 0xC0000000 | (len(buf) << 16) | (ord("H") << 8) | 0x06, buf)


# ---- uinput -----------------------------------------------------------------
class UInput:
    def __init__(self, name, keys=(), abs_axes=None, props=()):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for k in keys:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
        if abs_axes:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
            for axis, info in abs_axes.items():
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)
                fcntl.ioctl(self.fd, UI_ABS_SETUP, struct.pack("HH", axis, 0) + info)
        for p in props:
            fcntl.ioctl(self.fd, UI_SET_PROPBIT, p)
        setup = struct.pack("HHHH", 0x06, 0x0B05, 0x0001, 1) + name.encode().ljust(80, b"\0") + struct.pack("I", 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

    def emit(self, etype, code, value):
        os.write(self.fd, EVENT.pack(0, 0, etype, code, value))

    def syn(self):
        self.emit(EV_SYN, SYN_REPORT, 0)

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)


# ---- touch tracking ---------------------------------------------------------
class Touch:
    def __init__(self, tid):
        self.tid = tid
        self.x = self.y = None
        self.x0 = self.y0 = None
        self.t0 = time.monotonic()
        self.zone = None        # "toggle", "brightness", ("key", code) or None
        self.pointer = False    # being forwarded to the virtual touchpad
        self.started = False    # tracking id already sent to the virtual touchpad
        self.ended = False
        self.consumed = False   # already acted on, or a physical click happened


class NumberPad:
    def __init__(self):
        self.src = os.open(find_event_node(), os.O_RDONLY | os.O_NONBLOCK)
        self.backlight = Backlight()

        absinfo = {}
        for axis in (ABS_X, ABS_Y, ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID):
            buf = bytearray(24)
            fcntl.ioctl(self.src, EVIOCGABS(axis), buf)
            absinfo[axis] = bytes(buf)
        _, _, self.max_x, *_ = struct.unpack("6i", absinfo[ABS_X])
        _, _, self.max_y, *_ = struct.unpack("6i", absinfo[ABS_Y])

        key_codes = {c for row in KEYS for c in row if isinstance(c, int)} | {KEY_LEFTSHIFT, KEY_5}
        self.kbd = UInput("UX3405CA NumberPad", keys=key_codes)
        self.pad = UInput("UX3405CA NumberPad pointer", keys=[BTN_LEFT, BTN_TOUCH] + BTN_TOOL,
                          abs_axes=absinfo, props=[INPUT_PROP_POINTER, INPUT_PROP_BUTTONPAD])

        self.active = False     # LEDs on, grid live
        self.grabbed = False
        self.level = len(BRIGHTNESS) - 1
        self.slot = 0
        self.touches = {}       # slot -> Touch
        self.last_pos = {}      # slot -> (x, y); the kernel omits unchanged coordinates on a new touch
        self.click = 0

    # -- geometry
    def zone_at(self, x, y):
        if y < ICON_H and x > self.max_x - ICON_W:
            return "toggle"
        if not self.active:
            return None
        if y < ICON_H and x < ICON_W:
            return "brightness"
        gx, gy = x - LEFT, y - TOP
        gw, gh = self.max_x - LEFT - RIGHT, self.max_y - TOP - BOTTOM
        if 0 <= gx < gw and 0 <= gy < gh:
            row, col = int(gy * len(KEYS) / gh), int(gx * len(KEYS[0]) / gw)
            return ("key", KEYS[row][col])
        return None

    # -- actions
    def set_active(self, on):
        self.active = on
        try:
            self.backlight.set(BRIGHTNESS[self.level] if on else 0)
        except OSError as e:
            print(f"backlight: {e}", file=sys.stderr)
        log("numberpad", "ON" if on else "OFF")

    def cycle_brightness(self):
        self.level = (self.level + 1) % len(BRIGHTNESS)
        self.backlight.set(BRIGHTNESS[self.level])
        log(f"brightness {BRIGHTNESS[self.level]}")

    def type_key(self, code):
        seq = [KEY_LEFTSHIFT, KEY_5] if code == PERCENT else [code]
        for c in seq:
            self.kbd.emit(EV_KEY, c, 1)
            self.kbd.syn()
        for c in reversed(seq):
            self.kbd.emit(EV_KEY, c, 0)
            self.kbd.syn()
        log("key", code)

    def sync_grab(self):
        # Only switch the grab while no finger is down, so libinput never sees
        # a touch sequence cut in half.
        if self.touches or self.grabbed == self.active:
            return
        try:
            fcntl.ioctl(self.src, EVIOCGRAB, 1 if self.active else 0)
            self.grabbed = self.active
        except OSError as e:
            print(f"grab: {e}", file=sys.stderr)

    # -- event handling
    def handle(self, etype, code, value):
        if etype == EV_ABS:
            if code == ABS_MT_SLOT:
                self.slot = value
            elif code == ABS_MT_TRACKING_ID:
                if value >= 0:
                    t = self.touches[self.slot] = Touch(value)
                    t.x, t.y = self.last_pos.get(self.slot, (None, None))
                elif self.slot in self.touches:
                    self.touches[self.slot].ended = True
            elif code in (ABS_MT_POSITION_X, ABS_MT_POSITION_Y) and self.slot in self.touches:
                t = self.touches[self.slot]
                if code == ABS_MT_POSITION_X:
                    t.x = value
                else:
                    t.y = value
                self.last_pos[self.slot] = (t.x, t.y)
        elif etype == EV_KEY and code == BTN_LEFT:
            self.click = value
            if value:
                for t in self.touches.values():
                    t.consumed = True
        elif etype == EV_SYN and code == SYN_REPORT:
            self.frame()

    def frame(self):
        now = time.monotonic()
        live = [t for t in self.touches.values() if not t.ended]
        for t in self.touches.values():
            if t.x0 is None and t.x is not None and t.y is not None:
                t.x0, t.y0 = t.x, t.y
                t.zone = self.zone_at(t.x, t.y)
                log(f"down x={t.x} y={t.y} zone={t.zone}")
            if t.x0 is None:
                continue
            moved = abs(t.x - t.x0) > MOVE_THRESHOLD or abs(t.y - t.y0) > MOVE_THRESHOLD
            if moved or len(live) > 1:
                t.pointer = True
            if t.ended and not t.pointer and not t.consumed and now - t.t0 <= TAP_MAX_SECONDS:
                if t.zone == "brightness":
                    self.cycle_brightness()
                elif isinstance(t.zone, tuple):
                    self.type_key(t.zone[1])

        if self.grabbed:
            self.forward()
        for s in [s for s, t in self.touches.items() if t.ended]:
            del self.touches[s]
        self.sync_grab()

    def forward(self):
        for s, t in self.touches.items():
            if not t.pointer or t.x is None or t.y is None:
                continue
            self.pad.emit(EV_ABS, ABS_MT_SLOT, s)
            if not t.started:
                self.pad.emit(EV_ABS, ABS_MT_TRACKING_ID, t.tid)
                t.started = True
            if t.ended:
                self.pad.emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
            else:
                self.pad.emit(EV_ABS, ABS_MT_POSITION_X, t.x)
                self.pad.emit(EV_ABS, ABS_MT_POSITION_Y, t.y)
        down = [t for t in self.touches.values() if t.pointer and t.started and not t.ended]
        self.pad.emit(EV_KEY, BTN_TOUCH, 1 if down else 0)
        for i, btn in enumerate(BTN_TOOL):
            self.pad.emit(EV_KEY, btn, 1 if len(down) == i + 1 else 0)
        if down:
            self.pad.emit(EV_ABS, ABS_X, down[0].x)
            self.pad.emit(EV_ABS, ABS_Y, down[0].y)
        self.pad.emit(EV_KEY, BTN_LEFT, self.click)
        self.pad.syn()

    def check_hold(self):
        """Toggle when a finger has rested on the top-right icon long enough.
        Returns seconds until the next deadline, or None."""
        now = time.monotonic()
        wait = None
        for t in self.touches.values():
            if t.zone != "toggle" or t.pointer or t.consumed or t.ended:
                continue
            left = t.t0 + HOLD_SECONDS - now
            if left <= 0:
                t.consumed = True
                self.set_active(not self.active)
            else:
                wait = left if wait is None else min(wait, left)
        return wait

    def run(self):
        print(f"numberpadd: watching {TOUCHPAD_NAME} ({self.max_x}x{self.max_y})", flush=True)
        while True:
            timeout = self.check_hold()
            if not select.select([self.src], [], [], timeout)[0]:
                continue
            try:
                data = os.read(self.src, EVENT.size * 64)
            except BlockingIOError:
                continue
            for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, etype, code, value = EVENT.unpack_from(data, off)
                self.handle(etype, code, value)

    def shutdown(self, *_):
        try:
            if self.grabbed:
                fcntl.ioctl(self.src, EVIOCGRAB, 0)
            if self.active:
                self.backlight.set(0)
        finally:
            self.kbd.close()
            self.pad.close()
            sys.exit(0)


if __name__ == "__main__":
    pad = NumberPad()
    signal.signal(signal.SIGTERM, pad.shutdown)
    signal.signal(signal.SIGINT, pad.shutdown)
    pad.run()
