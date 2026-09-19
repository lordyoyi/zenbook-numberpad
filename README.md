# zenbook-numberpad

NumberPad support for the ASUS Zenbook 14 **UX3405CA** on Linux (touchpad: PixArt
`ASUP1415`, HID `093A:300C`, I2C-HID, driven by `hid-multitouch`).

## How the hardware works

- The touchpad is a plain Precision Touchpad. The firmware has **no NumberPad
  mode**: it never flags touches on the corner icons (vendor bit `0xFF01:01` in
  touch report `0x54` stays 0) and never emits key events. Icons and keys are
  just regions of the 3996 x 2242 coordinate space, exactly as the Windows
  filter driver (`AsusPTPFilter`) treats them.
- The only NumberPad hardware is the LED grid under the glass, controlled by a
  vendor **HID feature report `0x0D`** (usage page `0xFF00`, usage `0x06`,
  4 bytes), declared in the report descriptor. Payload: `14 03 <value> AD`.

  | value         | effect                  |
  |---------------|-------------------------|
  | `0x01`        | LEDs on                 |
  | `0x00`        | LEDs off                |
  | `0x41`–`0x48` | brightness              |
  | `0x60`/`0x61` | unlock / lock (MyASUS)  |

  Because the report is declared, it can be sent through **hidraw**
  (`HIDIOCSFEATURE`) — no raw `i2ctransfer -f` behind the kernel driver's back,
  which is what existing community drivers do with the same bytes wrapped in a
  hand-rolled I2C-HID SET_REPORT frame.

## Files

- `numberpadd.py` — the daemon. No dependencies (plain ioctls for evdev, uinput,
  hidraw). Hold the top-right icon ~0.6 s to toggle; taps on the grid type keys;
  drags, two-finger scroll and physical clicks keep working (the touchpad is
  grabbed while active and pointer touches are replayed on a virtual touchpad);
  tap the top-left icon to cycle brightness. `--debug` logs touches and keys.
- `numberpadd.service` — systemd unit (runs as root).
- `probe.py` — research tool: `led on|off|0xNN`, `sniff` (decoded touch reports).

## Install

    sudo install -m755 numberpadd.py /usr/local/bin/numberpadd
    sudo install -m644 numberpadd.service /etc/systemd/system/
    sudo systemctl enable --now numberpadd

## Known limits

- Digits, `.` and `%` are typed with main-block keycodes (NumLock-independent);
  correct on us/es/latam layouts, not on AZERTY.
- No key auto-repeat on backspace.
- Grid margins (`TOP/BOTTOM/LEFT/RIGHT`) borrowed from the UX3405MA layout.

## License

GPL-2.0-only.
