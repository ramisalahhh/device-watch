"""Unit tests for the laptop history (python tests/test_history.py)."""
import json
import os
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
from dw_history import History, day_bounds  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   -> {detail}"))
    if not ok and os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=History test failed::{name} {detail}")


def write(h, rows):
    with open(h.path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    tmp = tempfile.mkdtemp()
    h = History(tmp)
    d1, d1_end = day_bounds("2026-10-18")
    d2, _ = day_bounds("2026-10-19")
    H = 3600
    rows = [
        [d1 + 8 * H, "on", "boot", {"b": 1}],
        [d1 + 9 * H, "st", "FIFA 26"],
        [d1 + 10 * H, "cl", "FIFA 26", {"dur": 3600, "ct": 88}],
        [d1 + 10 * H, "st", "Chrome", {"q": 1}],
        [d1 + 12 * H, "sl"],                                  # sleep closes Chrome (2 h)
        [d1 + 13 * H, "wk", None, {"by": "network"}],
        [d1 + 23 * H, "st", "FIFA 26"],                       # game across midnight
        [d2 + 1 * H, "cl", "FIFA 26", {"dur": 7200}],
        [d2 + 2 * H, "off"],
        [d2 + 3 * H, "on", "boot", {"b": 2}],
    ]
    write(h, rows)
    now = d2 + 5 * H                                          # laptop still on at 05:00

    with mock.patch("time.time", return_value=now):
        day1 = h.day("2026-10-18")
        day2 = h.day("2026-10-19")
        week = h.week(7)
        brief = h.today_brief()

    # day 1: on 08-12 (4 h) + 13-24 (11 h) = 15 h
    check("day1 on-time = 15h", day1["on"] == 15 * H, day1["on"])
    check("day1 FIFA = 1h + 1h before midnight", day1["apps"].get("FIFA 26") == 2 * H, day1["apps"])
    check("day1 Chrome closed by sleep = 2h", day1["apps"].get("Chrome") == 2 * H, day1["apps"])
    check("quiet apps flagged", day1["quiet"] == ["Chrome"], day1["quiet"])
    check("day1 events listed", len(day1["ev"]) == 7, len(day1["ev"]))
    # day 2: 00-02 (2 h) + 03-05 now (2 h) = 4 h ; FIFA 00-01 = 1 h
    check("day2 on-time = 4h (incl. ongoing)", day2["on"] == 4 * H, day2["on"])
    check("day2 FIFA after midnight = 1h", day2["apps"].get("FIFA 26") == 1 * H, day2["apps"])
    check("week has 7 days ending today", len(week) == 7 and week[-1]["day"] == "2026-10-19",
          [w["day"] for w in week])
    check("week hides quiet apps", "Chrome" not in week[-2]["apps"], week[-2])
    check("today brief", brief["on"] == 4 * H and brief["top"][0][0] == "FIFA 26", brief)

    # crash: laptop was up, then nothing; alive file says 06:00; new boot at 09:00
    write(h, [[d2 + 3 * H, "on", "boot", {"b": 2}], [d2 + 4 * H, "st", "FIFA 26"]])
    with open(h.alive_path, "w") as f:
        f.write(str(int(d2 + 6 * H)))
    with mock.patch("time.time", return_value=d2 + 9 * H):
        h.startup(boot_id=3, fresh_boot=True)
        rows = h.read()
        day2 = h.day("2026-10-19")
    codes = [r[1] for r in rows]
    check("crash -> open game closed at last alive", rows[2][:2] == [d2 + 6 * H, "cl"], rows)
    check("crash -> 'lost' then 'on'", codes[-2:] == ["lost", "on"], codes)
    check("crash on-time ends at last alive", day2["on"] == 3 * H, day2["on"])

    # agent restart in the same boot: no 'lost', on-time continues
    write(h, [[d2 + 3 * H, "on", "boot", {"b": 2}]])
    with mock.patch("time.time", return_value=d2 + 4 * H):
        h.startup(boot_id=2, fresh_boot=False)
    with mock.patch("time.time", return_value=d2 + 5 * H):
        day2 = h.day("2026-10-19")
    codes = [r[1] for r in h.read()]
    check("agent restart -> 'rs', not 'lost'", codes == ["on", "rs"], codes)
    check("agent restart keeps on-time", day2["on"] == 2 * H, day2["on"])

    # size cap: lots of events still fit in one ntfy message
    many = [[d2 + i * 30, "st" if i % 2 == 0 else "cl", "Chrome", {"q": 1}] for i in range(600)]
    write(h, [[d2, "on", "boot", {"b": 9}]] + many)
    with mock.patch("time.time", return_value=d2 + 8 * H):
        big = h.day("2026-10-19")
    size = len(json.dumps(big, separators=(",", ":"), ensure_ascii=False).encode())
    check("day reply fits in one message (<3.6 KB)", size <= 3600, size)

    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
