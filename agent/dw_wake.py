"""
Wake-on-LAN: send magic packets, and work out whether THIS laptop can be woken.

The capability check reads (no admin needed):
  * which network adapter is in use (Wi-Fi or Ethernet), its MAC and broadcast address
  * what sleep the laptop uses (classic S3 sleep or Modern Standby)
  * whether Windows Fast Startup is on (it blocks waking from shutdown)
  * whether the adapter is allowed to wake the computer (powercfg /devicequery wake_armed)
  * whether "Wake on Magic Packet" is enabled in the adapter's driver settings
Then it gives a verdict for waking from SLEEP and from SHUTDOWN, plus how to fix it.
"""
import os
import re
import socket
import sys

IS_WIN = sys.platform == "win32"
WOL_PORTS = tuple(int(p) for p in os.environ.get("DW_WOL_PORTS", "9,7").split(","))


# ---------------------------------------------------------------------------- sending
def magic_packet(mac):
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(hexmac) != 12:
        raise ValueError(f"bad MAC address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(hexmac) * 16


def send_magic(mac, broadcast=None):
    """Send the packet to the subnet broadcast and 255.255.255.255 on ports 9 and 7."""
    pkt = magic_packet(mac)
    targets = [t for t in dict.fromkeys([broadcast, "255.255.255.255"]) if t]
    sent = 0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            for port in WOL_PORTS:
                try:
                    s.sendto(pkt, (t, port))
                    sent += 1
                except OSError:
                    pass
    finally:
        s.close()
    return sent


# ---------------------------------------------------------------------------- helpers
def local_ip():
    """IP of the interface that reaches the internet (no packet is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 53))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def broadcast_of(ip, mask):
    try:
        a = int.from_bytes(socket.inet_aton(ip), "big")
        m = int.from_bytes(socket.inet_aton(mask), "big")
        return socket.inet_ntoa(((a & m) | (~m & 0xFFFFFFFF)).to_bytes(4, "big"))
    except OSError:
        return None


def _run(args):
    import subprocess
    try:
        r = subprocess.run(args, capture_output=True, timeout=15,
                           creationflags=0x08000000 if IS_WIN else 0)
        enc = "oem" if IS_WIN else "utf-8"
        return r.stdout.decode(enc, errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------- Windows
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    class IP_ADDR_STRING(ctypes.Structure):
        pass

    IP_ADDR_STRING._fields_ = [("Next", ctypes.POINTER(IP_ADDR_STRING)),
                               ("IpAddress", ctypes.c_char * 16), ("IpMask", ctypes.c_char * 16),
                               ("Context", wintypes.DWORD)]

    class IP_ADAPTER_INFO(ctypes.Structure):
        pass

    IP_ADAPTER_INFO._fields_ = [
        ("Next", ctypes.POINTER(IP_ADAPTER_INFO)), ("ComboIndex", wintypes.DWORD),
        ("AdapterName", ctypes.c_char * 260), ("Description", ctypes.c_char * 132),
        ("AddressLength", wintypes.UINT), ("Address", ctypes.c_ubyte * 8),
        ("Index", wintypes.DWORD), ("Type", wintypes.UINT), ("DhcpEnabled", wintypes.UINT),
        ("CurrentIpAddress", ctypes.POINTER(IP_ADDR_STRING)),
        ("IpAddressList", IP_ADDR_STRING), ("GatewayList", IP_ADDR_STRING),
        ("DhcpServer", IP_ADDR_STRING), ("HaveWins", wintypes.BOOL),
        ("PrimaryWinsServer", IP_ADDR_STRING), ("SecondaryWinsServer", IP_ADDR_STRING),
        ("LeaseObtained", ctypes.c_int64), ("LeaseExpires", ctypes.c_int64)]

    def _active_adapter():
        ip = local_ip()
        iphlp = ctypes.WinDLL("iphlpapi")
        size = wintypes.ULONG(0)
        iphlp.GetAdaptersInfo(None, ctypes.byref(size))
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if iphlp.GetAdaptersInfo(buf, ctypes.byref(size)) != 0:
            return None
        node = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO))
        first = None
        while node:
            a = node.contents
            addr, mask = a.IpAddressList.IpAddress.decode(), a.IpAddressList.IpMask.decode()
            info = {
                "guid": a.AdapterName.decode(errors="replace"),
                "desc": a.Description.decode("mbcs", errors="replace"),
                "mac": ":".join(f"{b:02X}" for b in a.Address[:a.AddressLength]),
                "conn": {6: "ethernet", 71: "wifi"}.get(a.Type, "other"),
                "ip": addr, "bcast": broadcast_of(addr, mask),
            }
            if addr == ip:
                return info
            if first is None and addr != "0.0.0.0" and a.GatewayList.IpAddress.decode() not in ("", "0.0.0.0"):
                first = info
            node = a.Next
        return first

    def _power_caps():
        """Selected fields of SYSTEM_POWER_CAPABILITIES (byte offsets from winnt.h)."""
        buf = (ctypes.c_ubyte * 256)()
        if not ctypes.WinDLL("powrprof").GetPwrCapabilities(buf):
            return {}
        return {"s3": bool(buf[5]), "hibernate": bool(buf[6]), "hiberfile": bool(buf[8]),
                "modern_standby": bool(buf[20]), "ms_network": bool(buf[23])}

    def _reg_value(root, path, name):
        import winreg
        try:
            with winreg.OpenKey(root, path) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None

    def _fast_startup(caps):
        import winreg
        v = _reg_value(winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled")
        return bool(v) and caps.get("hiberfile", True)

    def _magic_setting(guid):
        """True/False from the driver's 'Wake on Magic Packet' setting, None if unknown."""
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as cls:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(cls, i)
                    except OSError:
                        return None
                    i += 1
                    if not sub.isdigit():
                        continue
                    p = base + "\\" + sub
                    if (_reg_value(winreg.HKEY_LOCAL_MACHINE, p, "NetCfgInstanceId") or "").lower() != guid.lower():
                        continue
                    for name in ("*WakeOnMagicPacket", "WakeOnMagicPacket", "*WakeOnMagicPkt"):
                        v = _reg_value(winreg.HKEY_LOCAL_MACHINE, p, name)
                        if v is not None:
                            return str(v).strip() not in ("0", "")
                    return None
        except OSError:
            return None

    def _wake_armed(desc):
        out = _run(["powercfg", "/devicequery", "wake_armed"])
        if not out.strip():
            return None
        names = [l.strip().lower() for l in out.splitlines() if l.strip()]
        return desc.lower() in names or any(desc.lower() in n for n in names)

    def raw_capability():
        ad = _active_adapter() or {}
        caps = _power_caps()
        out = {"conn": ad.get("conn", "unknown"), "mac": ad.get("mac"), "ip": ad.get("ip"),
               "bcast": ad.get("bcast"), "adapter": ad.get("desc"),
               "s3": caps.get("s3"), "modern_standby": caps.get("modern_standby"),
               "ms_network": caps.get("ms_network"), "fast_startup": _fast_startup(caps)}
        if ad.get("desc"):
            out["armed"] = _wake_armed(ad["desc"])
            out["magic"] = _magic_setting(ad["guid"])
        return out

    def last_wake_source(adapter_desc):
        """'network' if the last wake-up was caused by the network adapter."""
        out = _run(["powercfg", "/lastwake"])
        if not out:
            return None
        if adapter_desc and adapter_desc.lower() in out.lower():
            return "network"
        return "other"

    def enable_wake(adapter_desc):
        """Needs an administrator prompt. Lets the adapter wake the PC."""
        return _run(["powercfg", "/deviceenablewake", adapter_desc])

# ---------------------------------------------------------------------------- Linux
else:
    def raw_capability():
        ip = local_ip()
        out = {"conn": "unknown", "mac": None, "ip": ip, "bcast": None, "adapter": None,
               "s3": os.path.exists("/sys/power/mem_sleep"), "modern_standby": False,
               "ms_network": False, "fast_startup": False, "armed": None, "magic": None}
        try:
            lines = _run(["ip", "-o", "-4", "addr", "show"]).splitlines()
            for line in lines:
                parts = line.split()
                if ip and f"{ip}/" in line:
                    iface = parts[1]
                    out["adapter"] = iface
                    if "brd" in parts:
                        out["bcast"] = parts[parts.index("brd") + 1]
                    out["conn"] = "wifi" if os.path.exists(f"/sys/class/net/{iface}/wireless") else "ethernet"
                    with open(f"/sys/class/net/{iface}/address") as f:
                        out["mac"] = f.read().strip().upper()
        except Exception:
            pass
        if out["ip"] and not out["bcast"]:
            out["bcast"] = broadcast_of(out["ip"], "255.255.255.0")
        return out

    def last_wake_source(adapter_desc):
        return None

    def enable_wake(adapter_desc):
        return "Use: sudo ethtool -s <interface> wol g"


# ---------------------------------------------------------------------------- verdict
def verdict(c):
    """Adds sleep / off verdicts ('yes', 'maybe', 'no', '?') and plain-language tips."""
    tips = []
    adapter = c.get("adapter") or "your network adapter"
    if c.get("conn") == "unknown" or not c.get("mac"):
        c.update(sleep="?", off="?", tips=["Couldn't find the active network adapter."])
        return c

    if c.get("armed") is False:
        sleep = "no"
        tips.append(f"Allow it: Device Manager → Network adapters → {adapter} → Power Management → "
                    "tick 'Allow this device to wake the computer'. (Or run the installer's "
                    "'--enable-wake' command as administrator.)")
    elif c.get("magic") is False:
        sleep = "no"
        tips.append(f"Device Manager → {adapter} → Advanced → 'Wake on Magic Packet' → Enabled.")
    elif c["conn"] == "ethernet":
        sleep = "yes" if c.get("armed") else "maybe"
    elif c.get("modern_standby"):
        sleep = "maybe"
        tips.append("This laptop uses Modern Standby: Wi-Fi may stay connected while asleep. "
                    "Tap 'Test wake-up' to find out.")
    else:
        sleep = "maybe"
        tips.append("Over Wi-Fi this only works if the Wi-Fi card supports 'Wake on Wireless LAN'. "
                    "Tap 'Test wake-up' to find out.")

    if c["conn"] != "ethernet":
        off = "no"
        tips.append("Turning on from SHUT DOWN needs an Ethernet cable. Use Sleep instead of Off.")
    elif c.get("fast_startup"):
        off = "no"
        tips.append("Turn off Fast Startup: Control Panel → Power Options → 'Choose what the power "
                    "buttons do' → untick 'Turn on fast startup'.")
    else:
        off = "maybe"
        tips.append("Also enable 'Wake on LAN' (or 'Power on by PCIe') in the BIOS.")

    tips.append("Keep the charger plugged in. Most laptops won't wake on battery.")
    c.update(sleep=sleep, off=off, tips=tips)
    return c


def capability():
    try:
        return verdict(raw_capability())
    except Exception as e:
        return {"conn": "unknown", "sleep": "?", "off": "?", "tips": [f"Check failed: {e}"]}


if __name__ == "__main__":                       # python dw_wake.py  -> print the report
    import json
    print(json.dumps(capability(), indent=2, ensure_ascii=False))
