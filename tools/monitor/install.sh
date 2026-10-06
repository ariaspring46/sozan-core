#!/usr/bin/env bash
# C — install the sozan monitor on this (home) machine.
# Repo copy stays the source of truth; runtime lives in ~/local-ai/monitor.
set -euo pipefail

REPO_TOOLS="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$HOME/local-ai/monitor"
UNITS="$HOME/.config/systemd/user"

mkdir -p "$RUNTIME" "$UNITS"
install -m 750 "$REPO_TOOLS/sozan_monitor.py" "$RUNTIME/sozan_monitor.py"

cat > "$UNITS/sozan-monitor.service" <<EOF
[Unit]
Description=Sozan monitor pass (storefronts, api/app/landing, heartbeat)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $RUNTIME/sozan_monitor.py run
EOF

cat > "$UNITS/sozan-monitor.timer" <<EOF
[Unit]
Description=Run sozan monitor every 5 minutes

[Timer]
OnBootSec=2min
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > "$UNITS/sozan-monitor-summary.service" <<EOF
[Unit]
Description=Sozan nightly summary (21:30 Tehran)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $RUNTIME/sozan_monitor.py summary
EOF

cat > "$UNITS/sozan-monitor-summary.timer" <<EOF
[Unit]
Description=Sozan nightly summary at 21:30

[Timer]
OnCalendar=21:30
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sozan-monitor.timer sozan-monitor-summary.timer
systemctl --user list-timers 'sozan-monitor*' --no-pager
