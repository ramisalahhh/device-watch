#!/usr/bin/env sh
# DeviceWatch - Linux installer (systemd user service). Remote power commands
# use systemctl/loginctl, which work for the logged-in desktop user on most distros.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
TARGET="$HOME/.local/share/devicewatch"
mkdir -p "$TARGET" "$HOME/.config/systemd/user"
cp "$HERE/device_agent.py" "$HERE/config.example.json" "$TARGET/"
[ -f "$TARGET/config.json" ] || (cd "$TARGET" && python3 device_agent.py --setup)

cat > "$HOME/.config/systemd/user/devicewatch.service" <<EOF
[Unit]
Description=DeviceWatch agent
After=network-online.target

[Service]
ExecStart=/usr/bin/env python3 $TARGET/device_agent.py
Restart=always
RestartSec=10
Nice=10
MemoryMax=40M

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now devicewatch.service
(cd "$TARGET" && python3 device_agent.py --test)
echo "Installed. Logs: journalctl --user -u devicewatch -f"
