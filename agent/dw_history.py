"""
Laptop history: when it was on, slept, shut down, and which apps/games ran how long.

Storage: one small append-only file (history.jsonl), one line per event, kept for 60 days
(typically 2-5 KB per day). Plus a tiny 'alive' timestamp rewritten every heartbeat
(every 15 min) so a laptop that died without warning gets an accurate end time.

Event line: [unix_time, code, arg, extra]
  on   powered on / agent started     extra {"b": boot_id}
  rs   agent restarted, same boot     extra {"b": boot_id}
  wk   woke from sleep                extra {"by": "network"|"other"}
  sl   went to sleep
  off  shut down
  lost disappeared without warning (battery died, crash, forced power-off)
  st   app started                    arg = app label, extra {"q": 1} for quiet apps
  cl   app closed                     arg = app label, extra {"dur": s, "q": 1, "cpu":, "gpu":, "ct":, "gt":}
"""
import json
import os
import threading
import time

KEEP_DAYS = 60
UP, DOWN = ("on", "rs", "wk"), ("sl", "off", "lost")


def day_bounds(day):
    """(start, end) unix times of a local calendar day 'YYYY-MM-DD'."""
    t = time.mktime(time.strptime(day, "%Y-%m-%d"))
    nxt = time.localtime(t + 26 * 3600)              # robust across DST changes
    end = time.mktime((nxt.tm_year, nxt.tm_mon, nxt.tm_mday, 0, 0, 0, 0, 0, -1))
    return t, end


def day_of(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


class History:
    def __init__(self, folder):
        self.path = os.path.join(folder, "history.jsonl")
        self.alive_path = os.path.join(folder, "alive")
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ writing
    def add(self, code, arg=None, extra=None, t=None):
        row = [int(t or time.time()), code]
        if arg is not None or extra:
            row.append(arg)
        if extra:
            row.append({k: v for k, v in extra.items() if v is not None})
        line = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self.lock:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass

    def alive(self):
        try:
            with open(self.alive_path, "w") as f:
                f.write(str(int(time.time())))
        except OSError:
            pass

    def read(self):
        rows = []
        with self.lock:
            try:
                with open(self.path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            r = json.loads(line)
                            if isinstance(r, list) and len(r) >= 2:
                                rows.append(r)
                        except ValueError:
                            continue
            except OSError:
                pass
        rows.sort(key=lambda r: r[0])
        return rows

    def _last_alive(self):
        try:
            with open(self.alive_path) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def startup(self, boot_id, fresh_boot):
        """Called when the agent starts: close whatever the last run left open."""
        rows = self.read()
        self.prune(rows)
        state, last_boot, open_apps, last_t = "down", None, {}, None
        for r in rows:
            code = r[1]
            last_t = r[0]
            if code in UP:
                state = "up"
                last_boot = (r[3] if len(r) > 3 and isinstance(r[3], dict) else {}).get("b", last_boot)
            elif code in DOWN:
                state, open_apps = "down", {}
            elif code == "st":
                open_apps[r[2]] = r
            elif code == "cl":
                open_apps.pop(r[2], None)
        now = int(time.time())
        same_boot = state == "up" and last_boot == boot_id
        end = now if same_boot else max(self._last_alive() or 0, last_t or 0)
        for label, st in open_apps.items():            # apps left open by the previous run
            extra = {"dur": max(0, end - st[0])}
            if len(st) > 3 and isinstance(st[3], dict) and st[3].get("q"):
                extra["q"] = 1
            self.add("cl", label, extra, t=end)
        if same_boot:
            self.add("rs", None, {"b": boot_id})
        else:
            if state == "up":
                self.add("lost", t=end)
            self.add("on", "boot" if fresh_boot else "start", {"b": boot_id})
        self.alive()

    def prune(self, rows=None):
        """Rewrite the file without events older than KEEP_DAYS (rarely needed)."""
        try:
            if os.path.getsize(self.path) < 64_000:
                return
        except OSError:
            return
        rows = rows if rows is not None else self.read()
        cutoff = time.time() - KEEP_DAYS * 86400
        keep = [r for r in rows if r[0] >= cutoff]
        tmp = self.path + ".tmp"
        with self.lock:
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    for r in keep:
                        f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
                os.replace(tmp, self.path)
            except OSError:
                pass

    # ------------------------------------------------------------------ reading
    def _intervals(self, rows, now):
        """Replay events -> (on_intervals, {app: intervals}, quiet_apps)."""
        on, apps, quiet = [], {}, set()
        state, since, open_apps = "down", None, {}

        def close_apps(t):
            for label, start in open_apps.items():
                apps.setdefault(label, []).append((start, t))
            open_apps.clear()

        for r in rows:
            t, code = r[0], r[1]
            extra = r[3] if len(r) > 3 and isinstance(r[3], dict) else {}
            if code in UP or code in ("st", "cl"):
                if state == "down":
                    state, since = "up", t
            if code in DOWN:
                if state == "up":
                    on.append((since, t))
                    close_apps(t)
                state = "down"
            elif code == "st":
                open_apps.setdefault(r[2], t)
                if extra.get("q"):
                    quiet.add(r[2])
            elif code == "cl":
                start = open_apps.pop(r[2], None)
                if start is None and extra.get("dur"):
                    start = t - extra["dur"]
                if start is not None:
                    apps.setdefault(r[2], []).append((start, t))
                if extra.get("q"):
                    quiet.add(r[2])
        if state == "up":
            on.append((since, now))
            close_apps(now)
        return on, apps, quiet

    @staticmethod
    def _clip(intervals, a, b):
        return int(sum(max(0, min(e, b) - max(s, a)) for s, e in intervals))

    def day(self, day=None, max_bytes=3600):
        """Timeline + totals for one day (fits in one ntfy message)."""
        now = time.time()
        day = day or day_of(now)
        a, b = day_bounds(day)
        rows = self.read()
        on, apps, quiet = self._intervals(rows, now)
        totals = {k: self._clip(v, a, b) for k, v in apps.items()}
        totals = {k: v for k, v in sorted(totals.items(), key=lambda kv: -kv[1]) if v > 0}
        events = [r for r in rows if a <= r[0] < b]
        out = {"day": day, "on": self._clip(on, a, b), "apps": totals,
               "quiet": sorted(q for q in quiet if q in totals), "ev": events}

        def size():
            return len(json.dumps(out, separators=(",", ":"), ensure_ascii=False).encode())

        if size() > max_bytes:                      # drop quiet-app events first
            out["ev"] = [r for r in events if not (r[1] in ("st", "cl") and r[2] in quiet)]
            out["trunc"] = 1
        while size() > max_bytes and out["ev"]:     # then the oldest events
            out["ev"] = out["ev"][len(out["ev"]) // 4 + 1:]
        return out

    def week(self, days=7, top=5):
        now = time.time()
        rows = self.read()
        on, apps, quiet = self._intervals(rows, now)
        out = []
        for i in range(days - 1, -1, -1):
            d = day_of(now - i * 86400)
            a, b = day_bounds(d)
            totals = {k: self._clip(v, a, b) for k, v in apps.items() if k not in quiet}
            best = dict(sorted(((k, v) for k, v in totals.items() if v > 0), key=lambda kv: -kv[1])[:top])
            out.append({"day": d, "on": self._clip(on, a, b), "apps": best})
        return out

    def today_brief(self):
        """Small summary for the status card: on-time today + top 2 apps (not quiet)."""
        now = time.time()
        a, b = day_bounds(day_of(now))
        on, apps, quiet = self._intervals(self.read(), now)
        totals = sorted(((k, self._clip(v, a, b)) for k, v in apps.items() if k not in quiet),
                        key=lambda kv: -kv[1])
        return {"on": self._clip(on, a, b), "top": [[k, v] for k, v in totals[:2] if v > 0]}
