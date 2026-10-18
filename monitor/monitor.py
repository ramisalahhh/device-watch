#!/usr/bin/env python3
"""
DeviceWatch monitor - alerts you when a laptop disappears WITHOUT saying goodbye
(battery died, Wi-Fi dropped, crashed). Planned sleep/shutdown is announced by the
agent itself, so the monitor stays quiet for those.

Runs anywhere that is always on: a free cloud VM (Docker), a Raspberry Pi,
or your Android phone with Termux. Standard library only, ~10 MB RAM, no disk writes.

Config (environment variables):
  DW_SERVER          ntfy server            (default https://ntfy.sh)
  DW_TOPIC           same topic as agents   (required)
  DW_TOKEN           ntfy access token      (optional, self-hosted ntfy)
  DW_OFFLINE_AFTER   minutes without a heartbeat = offline (default 35;
                     keep it > 2x the agents' heartbeat_minutes)
  DW_POLL_SECONDS    how often to check     (default 60)
"""
import json
import logging
import os
import time
import urllib.request

SERVER = os.environ.get("DW_SERVER", "https://ntfy.sh").rstrip("/")
TOPIC = os.environ.get("DW_TOPIC", "")
TOKEN = os.environ.get("DW_TOKEN", "")
OFFLINE_AFTER = float(os.environ.get("DW_OFFLINE_AFTER", "35")) * 60
POLL = int(os.environ.get("DW_POLL_SECONDS", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("monitor")
AUTH = {"Authorization": "Bearer " + TOKEN} if TOKEN else {}


class Device:
    __slots__ = ("name", "emoji", "last_seen", "state", "boot", "alerted")

    def __init__(self, name):
        self.name, self.emoji = name, "💻"
        self.last_seen, self.state, self.boot, self.alerted = 0, "up", None, False


def notify(title, message, priority=4, tags=None):
    payload = {"topic": TOPIC, "title": title, "message": message, "priority": priority,
               "tags": tags or []}
    req = urllib.request.Request(SERVER, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **AUTH},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        log.warning("notify failed: %s", e)


def fetch(since):
    url = f"{SERVER}/{TOPIC}-hb/json?poll=1&since={since}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=AUTH), timeout=20) as r:
        for line in r:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") == "message":
                yield ev


def main():
    if not TOPIC:
        raise SystemExit("Set DW_TOPIC (same topic as your agents).")
    devices = {}
    since = f"{int(OFFLINE_AFTER * 2)}s"       # rebuild state from ntfy's cache on start
    first = True
    log.info("watching %s/%s-hb, offline after %.0f min", SERVER, TOPIC, OFFLINE_AFTER / 60)
    while True:
        try:
            for ev in fetch(since):
                since = ev["id"]
                try:
                    hb = json.loads(ev["message"])
                except ValueError:
                    continue
                name = hb.get("d")
                if not name or hb.get("type") == "dryrun":
                    continue
                dev = devices.setdefault(name, Device(name))
                dev.emoji = hb.get("e", dev.emoji)
                if dev.alerted is True:
                    if hb.get("b") == dev.boot and hb.get("s") == "up":
                        notify(f"{dev.emoji} {name}: 🟢 back online",
                               f"{name} reconnected (was unreachable since "
                               f"{time.strftime('%H:%M', time.localtime(dev.last_seen))})",
                               priority=3, tags=["green_circle"])
                    # different boot id = it rebooted, and the agent already said "turned on"
                dev.alerted = False
                dev.last_seen = ev.get("time", time.time())
                dev.state = hb.get("s", "up")
                dev.boot = hb.get("b")
        except Exception as e:
            log.warning("poll failed (monitor offline?): %s", e)
            time.sleep(POLL)
            continue

        now = time.time()
        for dev in devices.values():
            gone = now - dev.last_seen
            if dev.state == "up" and not dev.alerted and gone > OFFLINE_AFTER:
                dev.alerted = "silent" if first else True   # don't alarm about old news
                if not first:
                    notify(f"{dev.emoji} {dev.name}: 🔴 went offline",
                           f"No signal from {dev.name} since "
                           f"{time.strftime('%H:%M', time.localtime(dev.last_seen))} "
                           "- battery died, Wi-Fi dropped, or it crashed.",
                           priority=4, tags=["red_circle"])
                log.info("%s offline (%.0f min)", dev.name, gone / 60)
        first = False
        time.sleep(POLL)


if __name__ == "__main__":
    main()
