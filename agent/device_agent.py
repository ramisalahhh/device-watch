#!/usr/bin/env python3
"""
DeviceWatch agent - tells your phone (and watch) what this computer is doing,
and lets you lock / sleep / restart / shut it down from your phone.

Design goals: tiny footprint.
  * Python standard library only (no pip install). Windows APIs via ctypes.
  * Polls cheaply every few seconds; one idle HTTP connection for commands.
  * Writes nothing to disk unless you pass --log.
  * Runs at below-normal priority so it never competes with games.

Usage:
  python device_agent.py --setup      first-time config wizard
  python device_agent.py --discover   show the .exe name of the app in front (to add rules)
  python device_agent.py --test       send a test notification
  python device_agent.py              run (installer starts it with pythonw at logon)
"""
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import http.client
from collections import deque
from urllib.parse import urlsplit
from _operator import _compare_digest as compare_digest  # = hmac.compare_digest, without hashlib

VERSION = "1.0.0"
IS_WIN = sys.platform == "win32"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("DW_CONFIG", os.path.join(BASE_DIR, "config.json"))


def run(args, **kw):
    """subprocess.run, imported only when a power command actually happens."""
    import subprocess
    if IS_WIN:
        kw.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
    return subprocess.run(args, **kw)
DRY_RUN = os.environ.get("DW_DRY_RUN") == "1"   # log power actions instead of running them

log = logging.getLogger("devicewatch")

DEFAULTS = {
    "device_name": socket.gethostname(),
    "emoji": "💻",
    "server": "https://ntfy.sh",
    "token": "",
    "topic": "",
    "secret": "",
    "check_seconds": 5,
    "heartbeat_minutes": 15,
    "action_delay_seconds": 30,
    "allowed_commands": ["status", "lock", "sleep", "restart", "shutdown", "cancel"],
    "buttons_in_notifications": True,
    "show_window_titles": False,
    "notify": {
        "online": True,
        "sleep_and_shutdown": True,
        "apps": True,
        "idle_minutes": 0,
        "battery_low_percent": 20,
        "battery_critical_percent": 7,
    },
    "quiet_hours": {"enabled": False, "start": "01:00", "end": "08:00"},
    "apps": [],
}


# ----------------------------------------------------------------------------
# Platform layer: processes, foreground app, idle time, battery, uptime
# ----------------------------------------------------------------------------
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetTickCount64.restype = ctypes.c_ulonglong
    k32.GetTickCount.restype = wintypes.DWORD
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
    u32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    def process_table():
        """{pid: exe_name_lower} via one cheap Toolhelp snapshot."""
        table = {}
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == INVALID_HANDLE:
            return table
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                table[entry.th32ProcessID] = entry.szExeFile.lower()
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return table

    def foreground(table):
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        return table.get(pid.value, ""), buf.value

    def idle_seconds():
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not u32.GetLastInputInfo(ctypes.byref(lii)):
            return 0
        return ((k32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) // 1000

    def battery():
        """(percent or None, charging bool)"""
        s = SYSTEM_POWER_STATUS()
        if not k32.GetSystemPowerStatus(ctypes.byref(s)):
            return None, False
        if s.BatteryFlag & 128 or s.BatteryLifePercent == 255:
            return None, s.ACLineStatus == 1
        return int(s.BatteryLifePercent), s.ACLineStatus == 1

    def uptime_seconds():
        return k32.GetTickCount64() // 1000

    def lower_priority():
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL

else:  # Linux (and a best-effort macOS fallback)
    def process_table():
        table = {}
        if os.path.isdir("/proc"):
            for name in os.listdir("/proc"):
                if name.isdigit():
                    try:
                        with open(f"/proc/{name}/comm") as f:
                            table[int(name)] = f.read().strip().lower()
                    except OSError:
                        pass
        else:
            try:
                out = run(["ps", "-A", "-o", "pid=,comm="], capture_output=True,
                                     text=True, timeout=5).stdout
                for line in out.splitlines():
                    pid, _, comm = line.strip().partition(" ")
                    table[int(pid)] = os.path.basename(comm.strip()).lower()
            except Exception:
                pass
        return table

    def foreground(table):
        return "", ""

    def idle_seconds():
        return 0

    def battery():
        base = "/sys/class/power_supply"
        for bat in (os.listdir(base) if os.path.isdir(base) else []):
            if not bat.startswith("BAT"):
                continue
            try:
                with open(f"{base}/{bat}/capacity") as f:
                    pct = int(f.read())
                with open(f"{base}/{bat}/status") as f:
                    status = f.read().strip()
                return pct, status in ("Charging", "Full", "Not charging")
            except (OSError, ValueError):
                pass
        return None, False

    def uptime_seconds():
        try:
            with open("/proc/uptime") as f:
                return int(float(f.read().split()[0]))
        except OSError:
            return int(time.monotonic())

    def lower_priority():
        try:
            os.nice(10)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def fmt_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m" if m else f"{seconds}s"


def deep_merge(base, override):
    out = dict(base)
    for k, v in override.items():
        out[k] = deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"No config at {CONFIG_PATH}. Run:  python device_agent.py --setup")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = deep_merge(DEFAULTS, json.load(f))
    if not cfg["topic"] or not cfg["secret"]:
        sys.exit("config.json needs 'topic' and 'secret'. Run --setup.")
    cfg["server"] = cfg["server"].rstrip("/")
    for rule in cfg["apps"]:
        rule["_procs"] = {p.lower() for p in rule.get("process", [])}
    return cfg


def in_quiet_hours(cfg):
    q = cfg["quiet_hours"]
    if not q.get("enabled"):
        return False
    now = time.strftime("%H:%M")
    start, end = q["start"], q["end"]
    return (start <= now < end) if start <= end else (now >= start or now < end)



# ----------------------------------------------------------------------------
# Minimal HTTP client: http.client + ONE shared TLS context
# (urllib.request costs ~2 MB more and reloads the CA store on every request)
# ----------------------------------------------------------------------------
_TLS = None


def http_open(url, method="GET", body=None, headers=None, timeout=10):
    """Returns (conn, resp). Caller closes conn. Raises on network errors / HTTP >= 400."""
    global _TLS
    u = urlsplit(url)
    if u.scheme == "https":
        if _TLS is None:
            import ssl
            _TLS = ssl.create_default_context()
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=_TLS)
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
    except Exception:
        conn.close()
        raise
    if resp.status >= 400:
        conn.close()
        raise OSError(f"HTTP {resp.status}")
    return conn, resp


def http_post(url, body, headers, timeout=10):
    conn, resp = http_open(url, "POST", body, headers, timeout)
    try:
        resp.read()
    finally:
        conn.close()


def write_crash_log(exc_info=None):
    """Only touches the disk when something actually went wrong (kept under ~50 KB)."""
    import traceback
    try:
        path = os.path.join(BASE_DIR, "crash.log")
        mode = "w" if os.path.exists(path) and os.path.getsize(path) > 50_000 else "a"
        with open(path, mode, encoding="utf-8") as f:
            f.write(time.strftime("\n=== %Y-%m-%d %H:%M:%S ===\n"))
            if exc_info:
                traceback.print_exception(*exc_info, file=f)
            else:
                traceback.print_exc(file=f)
    except Exception:
        pass


def install_crash_hooks():
    sys.excepthook = lambda *ei: write_crash_log(ei)
    threading.excepthook = lambda a: write_crash_log((a.exc_type, a.exc_value, a.exc_traceback))

# ----------------------------------------------------------------------------
# ntfy transport
# ----------------------------------------------------------------------------
class Ntfy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.server = cfg["server"]
        self.topic = cfg["topic"]
        self.hb_topic = cfg["topic"] + "-hb"
        self.cmd_topic = cfg["topic"] + "-cmd"
        self.headers = {"Content-Type": "application/json"}
        if cfg["token"]:
            self.headers["Authorization"] = "Bearer " + cfg["token"]
        self.outbox = deque(maxlen=30)        # in-memory only; survives network blips
        self.lock = threading.Lock()
        self.wake = threading.Event()
        threading.Thread(target=self._sender, daemon=True, name="sender").start()

    def _post(self, payload, timeout=10):
        http_post(self.server, json.dumps(payload).encode(), self.headers, timeout)

    def notify(self, title, message, tags=None, priority=3, actions=None, urgent=False):
        """Queue a phone notification. urgent=True sends synchronously (shutdown/sleep)."""
        if in_quiet_hours(self.cfg) and priority < 4:
            log.info("quiet hours, skipped: %s", message)
            return
        payload = {"topic": self.topic, "title": title, "message": message,
                   "tags": tags or [], "priority": priority}
        if actions and self.cfg["buttons_in_notifications"]:
            payload["actions"] = actions[:3]
        if urgent:
            try:
                self._post(payload, timeout=4)
                return
            except Exception as e:
                log.warning("urgent send failed: %s", e)
        with self.lock:
            self.outbox.append((time.time(), payload))
        self.wake.set()

    def publish_hb(self, data, timeout=8):
        """Heartbeat / status for the monitor and phone app. Best effort, no retry."""
        try:
            self._post({"topic": self.hb_topic, "message": json.dumps(data, separators=(",", ":"))},
                       timeout=timeout)
            return True
        except Exception as e:
            log.debug("heartbeat failed: %s", e)
            return False

    def _sender(self):
        backoff = 5
        while True:
            self.wake.wait(timeout=backoff)
            self.wake.clear()
            while True:
                with self.lock:
                    if not self.outbox:
                        break
                    queued_at, payload = self.outbox[0]
                if time.time() - queued_at > 90:   # delivered late: say when it happened
                    payload = dict(payload, message=payload["message"] +
                                   time.strftime(" (at %H:%M)", time.localtime(queued_at)))
                try:
                    self._post(payload)
                    with self.lock:
                        if self.outbox and self.outbox[0][0] == queued_at:
                            self.outbox.popleft()
                    backoff = 5
                except Exception as e:
                    log.info("offline, will retry: %s", e)
                    backoff = min(backoff * 2, 120)
                    break

    def action(self, label, cmd, clear=True):
        """An ntfy notification button that POSTs a command back to this device."""
        body = json.dumps({"cmd": cmd, "to": self.cfg["device_name"], "key": self.cfg["secret"],
                           "reply": "notify"})
        act = {"action": "http", "label": label, "url": f"{self.server}/{self.cmd_topic}",
               "method": "POST", "body": body, "clear": clear}
        if self.cfg["token"]:
            act["headers"] = {"Authorization": "Bearer " + self.cfg["token"]}
        return act


# ----------------------------------------------------------------------------
# Agent
# ----------------------------------------------------------------------------
class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg["device_name"]
        self.emoji = cfg["emoji"]
        self.net = Ntfy(cfg)
        self.sessions = {}            # app label -> start time
        self.state = "up"
        self.boot_id = self._boot_id()
        self.idle_notified = False
        self.battery_alerted = None   # None / "low" / "critical"
        self.pending_action = None    # (cmd, threading.Timer)
        self.seen_cmds = deque(maxlen=50)
        self.last_hb = 0
        self.stopping = threading.Event()
        self.fg = ("", "")
        self.down_at = 0
        self.resume_lock = threading.Lock()

    def _boot_id(self):
        return int((time.time() - uptime_seconds()) // 120)

    def t(self, text):
        return f"{self.emoji} {self.name}: {text}"

    # ---- snapshots -------------------------------------------------------
    def activity(self):
        """Main thing happening: notifying apps (games, calls) beat background ones (Chrome)."""
        if not self.sessions:
            return ""
        loud = {r["label"] for r in self.cfg["apps"] if r.get("notify", True)}
        return max(self.sessions, key=lambda l: (l in loud, self.sessions[l]))

    def snapshot(self, kind="hb"):
        pct, charging = battery()
        exe, title = self.fg
        data = {"v": 1, "type": kind, "d": self.name, "e": self.emoji, "s": self.state,
                "b": self.boot_id, "app": self.activity(), "apps": sorted(self.sessions),
                "fg": exe, "bat": pct, "chg": charging, "idle": idle_seconds(),
                "up": uptime_seconds(), "ts": int(time.time())}
        if self.cfg["show_window_titles"]:
            data["title"] = title[:80]
        return data

    def heartbeat(self, kind="hb"):
        self.last_hb = time.time()
        self.net.publish_hb(self.snapshot(kind))

    def power_buttons(self):
        return [self.net.action("🔒 Lock", "lock"), self.net.action("😴 Sleep", "sleep"),
                self.net.action("⏻ Shut down", "shutdown")]

    # ---- lifecycle events ------------------------------------------------
    def announce_online(self, reason=None):
        self.state = "up"
        if not self.cfg["notify"]["online"]:
            return
        if reason is None:
            reason = "turned on" if uptime_seconds() < 600 else "is online"
        pct, charging = battery()
        extra = f" · 🔋{pct}%{'⚡' if charging else ''}" if pct is not None else ""
        self.net.notify(self.t(f"🟢 {reason}"), f"{self.name} {reason}{extra}",
                        tags=["green_circle"], actions=self.power_buttons())

    def announce_down(self, state, text):
        """Called right before sleep/shutdown. Must be quick."""
        if self.state == state:
            return
        self.state = state
        self.down_at = time.time()
        self.end_all_sessions(silent=True)
        self.net.publish_hb(self.snapshot(), timeout=3)   # tells monitor: expected, don't alarm
        if self.cfg["notify"]["sleep_and_shutdown"]:
            self.net.notify(self.t(text), f"{self.name} {text.split(' ', 1)[1]}",
                            tags=["zzz"] if state == "sleep" else ["red_circle"], urgent=True)

    def on_resume(self):
        with self.resume_lock:
            if self.state in ("up", "resuming"):
                return
            self.state = "resuming"
        log.info("resumed")
        self.boot_id = self._boot_id()
        self.state = "up"
        self.announce_online("woke up")
        self.heartbeat()

    # ---- apps ------------------------------------------------------------
    def end_all_sessions(self, silent=False):
        for label in list(self.sessions):
            self._stop_app(label, silent)

    def _stop_app(self, label, silent=False):
        started = self.sessions.pop(label, None)
        if started and not silent and self.cfg["notify"]["apps"]:
            self.net.notify(self.t(f"closed {label}"),
                            f"Closed {label} after {fmt_duration(time.time() - started)}",
                            tags=["white_check_mark"], priority=2)

    def check_apps(self, running):
        for rule in self.cfg["apps"]:
            label = rule["label"]
            active = bool(rule["_procs"] & running)
            if active and label not in self.sessions:
                self.sessions[label] = time.time()
                if self.cfg["notify"]["apps"] and rule.get("notify", True):
                    verb = rule.get("verb", "using")
                    icon = rule.get("emoji", "🟦")
                    self.net.notify(self.t(f"{icon} {verb} {label}"),
                                    f"{self.name} is now {verb} {label}",
                                    tags=[], priority=rule.get("priority", 3),
                                    actions=self.power_buttons())
                self.heartbeat("change")
            elif not active and label in self.sessions:
                self._stop_app(label, silent=not rule.get("notify", True))
                self.heartbeat("change")

    def check_idle(self):
        mins = self.cfg["notify"]["idle_minutes"]
        if not mins:
            return
        idle = idle_seconds()
        if idle >= mins * 60 and not self.idle_notified:
            self.idle_notified = True
            self.net.notify(self.t("💤 idle"), f"No keyboard/mouse for {mins} min", priority=2,
                            actions=self.power_buttons())
        elif idle < 30 and self.idle_notified:
            self.idle_notified = False
            self.net.notify(self.t("👀 active again"), f"Someone is using {self.name}", priority=3)

    def check_battery(self):
        pct, charging = battery()
        n = self.cfg["notify"]
        if pct is None or charging:
            self.battery_alerted = None
            return
        if pct <= n["battery_critical_percent"] and self.battery_alerted != "critical":
            self.battery_alerted = "critical"
            self.net.notify(self.t(f"🪫 battery {pct}%"), "About to die - plug it in!",
                            tags=["warning"], priority=5)
        elif pct <= n["battery_low_percent"] and self.battery_alerted is None:
            self.battery_alerted = "low"
            self.net.notify(self.t(f"🔋 battery {pct}%"), "Battery is low", priority=4)

    # ---- remote commands -------------------------------------------------
    def command_listener(self):
        """One long-lived HTTP stream. On every reconnect we ask ntfy for everything since
        the last moment the stream was known alive, so a Wi-Fi blip never loses a command
        (duplicates are dropped by message id)."""
        base = f"{self.net.server}/{self.net.cmd_topic}/json"
        headers = {k: v for k, v in self.net.headers.items() if k == "Authorization"}
        last_alive = None          # fresh start: only NEW commands (never replay old ones)
        backoff = 1
        while not self.stopping.is_set():
            started = time.time()
            try:
                url = base if last_alive is None else f"{base}?since={int(last_alive) - 20}"
                # ntfy sends a keepalive every ~45s; 75s of silence = dead connection
                conn, resp = http_open(url, headers=headers, timeout=75)
                try:
                    for raw in resp:
                        last_alive = time.time()
                        if self.stopping.is_set():
                            return
                        try:
                            ev = json.loads(raw)
                        except ValueError:
                            continue
                        if ev.get("event") == "message":
                            try:
                                self.handle_command(ev)
                            except Exception:
                                log.exception("command failed")
                finally:
                    conn.close()
            except Exception as e:
                log.info("command stream reconnecting: %s", e)
            if last_alive is None:     # first connect failed: catch up from our start time
                last_alive = started
            # healthy connection that just ended -> reconnect at once; repeated failures -> back off
            backoff = 1 if time.time() - started > 60 else min(backoff * 2, 60)
            self.stopping.wait(backoff)

    def handle_command(self, ev):
        if ev.get("id") in self.seen_cmds:
            return
        self.seen_cmds.append(ev.get("id"))
        if abs(time.time() - ev.get("time", 0)) > 300:      # stale/replayed
            return
        try:
            msg = json.loads(ev.get("message", ""))
        except ValueError:
            return
        if not compare_digest(str(msg.get("key", "")), self.cfg["secret"]):
            log.warning("command with bad key ignored")
            return
        if msg.get("to") not in (self.name, "*"):
            return
        cmd = msg.get("cmd")
        reply = msg.get("reply", "notify")
        if cmd not in self.cfg["allowed_commands"]:
            self.net.notify(self.t("⛔ refused"), f"'{cmd}' is not allowed on this device", priority=2)
            return
        log.info("command: %s", cmd)
        if cmd != "status":   # status replies with fresh data, which is its own receipt
            self.net.publish_hb({"v": 1, "type": "ack", "d": self.name, "cmd": cmd,
                                 "ts": int(time.time())}, timeout=5)
        if cmd == "status":
            self.send_status(reply)
        elif cmd == "lock":
            self.run_power("lock")
            self.net.notify(self.t("🔒 locked"), f"{self.name} was locked from your phone", priority=2)
        elif cmd == "cancel":
            self.cancel_pending()
        elif cmd in ("sleep", "restart", "shutdown"):
            self.schedule(cmd)

    def send_status(self, reply):
        if reply == "app":
            self.heartbeat("status")
            return
        s = self.snapshot()
        parts = [f"🎮 {s['app']}" if s["app"] else "No tracked app open"]
        if s["fg"]:
            parts.append(f"In front: {s['fg']}")
        if s["bat"] is not None:
            parts.append(f"🔋 {s['bat']}%{' charging' if s['chg'] else ''}")
        if s["idle"] >= 60:
            parts.append(f"Idle {fmt_duration(s['idle'])}")
        parts.append(f"Up {fmt_duration(s['up'])}")
        self.net.notify(self.t("📊 status"), "\n".join(parts), priority=3,
                        actions=self.power_buttons())

    def schedule(self, cmd):
        self.cancel_pending(quiet=True)
        delay = int(self.cfg["action_delay_seconds"])
        words = {"sleep": "go to sleep", "restart": "restart", "shutdown": "shut down"}
        if IS_WIN and cmd in ("shutdown", "restart") and not DRY_RUN:
            # Windows' own countdown also warns whoever is sitting at the laptop
            flag = "/s" if cmd == "shutdown" else "/r"
            run(["shutdown", flag, "/t", str(delay), "/c",
                 f"DeviceWatch: {words[cmd]} requested from phone"])
            timer = None
        else:
            timer = threading.Timer(delay, self.run_power, args=(cmd,))
            timer.daemon = True
            timer.start()
        self.pending_action = (cmd, timer)
        self.net.notify(self.t(f"⚠️ will {words[cmd]} in {delay}s"),
                        f"{self.name} will {words[cmd]} in {delay} seconds.",
                        tags=["warning"], priority=4,
                        actions=[self.net.action("✋ Cancel", "cancel")], urgent=True)

    def cancel_pending(self, quiet=False):
        if not self.pending_action:
            if not quiet:
                self.net.notify(self.t("nothing to cancel"), "No pending action", priority=2)
            return
        cmd, timer = self.pending_action
        self.pending_action = None
        if timer:
            timer.cancel()
        elif IS_WIN and not DRY_RUN:
            run(["shutdown", "/a"])
        if not quiet:
            self.net.notify(self.t(f"✋ {cmd} cancelled"), f"{cmd} cancelled", priority=3)

    def run_power(self, cmd):
        if cmd != "lock":
            self.pending_action = None
        if DRY_RUN:
            log.warning("DRY RUN power action: %s", cmd)
            self.net.publish_hb({"v": 1, "type": "dryrun", "d": self.name, "cmd": cmd})
            return
        try:
            if IS_WIN:
                if cmd == "lock":
                    ctypes.windll.user32.LockWorkStation()
                elif cmd == "sleep":
                    self.announce_down("sleep", "😴 going to sleep")
                    ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)
                elif cmd == "shutdown":
                    run(["shutdown", "/s", "/t", "0"])
                elif cmd == "restart":
                    run(["shutdown", "/r", "/t", "0"])
            else:
                linux = {"lock": ["loginctl", "lock-session"], "sleep": ["systemctl", "suspend"],
                         "shutdown": ["systemctl", "poweroff"], "restart": ["systemctl", "reboot"]}
                if cmd == "sleep":
                    self.announce_down("sleep", "😴 going to sleep")
                run(linux[cmd])
        except Exception as e:
            log.error("power action %s failed: %s", cmd, e)
            self.net.notify(self.t(f"❌ {cmd} failed"), str(e)[:200], priority=4)

    # ---- main loop -------------------------------------------------------
    def run(self):
        lower_priority()
        log.info("DeviceWatch %s starting as '%s'", VERSION, self.name)
        self.announce_online()
        self.heartbeat()
        threading.Thread(target=self.command_listener, daemon=True, name="commands").start()
        if IS_WIN:
            start_windows_event_window(self)

        interval = max(2, int(self.cfg["check_seconds"]))
        hb_every = max(1, float(self.cfg["heartbeat_minutes"])) * 60
        tick = 0
        last_loop = time.time()
        while not self.stopping.wait(interval):
            try:
                now = time.time()
                if now - last_loop > interval * 6 + 60:      # clock jumped: we were asleep
                    self.on_resume()
                last_loop = now
                if self.state != "up":
                    # still running long after "going down": the sleep didn't happen / we missed wake
                    if self.state == "sleep" and now - self.down_at > 120:
                        self.on_resume()
                    continue
                table = process_table()
                self.fg = foreground(table)
                self.check_apps(set(table.values()))
                tick += 1
                if tick % 6 == 0:                              # these change slowly
                    self.check_idle()
                    self.check_battery()
                if now - self.last_hb >= hb_every:
                    self.heartbeat()
                del table
            except Exception:
                # never die: log it (crash.log) and keep watching on the next tick
                log.exception("main loop error")
                write_crash_log()

    def shutdown_hook(self, *_):
        self.announce_down("off", "🔴 shutting down")
        self.stopping.set()


# ----------------------------------------------------------------------------
# Windows: hidden window that receives sleep / shutdown broadcasts
# ----------------------------------------------------------------------------
def start_windows_event_window(agent):
    WM_QUERYENDSESSION, WM_ENDSESSION, WM_POWERBROADCAST = 0x11, 0x16, 0x218
    PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x4, 0x7, 0x12
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                 wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    u32.DefWindowProcW.restype = LRESULT
    u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.CreateWindowExW.restype = wintypes.HWND
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                    wintypes.HINSTANCE, wintypes.LPVOID]
    u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                wintypes.UINT]

    def wndproc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_POWERBROADCAST:
                if wparam == PBT_APMSUSPEND:
                    agent.announce_down("sleep", "😴 going to sleep")
                elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                    threading.Thread(target=agent.on_resume, daemon=True).start()
                return 1
            if msg == WM_QUERYENDSESSION:
                return 1
            if msg == WM_ENDSESSION and wparam:
                agent.announce_down("off", "🔴 shutting down")
                return 0
        except Exception as e:
            log.error("wndproc: %s", e)
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def loop():
        proc = WNDPROC(wndproc)
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = proc
        wc.hInstance = hinst
        wc.lpszClassName = "DeviceWatchHidden"
        u32.RegisterClassW(ctypes.byref(wc))
        # A real (never shown) top-level window: message-only windows miss broadcasts
        hwnd = u32.CreateWindowExW(0, wc.lpszClassName, "DeviceWatch", 0, 0, 0, 0, 0,
                                   None, None, hinst, None)
        if not hwnd:
            log.error("could not create event window")
            return
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        del proc

    threading.Thread(target=loop, daemon=True, name="win-events").start()


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def setup_wizard():
    print("DeviceWatch setup\n-----------------")
    existing = {}
    import secrets
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            existing = json.load(f)

    def ask(prompt, default):
        v = input(f"{prompt} [{default}]: ").strip()
        return v or default

    name = ask("Name for this device", existing.get("device_name", socket.gethostname()))
    emoji = ask("Emoji", existing.get("emoji", "💻"))
    server = ask("ntfy server", existing.get("server", "https://ntfy.sh"))
    print("\nIf this is your FIRST device, press Enter to generate a topic and secret.")
    print("For the SECOND device, paste the SAME topic and secret as the first one.\n")
    topic = ask("Topic", existing.get("topic") or "dw-" + secrets.token_hex(8))
    secret = ask("Secret", existing.get("secret") or secrets.token_urlsafe(18))
    cfg = existing or {}
    cfg.update({"device_name": name, "emoji": emoji, "server": server,
                "topic": topic, "secret": secret})
    if "apps" not in cfg:
        example = os.path.join(BASE_DIR, "config.example.json")
        if os.path.exists(example):
            with open(example, encoding="utf-8") as f:
                cfg["apps"] = json.load(f).get("apps", [])
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {CONFIG_PATH}")
    print(f"\n>>> In the ntfy phone app, subscribe to:  {topic}")
    print(f">>> Use this on your other laptop:  topic={topic}  secret={secret}")


def discover():
    print("Switch to the app you want to track. Ctrl+C to stop.\n")
    last = None
    while True:
        exe, title = foreground(process_table())
        if (exe, title) != last:
            print(f"  process: {exe or '?':30} window: {title[:60]}")
            last = (exe, title)
        time.sleep(2)


def main():
    argv = sys.argv[1:]                      # (no argparse: saves memory for a 24/7 process)
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return
    flag = lambda *names: any(n in argv for n in names)
    log_file = argv[argv.index("--log") + 1] if "--log" in argv[:-1] else None

    handlers = []
    if log_file:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(log_file, maxBytes=200_000, backupCount=1,
                                            encoding="utf-8"))
    elif sys.stderr is not None:   # pythonw has no console: stay silent, write nothing
        handlers.append(logging.StreamHandler())
    else:
        handlers.append(logging.NullHandler())
    logging.basicConfig(level=logging.DEBUG if flag("-v", "--verbose") else logging.INFO,
                        handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s")

    if flag("--setup"):
        return setup_wizard()
    if flag("--discover"):
        try:
            return discover()
        except KeyboardInterrupt:
            return
    cfg = load_config()
    if flag("--test"):
        net = Ntfy(cfg)
        net.notify(f"{cfg['emoji']} {cfg['device_name']}: test ✅",
                   "If you see this on your phone (and watch), DeviceWatch works!", urgent=True)
        print("Sent. Check your phone.")
        return
    install_crash_hooks()
    agent = Agent(cfg)
    for sig in (signal.SIGTERM, signal.SIGINT) + ((signal.SIGBREAK,) if IS_WIN else ()):
        try:
            signal.signal(sig, agent.shutdown_hook)
        except (ValueError, OSError):
            pass
    agent.run()


if __name__ == "__main__":
    main()
