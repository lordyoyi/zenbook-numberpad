#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Build hid-multitouch with the NumberPad LED patch for the running kernel.
# Fetches the matching upstream driver source, applies the patch and builds an
# out-of-tree module in ./build. Needs the kernel headers, curl, patch, make.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
version=${1:-$(uname -r | grep -oE '^[0-9]+\.[0-9]+(\.[0-9]+)?')}
url="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/hid"
build="$here/build"

rm -rf "$build"
mkdir -p "$build/drivers/hid"
for f in hid-multitouch.c hid-ids.h hid-haptic.h; do
  echo "fetching $f (v$version)"
  curl -sfL "$url/$f?h=v$version" -o "$build/drivers/hid/$f"
done

(cd "$build" && patch -Np1 < "$here"/0568-hid-multitouch-asus-numberpad-led.patch)
cp "$here/Makefile" "$build/drivers/hid/"
make -C "$build/drivers/hid"

echo
echo "built: $build/drivers/hid/hid-multitouch.ko"
echo "load:  sudo rmmod hid_multitouch && sudo insmod $build/drivers/hid/hid-multitouch.ko"
echo "undo:  sudo rmmod hid_multitouch && sudo modprobe hid_multitouch   (or reboot)"
