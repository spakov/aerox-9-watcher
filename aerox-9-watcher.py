#!/usr/bin/env python3

import asyncio
import os
import subprocess
import time

import evdev

HOME = os.path.expanduser("~")
VENDOR = 0x1038  # SteelSeries
PRODUCT_WIRELESS = 0x1858  # SteelSeries Aerox 9 Wireless (connected via dongle on 2.4 GHz, not Bluetooth)
PRODUCT_WIRED = 0x185A  # SteelSeries Aerox 9 Wireless (connected via USB, not wireless)
PROFILE_WIRELESS = f"{HOME}/.config/OpenRGB/Fuchsia-Wireless.orp"
PROFILE_WIRED = f"{HOME}/.config/OpenRGB/Fuchsia-Wired.orp"
IDLE_GAP = 30  # seconds of silence that counts as "asleep"
SETTLE = 0  # let the mouse finish waking before applying
CMD = [
    f"{HOME}/AppImages/openrgb.appimage",
    "--client",
    "localhost",
    "-p",
]

ENV = {}  # not needed, evidently: ENV = {"DESKTOPINTEGRATION": "1"}

last = 0.0
pending = False


async def reapply(is_wireless=False):
    global pending
    await asyncio.sleep(SETTLE)

    CMD.append(PROFILE_WIRELESS if is_wireless else PROFILE_WIRED)
    print(f"Running {CMD}...")
    subprocess.run(CMD, check=False, env=ENV)  # noqa: ASYNC221
    CMD.pop()

    pending = False


async def watch(dev):
    global last, pending
    async for _ in dev.async_read_loop():
        now = time.monotonic()
        if now - last > IDLE_GAP and not pending:
            pending = True
            asyncio.create_task(reapply(dev.info.product == PRODUCT_WIRELESS))
        last = now


async def main():
    devs = [evdev.InputDevice(p) for p in evdev.list_devices()]
    devs = [
        d
        for d in devs
        if d.info.vendor == VENDOR
        and (d.info.product == PRODUCT_WIRELESS or d.info.product == PRODUCT_WIRED)
    ]
    await asyncio.gather(*(watch(d) for d in devs))


asyncio.run(main())
