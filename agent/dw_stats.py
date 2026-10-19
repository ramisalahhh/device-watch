"""
Live hardware stats: CPU %, RAM %, GPU %, CPU/GPU temperature.

Cheap by design: CPU and RAM are single API calls. GPU load (Windows performance
counters) and temperatures are only read when a status is requested or a game is running.

Temperatures: Windows has no built-in API for CPU temperature. We read them from
  1. LibreHardwareMonitor (free) if its "Remote Web Server" is on (http://localhost:8085)
  2. nvidia-smi for NVIDIA GPUs (installed with the NVIDIA driver)
  3. /sys/class/thermal on Linux
Otherwise temps are reported as unknown (None).
"""
import json
import os
import re
import sys
import time

IS_WIN = sys.platform == "win32"
LHM_URL = os.environ.get("DW_LHM_URL", "http://127.0.0.1:8085/data.json")

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class _MEMSTATEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def _cpu_times():
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return None
        v = lambda f: (f.hi << 32) | f.lo
        return v(idle), v(kern) + v(user)          # kernel time already includes idle

    def ram():
        m = _MEMSTATEX()
        m.dwLength = ctypes.sizeof(_MEMSTATEX)
        if not _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None, None
        return int(m.dwMemoryLoad), round(m.ullTotalPhys / 2**30, 1)

else:
    def _cpu_times():
        try:
            with open("/proc/stat") as f:
                vals = [int(x) for x in f.readline().split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return idle, sum(vals)
        except (OSError, ValueError, IndexError):
            return None

    def ram():
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k] = int(v.split()[0])
            total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
            return round(100 * (total - avail) / total), round(total / 2**20, 1)
        except (OSError, KeyError, ValueError, ZeroDivisionError):
            return None, None


class CpuMeter:
    """CPU % between consecutive calls (or over a short 0.3 s window on the first call)."""

    def __init__(self):
        self.last = _cpu_times()
        self.last_t = time.time()

    def read(self):
        if self.last is None or time.time() - self.last_t < 0.25:
            time.sleep(0.3)
        now = _cpu_times()
        if not now or not self.last:
            self.last = now
            return None
        didle, dtotal = now[0] - self.last[0], now[1] - self.last[1]
        self.last, self.last_t = now, time.time()
        if dtotal <= 0:
            return None
        return max(0, min(100, round(100 * (1 - didle / dtotal))))


# ---------------------------------------------------------------------------- GPU load
def gpu_load_windows():
    """Same number Task Manager shows for '3D': busiest GPU engine across all processes.
    Uses Windows performance counters (pdh.dll). Takes ~0.5 s. None if unavailable."""
    try:
        pdh = ctypes.WinDLL("pdh")

        class _VAL(ctypes.Union):
            _fields_ = [("longValue", ctypes.c_long), ("doubleValue", ctypes.c_double),
                        ("largeValue", ctypes.c_longlong)]

        class _FMT(ctypes.Structure):
            _fields_ = [("CStatus", wintypes.DWORD), ("v", _VAL)]

        class _ITEM(ctypes.Structure):
            _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FMT)]

        q, c = ctypes.c_void_p(), ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
            return None
        try:
            path = r"\GPU Engine(*engtype_3D)\Utilization Percentage"
            if pdh.PdhAddEnglishCounterW(q, path, None, ctypes.byref(c)) != 0:
                return None
            pdh.PdhCollectQueryData(q)
            time.sleep(0.5)
            pdh.PdhCollectQueryData(q)
            size, count = wintypes.DWORD(0), wintypes.DWORD(0)
            FMT_DOUBLE_NOCAP = 0x00000200 | 0x00008000
            pdh.PdhGetFormattedCounterArrayW(c, FMT_DOUBLE_NOCAP, ctypes.byref(size),
                                             ctypes.byref(count), None)
            if not size.value:
                return 0
            buf = (ctypes.c_byte * size.value)()
            if pdh.PdhGetFormattedCounterArrayW(c, FMT_DOUBLE_NOCAP, ctypes.byref(size),
                                                ctypes.byref(count), buf) != 0:
                return None
            items = ctypes.cast(buf, ctypes.POINTER(_ITEM))
            per_engine = {}
            for i in range(count.value):
                name = items[i].szName or ""
                key = name[name.find("luid"):] if "luid" in name else name   # one GPU engine
                per_engine[key] = per_engine.get(key, 0.0) + items[i].FmtValue.v.doubleValue
            return int(min(100, round(max(per_engine.values(), default=0))))
        finally:
            pdh.PdhCloseQuery(q)
    except Exception:
        return None


# ---------------------------------------------------------------------------- temperatures
_lhm_down_until = 0.0


def _parse_temp(value):
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*°?\s*C", value or "")
    return float(m.group(1).replace(",", ".")) if m else None


def temps_from_lhm(url=None):
    """(cpu_temp, gpu_temp) from LibreHardwareMonitor / OpenHardwareMonitor web server."""
    global _lhm_down_until
    if time.time() < _lhm_down_until:
        return None, None
    try:
        import http.client
        from urllib.parse import urlsplit
        u = urlsplit(url or LHM_URL)
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=1.5)
        try:
            conn.request("GET", u.path or "/data.json")
            data = json.loads(conn.getresponse().read())
        finally:
            conn.close()
    except Exception:
        _lhm_down_until = time.time() + 600        # not running: don't retry for 10 min
        return None, None

    cpu, gpu = {}, {}

    def walk(node, kind):
        # LibreHardwareMonitor: SensorId like "/amdcpu/0/temperature/2", "/gpu-nvidia/0/..."
        # OpenHardwareMonitor: hardware nodes carry an icon ("cpu.png", "nvidia.png", "ati.png")
        sid = (node.get("SensorId") or node.get("HardwareId") or "").lower()
        img = (node.get("ImageURL") or "").lower()
        text = node.get("Text") or ""
        hw = sid.split("/")[1] if sid.startswith("/") and sid.count("/") >= 1 else ""
        if hw:
            kind = "cpu" if "cpu" in hw else "gpu" if "gpu" in hw else "other"
        elif "cpu.png" in img:
            kind = "cpu"
        elif any(k in img for k in ("nvidia.png", "ati.png", "amd.png", "gpu")):
            kind = "gpu"
        elif any(k in img for k in ("mainboard", "hdd", "ram.png", "chip.png")):
            kind = "other"
        t = _parse_temp(node.get("Value")) if node.get("Type", "Temperature") == "Temperature" else None
        if t is not None and not node.get("Children") and kind in ("cpu", "gpu") and 0 < t < 125:
            (cpu if kind == "cpu" else gpu)[text] = t
        for ch in node.get("Children") or []:
            walk(ch, kind)

    walk(data, None)

    def pick(d, preferred):
        for p in preferred:
            for name, t in d.items():
                if p in name.lower():
                    return round(t)
        return round(max(d.values())) if d else None

    return (pick(cpu, ["package", "tctl", "tdie", "core max", "core average"]),
            pick(gpu, ["gpu core", "core", "hot spot"]))


_nvsmi = None


def nvidia_smi():
    """(gpu_temp, gpu_load) from nvidia-smi, or (None, None)."""
    global _nvsmi
    if _nvsmi is None:
        import shutil
        _nvsmi = shutil.which("nvidia-smi") or ""
        if not _nvsmi and IS_WIN:
            p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
            _nvsmi = p if os.path.exists(p) else ""
    if not _nvsmi:
        return None, None
    try:
        import subprocess
        out = subprocess.run([_nvsmi, "--query-gpu=temperature.gpu,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=5, creationflags=0x08000000 if IS_WIN else 0).stdout
        t, u = (x.strip() for x in out.splitlines()[0].split(","))
        return int(float(t)), int(float(u))
    except Exception:
        return None, None


def temps_linux():
    best = None
    base = "/sys/class/thermal"
    try:
        for z in os.listdir(base):
            if not z.startswith("thermal_zone"):
                continue
            try:
                with open(f"{base}/{z}/type") as f:
                    typ = f.read().strip()
                with open(f"{base}/{z}/temp") as f:
                    t = int(f.read()) / 1000
            except (OSError, ValueError):
                continue
            if typ in ("x86_pkg_temp", "cpu-thermal", "k10temp") or best is None:
                best = t
    except OSError:
        pass
    return (round(best) if best else None), None


class Stats:
    def __init__(self):
        self.cpu = CpuMeter()

    def quick(self):
        """CPU + RAM only (instant)."""
        r, total = ram()
        return {"cpu": self.cpu.read(), "ram": r, "ramgb": total}

    def full(self):
        """Everything, including GPU load and temperatures (~0.5-1 s)."""
        out = self.quick()
        ct, gt = temps_from_lhm() if IS_WIN else temps_linux()
        gpu = gpu_load_windows() if IS_WIN else None
        if gt is None or gpu is None:
            nt, nu = nvidia_smi()
            gt = gt if gt is not None else nt
            gpu = gpu if gpu is not None else nu
        out.update({"gpu": gpu, "ct": ct, "gt": gt})
        return out
