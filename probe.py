#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Probe the UX3405CA NumberPad (PixArt ASUP1415 093A:300C) over hidraw.

  sudo ./probe.py led on|off|0x41..0x48   send vendor feature report 0x0D
  sudo ./probe.py sniff                   dump touch reports (0x54), flag vendor bit changes
"""
import fcntl
import glob
import os
import sys

HID_ID = "0018:093A:300C"


def hidraw_path():
    for dev in glob.glob(f"/sys/bus/hid/devices/{HID_ID}.*/hidraw/hidraw*"):
        return "/dev/" + os.path.basename(dev)
    sys.exit(f"no hidraw node for {HID_ID}")


def hidiocsfeature(length):
    # _IOC(_IOC_READ | _IOC_WRITE, 'H', 0x06, length)
    return 0xC0000000 | (length << 16) | (ord("H") << 8) | 0x06


def led(value):
    # Same payload the Windows driver / asus-numberpad-driver send, minus the
    # hand-rolled I2C-HID SET_REPORT framing: the kernel adds that for us.
    buf = bytearray([0x0D, 0x14, 0x03, value, 0xAD])
    with open(hidraw_path(), "rb+", buffering=0) as f:
        fcntl.ioctl(f, hidiocsfeature(len(buf)), buf)
    print(f"sent feature 0x0D value 0x{value:02x}")


def sniff():
    # Report 0x54 layout (from the report descriptor):
    #   byte 1: bit0 button1 (physical click), bit3 vendor 0xFF01:01, bits4-7 contact count
    #   byte 4: bit0 confidence, bit1 tip switch; bytes 5-6 X (0..3996), 7-8 Y (0..2242)
    #   bytes 29-38: vendor 0xFF01:02..06 (16 bit each), bytes 39-42: vendor 0xFF01:1F
    last_vendor = last_click = None
    touching = False
    n = 0
    with open(hidraw_path(), "rb", buffering=0) as f:
        print("touch the pad and the two corner icons; Ctrl-C to stop")
        try:
            while True:
                r = f.read(64)
                if not r:
                    continue
                if r[0] != 0x54:
                    print(f"report 0x{r[0]:02x}: {r.hex(' ')}")
                    continue
                vendor, click = (r[1] >> 3) & 1, r[1] & 1
                tip = (r[4] >> 1) & 1
                x, y = int.from_bytes(r[5:7], "little"), int.from_bytes(r[7:9], "little")
                if vendor != last_vendor:
                    print(f"  VENDOR BIT -> {vendor}  at x={x} y={y}")
                    last_vendor = vendor
                if click != last_click:
                    if last_click is not None:
                        print(f"  click -> {click}")
                    last_click = click
                if tip and not touching:
                    n += 1
                    print(f"touch {n} DOWN x={x:4d} y={y:4d}  vendor fields: {r[29:43].hex(' ')}")
                elif touching and not tip:
                    print(f"touch {n} UP   x={x:4d} y={y:4d}  vendor fields: {r[29:43].hex(' ')}")
                touching = bool(tip)
        except KeyboardInterrupt:
            print()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "led":
        v = {"on": 0x01, "off": 0x00}.get(sys.argv[2])
        led(v if v is not None else int(sys.argv[2], 16))
    elif len(sys.argv) == 2 and sys.argv[1] == "sniff":
        sniff()
    else:
        sys.exit(__doc__)
