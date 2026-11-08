#!/usr/bin/env python3

import asyncio
import os
import subprocess
import time

import evdev

VENDOR = 0x1038  # SteelSeries
PRODUCT = 0x1858  # SteelSeries Aerox 9 Wireless
IDLE_GAP = 30  # seconds of silence that counts as "asleep"
SETTLE = 1  # let the mouse finish waking before applying
CMD = [
    f"{os.path.expanduser('~')}/AppImages/openrgb.appimage",
    "--client",
    "localhost",
    "-p",
    "Fuchsia",
]

ENV = {}  # not needed, evidently: ENV = {"DESKTOPINTEGRATION": "1"}

last = 0.0
pending = False


async def reapply():
    global pending
    await asyncio.sleep(SETTLE)
    subprocess.run(CMD, env=ENV)
    pending = False


async def watch(dev):
    global last, pending
    async for _ in dev.async_read_loop():
        now = time.monotonic()
        if now - last > IDLE_GAP and not pending:
            pending = True
            asyncio.create_task(reapply())
        last = now


async def main():
    devs = [evdev.InputDevice(p) for p in evdev.list_devices()]
    devs = [d for d in devs if d.info.vendor == VENDOR and d.info.product == PRODUCT]
    await asyncio.gather(*(watch(d) for d in devs))


asyncio.run(main())
