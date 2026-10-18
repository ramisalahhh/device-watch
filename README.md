# DeviceWatch 💻⌚

See what your laptops are doing **on your phone and Redmi Watch**, and **lock / sleep / restart / shut them down** from your phone.

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
| Disk | **zero writes** while running. No database, no logs (unless you pass `--log`, capped at 200 KB) |
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

### 3. Laptop 2
Same steps, but **paste the same topic and secret** in the wizard and use a different name (`Laptop-2`).

### 4. DeviceWatch Android app
A native Android app (`android-app/`, Java, no libraries, about 100 KB):

- **Dashboard:** a card for each laptop with online/sleeping/offline status, current game, battery, idle time, and uptime.
- **Power buttons:** Lock · Sleep · Restart · Off, plus Status and Cancel. Each asks for confirmation before acting.
- **Live notifications** with the same buttons. Enable DeviceWatch in Mi Fitness and they reach your watch. With this on, you don't need the ntfy app.
- Starts again automatically after the phone reboots.

**Install:** download `DeviceWatch.apk` from this repo's **Releases** page on your phone, then tap it and allow "Install unknown apps" when asked. Open it, tap ⚙, and enter the same topic and secret as your laptops. Then press the two HyperOS buttons on that screen (background activity and Autostart).

**Build it yourself:** every push to `main` builds the APK with GitHub Actions (`.github/workflows/build.yml`) and publishes it to Releases. You can also open `android-app/` in Android Studio.

`phone-app/index.html` is the same dashboard as a web page, for use from a laptop browser.

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
- Commands older than 3 minutes are ignored, so old messages can't be replayed later.

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
agent/      device_agent.py, config.example.json, Windows + Linux installers
monitor/    monitor.py, Dockerfile, docker-compose.yml (+ optional self-hosted ntfy)
phone-app/  index.html  (control app, single file)
tests/      mock_ntfy.py + test_e2e.py  (python tests/test_e2e.py, Linux)
```
