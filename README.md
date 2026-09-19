# zenbook-numberpad

Makes the **NumberPad** — the LED-lit numeric keypad inside the touchpad — work
on Linux on the ASUS Zenbook 14 **UX3405CA**.

Two pieces:

- **`numberpadd`**, a small daemon with no dependencies. This is all you need.
- **A kernel patch** for `hid-multitouch` that exposes the backlight as a
  standard LED. Optional; the daemon uses it when present.

| Tested on | Touchpad | Kernel |
|---|---|---|
| Zenbook 14 UX3405CA | PixArt `ASUP1415`, I2C-HID `093A:300C` | 7.2 (`linux-omarchy`), Omarchy / Arch |

The UX3405MA ships the same touchpad and the same printed grid, so it should
work there too — untested.

## Is this the right project for you?

[asus-numberpad-driver](https://github.com/asus-linux-drivers/asus-numberpad-driver)
is the full-featured option: dozens of ASUS models, configurable layouts and
gestures, calculator shortcut, runs as a normal user. Use it if you want any of
that, or if your laptop is not a UX3405.

This project is the minimal take for one laptop: a single file with no
dependencies, the backlight driven through the regular HID path instead of raw
I2C writes, and a kernel patch aiming to make that part native. The hidraw
approach found here was contributed back to that driver (see Upstream status).

## Using it

- **Turn on / off:** rest a finger on the top-right icon for about half a second.
- **Type:** tap a key. Drags, two-finger scroll and physical clicks keep working
  as pointer input while the NumberPad is on.
- **Brightness:** tap the top-left icon to cycle through four levels.

## Install

    sudo install -m755 numberpadd.py /usr/local/bin/numberpadd
    sudo install -m644 numberpadd.service /etc/systemd/system/
    sudo systemctl enable --now numberpadd

Runs as root: it needs the touchpad's hidraw node, `/dev/uinput` and an
exclusive grab of the touchpad while the NumberPad is on.

Uninstall:

    sudo systemctl disable --now numberpadd
    sudo rm /usr/local/bin/numberpadd /etc/systemd/system/numberpadd.service

Troubleshooting: `sudo systemctl stop numberpadd`, then run
`sudo numberpadd --debug` in a terminal to see every touch, zone and key.
Timing, icon sizes, grid margins and brightness levels are constants at the top
of `numberpadd.py`.

## How the hardware works

- The touchpad is a plain Precision Touchpad. The firmware has **no NumberPad
  mode**: it never flags touches on the corner icons (vendor bit `0xFF01:01` in
  touch report `0x54` stays 0) and never emits key events. Icons and keys are
  just regions of the 3996 x 2242 coordinate space, which is also how the
  Windows filter driver (`AsusPTPFilter`) treats them.
- The only NumberPad hardware is the LED grid under the glass, controlled by a
  vendor **HID feature report `0x0D`** (usage page `0xFF00`, usage `0x06`,
  4 bytes) declared in the report descriptor. Payload: `14 03 <value> AD`.

  | value         | effect                          |
  |---------------|---------------------------------|
  | `0x01`        | LEDs on                         |
  | `0x00`        | LEDs off                        |
  | `0x41`–`0x48` | brightness, 8 distinct levels   |
  | `0x60`/`0x61` | unlock / lock (MyASUS setting)  |

  Because the report is declared, it goes through the normal HID path —
  **hidraw** (`HIDIOCSFEATURE`) from userspace, `hid_hw_raw_request()` in the
  kernel. Existing community drivers send the same bytes as a hand-rolled
  I2C-HID SET_REPORT frame with `i2ctransfer -f`, behind the kernel driver's back.
- The touchpad keeps the LED state across a short s2idle suspend (tested: lit
  before, lit after, stock driver). With the kernel patch the LED core turns
  the grid off on suspend and restores it on resume. The daemon re-applies its
  state after a resume anyway, in case a deeper or longer sleep does power the
  touchpad down — that case is untested.

## Kernel patch (optional)

`kernel/0568-hid-multitouch-asus-numberpad-led.patch` registers
`/sys/class/leds/asus::numberpad` (brightness 0–8) for this touchpad. LEDs go
off on suspend and are restored on resume. Touch handling is untouched.

Try it without installing anything — builds the patched driver for the running
kernel and prints the load / undo commands (the touchpad drops out for a second
while the module is swapped; a reboot brings the stock module back):

    kernel/build.sh

Needs the kernel headers (`linux-omarchy-headers` / `linux-headers`), `curl`,
`patch` and `make`.

## Upstream status

- `linux-omarchy`: [omacom/omarchy-pkgs#536](https://github.com/omacom/omarchy-pkgs/pull/536)
- `asus-numberpad-driver` (hidraw instead of raw I2C):
  [asus-linux-drivers/asus-numberpad-driver#316](https://github.com/asus-linux-drivers/asus-numberpad-driver/pull/316)
  (requested by the maintainer in [#315](https://github.com/asus-linux-drivers/asus-numberpad-driver/issues/315))
- Mainline (linux-input): not sent yet.

## Known limits

- Digits, `.` and `%` are typed with main-block keycodes so they do not depend
  on NumLock; correct on us/es/latam layouts, not on AZERTY.
- No auto-repeat when holding backspace.
- Grid margins were borrowed from the UX3405MA layout of `asus-numberpad-driver`;
  every key maps correctly, but the edges are not measured.

## Other files

- `probe.py` — the research tool used to work all this out: `led on|off|0xNN`
  sends the feature report, `sniff` prints decoded touch reports.

## License

GPL-2.0-only.
