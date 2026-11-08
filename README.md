> [!Prompt (Claude Opus 5.5 Medium)]
> Minor clarification of what I'm actually trying to do: when the (wireless) mouse wakes back up, run some configurable command (in this case, get OpenRGB to do something to reapply the theme). I may be trying to reinvent the wheel: are you able to find a plugin or anything that does that already?

Let me check what already exists.

I didn't find a ready-made Linux tool for this. The closest things are:

- **OpenRGB itself:** there's an open feature request for applying the saved profile when a device is detected or reconnected (gitlab.com/CalcProgrammer1/OpenRGB issue #3842). Per that request, you currently have to rescan and reload the profile by hand.
- **A Windows-only Python script** that restarts OpenRGB when a keyboard reconnects.
- **Razer-specific bug reports** where the mouse reverts to its default lighting after standby. Synapse reapplies the profile 1-2 seconds after wake, so a short delay in your hook is probably worthwhile.

So a small udev rule plus a systemd unit is probably the least-reinvented wheel.

**1. Find out what event the host actually sees on wake**

Run this, then let the mouse sleep and wake it:
```
udevadm monitor --udev --property
```
- With a **dongle**, the dongle usually stays enumerated. Whether you get anything depends on the driver. Logitech's `hid-logitech-dj`, for example, creates and removes child hidraw/input devices on wake, so you'd see `add` events. Other receivers show nothing at all.
- With **Bluetooth**, udev may show input device add/remove events, but the more reliable signal is BlueZ's `Connected` property changing.
- If nothing shows up, the mouse's sleep and wake isn't visible to the host except through input activity. In that case you'd have to poll or watch for the first input event instead.

**2. Hook it with udev and systemd** (once you have a matching event)

`/etc/udev/rules.d/99-mouse-rgb.rules`:
```
ACTION=="add", SUBSYSTEM=="input", ATTRS{idVendor}=="XXXX", ATTRS{idProduct}=="YYYY", TAG+="systemd", ENV{SYSTEMD_WANTS}="mouse-rgb.service"
```
Adjust the subsystem to whatever step 1 showed. Avoid `RUN+=` for anything that talks to OpenRGB, because udev kills slow or long-running `RUN` programs.

`/etc/systemd/system/mouse-rgb.service`:
```
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'sleep 2; /usr/bin/openrgb --noautoconnect -p MyProfile'
```
If OpenRGB runs as a user-session server or GUI, point the command at it instead, for example `openrgb --client -p MyProfile`. Otherwise two instances will fight over the HID device. Since you're on an immutable ublue host, remember that `/etc` is writable but the container's OpenRGB binary isn't on the host path. You'd want `distrobox-enter` or a Flatpak invocation in `ExecStart`.

**3. Bluetooth fallback**

```
dbus-monitor --system "type='signal',interface='org.freedesktop.DBus.Properties',path_namespace='/org/bluez'"
```
Watch for `Connected = true` on your mouse's device path. A tiny script can run your command when it sees that.

If you tell me the mouse model and whether it's dongle or Bluetooth, I can be more specific about which events to expect. Paste the `udevadm monitor` output from a sleep/wake cycle and I can help write the match rule.

> [!Prompt (Claude Opus 5.5 Medium)]
> No good, I'm afraid, udev isn't going to do it. This is the SteelSeries Aerox 9 Wireless running in 2.4 GHz dongle mode (not Bluetooth). I have identified the URB_INTERRUPT back and forth that happens when there's input via dumpcap, so I can potentially use that as a trigger. I assume this is essentially a driver at this point, correct?

Sort of, but it's a lot smaller than a driver. You don't need to speak the mouse's protocol, since OpenRGB already does that. You only need a userspace watcher that detects "mouse just woke up" and runs your command.

**Don't use usbmon as the trigger.** It's root-only and heavy. The same input traffic is available through `evdev` (or `hidraw`), where the dongle's interfaces appear as ordinary input devices. Multiple readers can open these at once, so the watcher won't conflict with the desktop or OpenRGB.

**Detect wake by idle gap.** The mouse presumably goes to sleep after some idle time and then starts sending events again. If you treat "first event after N seconds of silence" as the wake signal, you don't have to decode anything in the traffic. A false positive just reapplies the profile, which is harmless.

A sketch using `python-evdev` (install it in whatever environment the watcher runs in):

```python
#!/usr/bin/env python3
import asyncio, subprocess, time
import evdev

VENDOR = 0x1038          # SteelSeries
IDLE_GAP = 60            # seconds of silence that counts as "asleep"
SETTLE = 2               # let the mouse finish waking before applying
CMD = ["openrgb", "--client", "-p", "MyProfile"]

last = 0.0
pending = False

async def reapply():
    global pending
    await asyncio.sleep(SETTLE)
    subprocess.run(CMD)
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
    devs = [d for d in devs if d.info.vendor == VENDOR]
    await asyncio.gather(*(watch(d) for d in devs))

asyncio.run(main())
```

Run it as a systemd **user** service so it can open the input nodes (the logged-in seat user normally gets access) and reach your OpenRGB instance.

Some caveats:

- **The dongle exposes several interfaces.** That's why the script watches every input node with that vendor ID. If the mouse also exposes a vendor-specific HID interface, it may send a distinct report on wake. That would be a more precise trigger than the idle gap, and you can check by comparing the first packet after wake against normal movement in your capture.
- **Idle gap versus the mouse's sleep timeout.** Set `IDLE_GAP` somewhat below the sleep timeout configured in SteelSeries GG. If it's too short you'll get extra harmless reapplies, and if it's too long you'll miss short sleeps.
- **Hook into OpenRGB cleanly.** Run OpenRGB as a server or in the background and have the command talk to it with `--client`. Starting a second standalone instance will fight over the HID device. If OpenRGB lives in your distrobox, the command needs to be a `distrobox-enter ...` call, or you can run the whole watcher inside the container.
- **Check onboard memory.** If the Aerox 9 can store a lighting profile onboard and OpenRGB's driver can write to it, the problem goes away without any daemon. I don't know whether OpenRGB's support for this mouse does that, so I'd check its issue tracker before building anything.

If you share what `evtest` or `udevadm info` shows for the dongle's nodes, I can help tighten the match to the right interface.

> [!Prompt (Claude Opus 5.5 Medium)]
> Actually, that script falls thoroughly into the "good enough" category for me. Could you put together a user unit file for me?

Here's the unit, assuming you save the script as `~/.local/bin/mouse-rgb-watch.py` and make it executable.

`~/.config/systemd/user/mouse-rgb-watch.service`:
```ini
[Unit]
Description=Reapply OpenRGB profile when the Aerox 9 wakes up
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/share/mouse-rgb/venv/bin/python %h/.local/bin/mouse-rgb-watch.py
Restart=always
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

Enable it with:
```
systemctl --user daemon-reload
systemctl --user enable --now mouse-rgb-watch.service
journalctl --user -u mouse-rgb-watch -f
```

A few notes:

- **`Restart=always`, not `on-failure`:** if the dongle isn't present at startup, the script finds no devices and exits cleanly. If the dongle is unplugged mid-run, the read loop raises an error. Either way you want a retry.
- **Python environment:** on an immutable host, the simplest route is a venv, which the unit above expects:
  ```
  python3 -m venv ~/.local/share/mouse-rgb/venv
  ~/.local/share/mouse-rgb/venv/bin/pip install evdev
  ```
  If the install fails because it needs to compile, run the watcher in your distrobox instead and use `distrobox-enter` in `ExecStart`.
- **Input device access:** `/dev/input/event*` is normally `root:input` with mode 0660, and regular desktop users aren't in the `input` group. If the script dies with a permission error, add yourself to the group and log out and back in. On Fedora Atomic-based systems, `usermod` can be awkward for system groups. If it complains, the usual workaround is:
  ```
  getent group input | sudo tee -a /etc/group
  sudo usermod -aG input $USER
  ```
- **OpenRGB command:** the `CMD` in the script runs in the service's environment, which has no `PATH` surprises but also isn't your distrobox or Flatpak. If OpenRGB lives in one of those, change `CMD` to something like `["flatpak", "run", "org.openrgb.OpenRGB", "--client", "-p", "MyProfile"]`.
