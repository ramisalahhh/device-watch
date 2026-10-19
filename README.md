# DeviceWatch 💻⌚

[![Build](https://github.com/ramisalahhh/device-watch/actions/workflows/build.yml/badge.svg)](https://github.com/ramisalahhh/device-watch/actions/workflows/build.yml)
[![Download APK](https://img.shields.io/badge/Download-APK-3DDC84?logo=android&logoColor=white)](https://github.com/ramisalahhh/device-watch/releases/latest)
[![iPhone app](https://img.shields.io/badge/iPhone-web%20app-000000?logo=apple&logoColor=white)](https://ramisalahhh.github.io/device-watch/)
![Python](https://img.shields.io/badge/Python-stdlib%20only-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-monitor-2496ED?logo=docker&logoColor=white)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20Android%20%7C%20iPhone-lightgrey)

See what your laptops are doing **on your phone and Redmi Watch**, and control them from your phone:
lock / sleep / restart / shut down, **show a message on the screen**, **ring it to find it**, and **wake it up**.
Works with any number of laptops/PCs, one at a time or several at once. Apps for **Android** (native) and **iPhone** (web app).

## What's in v1.1

| Feature | Where |
|---|---|
| 📊 **Live stats**: CPU, RAM, GPU load, CPU/GPU temperature | card + device screen; game sessions report average load and peak temperature |
| 🕘 **History**: when each laptop was on, slept or shut down, which games/apps ran how long | device screen: day timeline (‹ › to go back), per-app totals, last 7 days |
| 💬 **Message on screen** | pops up on the laptop; you get "👀 read your message" when someone clicks OK |
| 🔔 **Find my laptop** | max volume + beeping for 60 s until someone clicks OK |
| ⚡ **Wake up** from sleep (Wake-on-LAN) | phone sends the wake signal on home Wi-Fi; your other laptops relay it when you're away |
| ✅ **Wake-up support check** per laptop | Yes / Maybe / No for waking from sleep and from shutdown, with the exact setting to fix, plus a **🧪 Test wake-up** button |
| ☑️ **Control several devices at once** | tap **Select**, tick devices (or **All**), press one button |
| 📱 **iPhone app** | web app: Safari → Share → Add to Home Screen |

## ✨ Highlights

- **CI/CD with GitHub Actions:** every push to `main` runs 47 automated checks (history unit tests + end-to-end tests with a 30 MB RAM guard), builds the Android APK, which is published automatically to [Releases](https://github.com/ramisalahhh/device-watch/releases).
- **Containerized monitoring:** the offline-alert monitor ships with a `Dockerfile` and `docker-compose.yml`, with an optional self-hosted ntfy server.
- **Lightweight by design:** Python standard library only, ~20 MB RAM, ~0.1% CPU, and only a small history file on disk (auto-trimmed to 60 days).
- **Event-driven and reliable:** commands arrive over one idle connection (no polling), with lossless reconnects, receipts and retries.
- **Secure remote control:** secret-authenticated commands with replay protection (commands older than 5 minutes are ignored).

## 🧰 Tech stack

Python (ctypes / Windows APIs) · Java (native Android, no libraries) · GitHub Actions · Docker & Docker Compose · ntfy (HTTP pub/sub) · HTML/JS (installable web app on GitHub Pages) · Wake-on-LAN (UDP)

```
 ┌───────────┐                       ┌──────────┐   notification   ┌──────────────┐  Mi Fitness  ┌─────────┐
 │ Laptop 1  │── events/heartbeat ──▶│          │─────────────────▶│ Phone (ntfy  │────────────▶│ Redmi   │
 │  agent    │◀──── commands ────────│   ntfy   │                  │  app + Web   │             │ Watch   │
 ├───────────┤                       │  server  │◀── commands ─────│  control app)│             └─────────┘
 │ Laptop 2  │◀─────────────────────▶│          │                  └──────────────┘
 └───────────┘                       └────▲─────┘
                       (optional) monitor ┘  alerts if a laptop vanishes without saying goodbye
```

Example notifications:

- `💻 Laptop-1: 🟢 turned on · 🔋 84%` with buttons **🔒 Lock · 😴 Sleep · ⏻ Shut down**
- `💻 Laptop-1: ⚽ playing FIFA 26 (EA FC 26)`
- `💻 Laptop-1: closed FIFA 26 (EA FC 26)` with "after 1h 42m"
- `💻 Laptop-2: 😴 going to sleep` / `🔴 shutting down` / `🪫 battery 7%`
- `💻 Laptop-2: 🔴 went offline` (from the monitor: battery died or Wi-Fi dropped)

## Resource use (built to be tiny)

| | |
|---|---|
| Dependencies | **none**. Python standard library only; Windows APIs are called directly with `ctypes` |
| RAM | ~18-22 MB (most of that is the Python interpreter itself) |
| CPU | ~0.1%. One cheap process snapshot every 5 s; commands arrive over one idle connection, no polling |
| Disk | Only the history file: a few KB per day, auto-trimmed to 60 days (well under 1 MB) |
| Priority | Runs at *below normal* priority, so games always win |
| Network | Only sends on changes, plus a heartbeat every 15 min |

---

## Setup (about 15 minutes)

### 1. Phone
Install the **DeviceWatch Android app** (step 4). It shows the notifications itself.
Alternatively, use the **ntfy** app from the Play Store. Either way:

1. **Important on Xiaomi/HyperOS:** Settings → Apps → (DeviceWatch or ntfy) → **Battery saver: No restrictions** and turn on **Autostart**. Otherwise HyperOS kills it and notifications arrive late.
2. Open **Mi Fitness** → your watch → **Notifications** → enable that app.

### 2. Laptop 1
1. Install Python 3 from <https://python.org/downloads> and tick **"Add python.exe to PATH"**.
2. Unzip this folder, open `agent/`, right-click `install_windows.ps1` → **Run with PowerShell**.
3. The wizard asks for a name (for example `Laptop-1`). Press **Enter** at *Topic* and *Secret* to generate them.
4. It prints your **topic** and **secret**. Save both, they work like a password.
5. In the ntfy app, tap **+** and subscribe to that topic.

A test notification should appear on your phone and watch. ✅

### 3. Laptop 2, PC 3, … (as many as you like)
Same steps, but **paste the same topic and secret** in the wizard and use a different name (`Laptop-2`, `PC-3`).
Each one appears as its own card in the app.

### 4. DeviceWatch Android app
A native Android app (`android-app/`, Java, no libraries, about 100 KB):

- **Dashboard:** a card for each laptop with online/sleeping/offline status, current game, battery, idle time, and uptime.
- **Power buttons:** Lock · Sleep · Restart · Off, plus Status and Cancel. Each asks for confirmation before acting.
- **Live notifications** with the same buttons. Enable DeviceWatch in Mi Fitness and they reach your watch. With this on, you don't need the ntfy app.
- Starts again automatically after the phone reboots.

**Install:** download `DeviceWatch.apk` from this repo's **Releases** page on your phone, then tap it and allow "Install unknown apps" when asked. Open it, tap ⚙, and enter the same topic and secret as your laptops. Then press the two HyperOS buttons on that screen (background activity and Autostart).

**Build it yourself:** every push to `main` builds the APK with GitHub Actions (`.github/workflows/build.yml`) and publishes it to Releases. You can also open `android-app/` in Android Studio.

### 4b. iPhone app (web app)
The same app for iPhone (and any browser), with every feature, is published at
**`https://<your-github-name>.github.io/device-watch/`** by the build.

- **One-time setup on GitHub:** repo **Settings → Pages → Source: GitHub Actions**. Then push or re-run the build.
- **On iPhone:** open the link in **Safari** → Share → **Add to Home Screen**. It opens full-screen like an app.
- **Notifications on iPhone:** install the free **ntfy** app from the App Store and subscribe to your topic. Enable ntfy in Mi Fitness for the watch.
- **Wake-up from iPhone:** Safari can't send the wake signal itself, so your *other laptops* send it (at least one must be on).
- Your topic and secret are stored only on the phone, never in the page, so the public link is safe.

### 5. Offline alerts (optional)
Sleep and shutdown are announced by the laptop itself. A laptop whose **battery dies or Wi-Fi drops** can't say goodbye, so something always-on has to notice the silence. Pick one:

- **Docker** (free cloud VM, Raspberry Pi):
  ```bash
  cd monitor
  # edit DW_TOPIC in docker-compose.yml
  docker compose up -d
  ```
- **Your phone (Termux):**
  ```bash
  pkg install python
  DW_TOPIC=dw-yourtopic python monitor.py
  ```
  Run `termux-wake-lock` first and disable battery optimization for Termux.

---

## Track your games and apps

Edit `%LOCALAPPDATA%\DeviceWatch\config.json` → `"apps"`, then re-run the installer to restart.

```json
{ "label": "FIFA 26 (EA FC 26)", "emoji": "⚽", "verb": "playing", "process": ["FC26.exe"] }
```

**Don't know the .exe name?** Start the game, then run:
```powershell
cd $env:LOCALAPPDATA\DeviceWatch
py device_agent.py --discover
```
It prints the process name of whatever window is in front. You can also check Task Manager → *Details*.

- `"notify": false` tracks the app silently. It still shows in status, but your watch won't buzz (good for Chrome or Discord).
- The FIFA 26 process names in the example are best guesses. Confirm with `--discover`.

## Remote control

| Command | What happens |
|---|---|
| `status` | Replies with the current game/app, battery, idle time, and uptime |
| `lock` | Locks immediately |
| `sleep` | Sleeps after a 30 s countdown |
| `restart` / `shutdown` | 30 s countdown. Windows also shows a warning on screen, so whoever is using the laptop sees it |
| `cancel` | Cancels a pending sleep/restart/shutdown |
| `msg` | Shows your text in a pop-up on the laptop's screen |
| `ring` | Max volume + beeping for 60 s, until someone clicks OK |
| `wake` | Sent to all laptops: the ones that are on send a wake-up packet to the sleeping one |
| `history` | Replies with a day's timeline and totals, or the last 7 days |

You can send these from:
- **Notification buttons** on your phone (watches generally don't show action buttons)
- **The web control app**
- **Anything that can send HTTP**, for example:
  ```bash
  curl -d '{"cmd":"shutdown","to":"Laptop-1","key":"YOUR-SECRET"}' https://ntfy.sh/YOUR-TOPIC-cmd
  ```
  Use `"to":"*"` for all devices.

Settings in `config.json`:
- `action_delay_seconds`: length of the countdown
- `allowed_commands`: remove `"shutdown"` here to disable it on a laptop
- `buttons_in_notifications`: turn the buttons off

## Wake-up (Wake-on-LAN)

Check any laptop: in the app's device screen (**Wake-up support**), or on the laptop:
```powershell
cd $env:LOCALAPPDATA\DeviceWatch
py device_agent.py --wake-check
```
- **From sleep over Wi-Fi:** depends on the Wi-Fi card. Use **🧪 Test wake-up** to find out for sure.
- **From shutdown:** needs an **Ethernet cable**, Windows **Fast Startup off**, and Wake on LAN in the BIOS.
- **Allow the adapter to wake the PC:** run PowerShell **as administrator**, then `py device_agent.py --enable-wake`.
- Keep the charger plugged in. Most laptops won't wake on battery.

## Temperatures

Windows doesn't give apps the CPU temperature. Install the free **LibreHardwareMonitor**, open
*Options → Remote Web Server → Run* (port 8085), and tick *Run On Windows Startup*. DeviceWatch picks it up
automatically. NVIDIA GPU temperature works without it (through `nvidia-smi`).

## Settings worth knowing

| Key | Default | Meaning |
|---|---|---|
| `check_seconds` | 5 | How often to check running apps |
| `heartbeat_minutes` | 15 | "I'm alive" signal for the monitor and web app |
| `notify.idle_minutes` | 0 (off) | Alert after N minutes without keyboard/mouse |
| `notify.battery_low_percent` | 20 | Low battery alert |
| `quiet_hours` | off | Silence normal alerts at night (urgent ones still come through) |
| `show_window_titles` | false | Include window titles in status (privacy) |

## Security: read this

- Your **topic + secret = full control** of your laptops. Don't share them or post screenshots of them.
- On public `ntfy.sh`, anyone who knows a topic name can read it. The random names make guessing impractical. Notification buttons contain the secret, so treat the topic as private too.
- **Stronger setup:** self-host ntfy (template included in `monitor/docker-compose.yml`) with authentication, then put an access token in `"token"`. That also removes public rate limits, so you can set `heartbeat_minutes` to 1 for faster offline detection.
- Commands older than 5 minutes are ignored, so old messages can't be replayed later.
- This repository contains **no secrets**. Your topic and secret live only in `config.json` on each laptop and in the apps.

## Public ntfy.sh limits

The free public server limits how many messages each IP can send per day, and both laptops at home share one IP. That's why the heartbeat defaults to 15 minutes and events are only sent on changes. If you start missing notifications, self-host ntfy.

## Troubleshooting

- **No notifications:** run `py device_agent.py --test`. Check the topic in the ntfy app and the battery settings from Setup step 1.
- **Phone gets them, watch doesn't:** Mi Fitness → Notifications → enable ntfy, and keep Mi Fitness allowed in the background.
- **No "going to sleep" message:** some laptops use *Modern Standby* and never send the classic sleep signal. You'll still get "woke up", and the monitor covers the gap.
- **Run with a log for debugging:** `py device_agent.py -v --log dw.log`
- **Uninstall:** run `agent/uninstall_windows.ps1`.

## Project layout

```
agent/        device_agent.py (core) + dw_stats.py, dw_wake.py, dw_history.py, dw_popup.py,
              config.example.json, Windows + Linux installers
android-app/  native Android app (Java, no libraries)
phone-app/    iPhone / web app (single HTML file + manifest + icons) -> GitHub Pages
monitor/      monitor.py, Dockerfile, docker-compose.yml (+ optional self-hosted ntfy)
tests/        mock_ntfy.py, test_e2e.py (31 checks), test_history.py (16 checks)
```
