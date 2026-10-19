"""End-to-end test: mock ntfy + agent (dry-run power actions) + monitor.
Run:  python tests/test_e2e.py   (Linux)"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8099
SERVER = f"http://127.0.0.1:{PORT}"
TOPIC, SECRET = "dw-test", "s3cret"
procs = []
results = []


def spawn(args, env=None):
    p = subprocess.Popen(args, env={**os.environ, **(env or {})},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def msgs(topic, since="1h"):
    with urllib.request.urlopen(f"{SERVER}/{topic}/json?poll=1&since={since}") as r:
        return [json.loads(l) for l in r.read().decode().splitlines() if l]


def wait_for(topic, pred, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        for m in msgs(topic):
            if pred(m):
                return m
        time.sleep(0.5)
    return None


def check(name, ok, detail=None):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or detail is None else f"   -> {str(detail)[:300]}"))
    if not ok and os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=Test failed::{name}")   # shows up as an annotation on the run


def cmd(c, to="Test-PC", key=SECRET, reply="notify", **extra):
    body = json.dumps({"cmd": c, "to": to, "key": key, "reply": reply, **extra}).encode()
    urllib.request.urlopen(urllib.request.Request(f"{SERVER}/{TOPIC}-cmd", data=body,
                                                  method="POST")).read()


def rss_kb(pid):
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS"):
            return int(line.split()[1])


def main():
    spawn([sys.executable, str(ROOT / "tests/mock_ntfy.py"), str(PORT)])
    time.sleep(0.8)
    tmp = Path(tempfile.mkdtemp())
    cfg = {"device_name": "Test-PC", "emoji": "🧪", "server": SERVER, "topic": TOPIC,
           "secret": SECRET, "check_seconds": 2, "heartbeat_minutes": 1,
           "action_delay_seconds": 2,
           "apps": [{"label": "Fake Game", "emoji": "⚽", "verb": "playing",
                     "process": ["dw_fake_game"]}]}
    (tmp / "config.json").write_text(json.dumps(cfg))
    env = {"DW_CONFIG": str(tmp / "config.json"), "DW_DRY_RUN": "1", "DW_DATA": str(tmp),
           "DW_WOL_PORTS": "40009"}

    agent = spawn([sys.executable, str(ROOT / "agent/device_agent.py")], env)
    check("online notification", wait_for(TOPIC, lambda m: "🟢" in m.get("title", "")
                                          and m.get("actions")))
    check("startup heartbeat", wait_for(TOPIC + "-hb", lambda m: '"s":"up"' in m["message"]))

    # fake game: a process whose name is dw_fake_game
    fake = tmp / "dw_fake_game"
    fake.symlink_to("/bin/sleep")
    game = spawn([str(fake), "300"])
    check("game start detected", wait_for(TOPIC, lambda m: "playing Fake Game" in m.get("title", "")))
    game.kill(); game.wait()   # reap, so it leaves the process table
    check("game stop + duration", wait_for(TOPIC, lambda m: "closed Fake Game" in m.get("title", "")))

    cmd("status")
    check("status -> notification", wait_for(TOPIC, lambda m: "status" in m.get("title", "")))
    cmd("status", to="*", reply="app")
    check("status -> app (hb topic)", wait_for(TOPIC + "-hb", lambda m: '"type":"status"' in m["message"]))

    cmd("shutdown", key="wrong")
    time.sleep(2)
    check("bad key ignored", not any("will shut down" in m.get("title", "") for m in msgs(TOPIC)))

    cmd("shutdown")
    check("shutdown countdown + cancel button",
          wait_for(TOPIC, lambda m: "will shut down" in m.get("title", "") and m.get("actions")))
    cmd("cancel")
    check("cancel acknowledged", wait_for(TOPIC, lambda m: "cancelled" in m.get("title", "")))
    time.sleep(3)
    check("cancelled action did not run",
          not any('"dryrun"' in m["message"] for m in msgs(TOPIC + "-hb")))

    cmd("restart")
    check("receipt (ack) sent for commands", wait_for(TOPIC + "-hb", lambda m: '"type":"ack"' in m["message"]))
    check("restart runs after delay",
          wait_for(TOPIC + "-hb", lambda m: '"cmd":"restart"' in m["message"], timeout=8))

    seen_acks = {m["id"] for m in msgs(TOPIC + "-hb") if '"type":"ack"' in m["message"]}
    time.sleep(3)   # let the earlier restart's delayed action finish
    # network blip: stream is cut, a command is sent while disconnected -> must still arrive
    urllib.request.urlopen(f"{SERVER}/__drop?secs=3").read()
    time.sleep(0.5)
    cmd("restart")
    check("command sent during outage is delivered after reconnect",
          wait_for(TOPIC + "-hb", lambda m: '"type":"ack"' in m["message"] and '"restart"' in m["message"]
                   and m["id"] not in seen_acks, timeout=25))

    cmd("lock", to="Other-PC")
    time.sleep(2)
    check("command for other device ignored",
          not any('"cmd":"lock"' in m["message"] for m in msgs(TOPIC + "-hb")))

    # ---- v1.1 features ----------------------------------------------------
    hb = lambda pred, timeout=15: wait_for(TOPIC + "-hb", lambda m: pred(json.loads(m["message"])), timeout)
    cmd("status", reply="app")
    st = hb(lambda d: d.get("type") == "status" and "cpu" in d)
    st = json.loads(st["message"]) if st else {}
    check("status has CPU/RAM stats", isinstance(st.get("cpu"), int) and isinstance(st.get("ram"), int), st)
    check("status has today's summary", "on" in st.get("td", {}), st.get("td"))
    check("status has wake-up report", st.get("wol", {}).get("sleep") in ("yes", "maybe", "no", "?"),
          st.get("wol"))

    cmd("history", reply="app", rid="r1")
    h = hb(lambda d: d.get("type") == "hist" and d.get("rid") == "r1")
    h = json.loads(h["message"]) if h else {}
    codes = [e[1] for e in h.get("ev", [])]
    check("history: day timeline", "on" in codes and "st" in codes and "cl" in codes, codes)
    check("history: game time counted", "Fake Game" in h.get("apps", {}), h.get("apps"))
    cmd("history", reply="app", range="week", rid="r2")
    w = hb(lambda d: d.get("type") == "histw" and d.get("rid") == "r2")
    w = json.loads(w["message"]) if w else {}
    check("history: 7-day totals", len(w.get("week", [])) == 7, w)

    cmd("msg", text="Dinner is ready 🍽️")
    check("message shown on screen", hb(lambda d: d.get("type") == "dryrun" and d.get("cmd") == "msg"
                                         and "Dinner" in d.get("text", "")))
    check("message read receipt", wait_for(TOPIC, lambda m: "read your message" in m.get("title", "")))

    cmd("ring")
    check("ring started", hb(lambda d: d.get("type") == "dryrun" and d.get("cmd") == "ring"))
    check("ring -> found notification", wait_for(TOPIC, lambda m: "found!" in m.get("title", "")))

    import socket as _s
    udp = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 40009))
    udp.settimeout(10)
    cmd("wake", to="*", target="Other-PC", mac="AA:BB:CC:DD:EE:FF", bcast="127.0.0.1")
    try:
        pkt = udp.recv(200)
    except OSError:
        pkt = b""
    check("wake relay sends magic packet", pkt == b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16, pkt[:12])
    check("wake relay reported", hb(lambda d: d.get("type") == "relay" and d.get("target") == "Other-PC"))
    cmd("wake", to="*", target="Test-PC", mac="AA:BB:CC:DD:EE:FF", bcast="127.0.0.1")
    udp.settimeout(3)
    try:
        udp.recv(200)
        own = True
    except OSError:
        own = False
    check("laptop doesn't 'wake' itself", not own)
    udp.close()

    kb = rss_kb(agent.pid)
    cpu = sum(int(x) for x in Path(f"/proc/{agent.pid}/stat").read_text().split()[13:15]) / os.sysconf("SC_CLK_TCK")
    print(f"     agent RSS: {kb/1024:.1f} MB, total CPU so far: {cpu:.2f}s")
    check("agent RAM under 30 MB", kb < 30 * 1024)

    # monitor: unexpected disappearance -> alert ; graceful shutdown -> no alert
    mon = spawn([sys.executable, str(ROOT / "monitor/monitor.py")],
                {"DW_SERVER": SERVER, "DW_TOPIC": TOPIC, "DW_OFFLINE_AFTER": "0.15",
                 "DW_POLL_SECONDS": "2"})
    time.sleep(3)
    cmd("status", to="*", reply="app")             # fresh heartbeat right before death
    time.sleep(3)
    agent.send_signal(signal.SIGKILL)              # simulate battery death
    check("monitor: offline alert after silent death",
          wait_for(TOPIC, lambda m: "went offline" in m.get("title", ""), timeout=25))

    agent2 = spawn([sys.executable, str(ROOT / "agent/device_agent.py")],
                   {**env, "DW_CONFIG": str(tmp / "config.json")})
    time.sleep(4)
    since = msgs(TOPIC)[-1]["id"]
    agent2.send_signal(signal.SIGTERM)            # graceful
    check("graceful shutdown notification",
          wait_for(TOPIC, lambda m: "shutting down" in m.get("title", "")))
    time.sleep(16)
    check("monitor silent after graceful shutdown",
          not any("went offline" in m.get("title", "") for m in msgs(TOPIC, since)))

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for p in procs:
            p.kill()
    sys.exit(code)
