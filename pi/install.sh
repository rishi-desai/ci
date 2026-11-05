#!/usr/bin/env bash
# Install or update the CI-gated updater for one app on this Pi. Run it AS YOURSELF from this
# checkout of rishi-desai/ci (normally ~/homelab/ci); it asks for your password once.
#   pi/install.sh <app> <config>     e.g.  pi/install.sh aurora pi/apps/aurora.conf.example
#
# Idempotent. Installs:
#   /etc/ci-gated-update/<app>.conf      the config (root-owned, so the app can't change its commands)
#   /etc/ci-gated-update/ops.env         GH_TOKEN/ALERT_URL (created once from ops.env.example)
#   ci-gated-update@.service/.timer, ci-gated-update-alert@.service   (shared by every app)
#   /etc/sudoers.d/ci-gated-update-<app> exactly the app's restart/pre-deploy commands, nothing else
# then enables ci-gated-update@<app>.timer. Updating this checkout never changes a running
# updater's behavior until you re-run this script.
set -euo pipefail

CI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-}"
SRC_CONF="${2:-}"
ETC=/etc/ci-gated-update
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"

[[ $EUID -ne 0 ]] || { echo "Run this as yourself, not with sudo"; exit 1; }
[[ "$APP" =~ ^[a-z0-9][a-z0-9-]*$ && -r "$SRC_CONF" ]] \
  || { echo "usage: $0 <app> <config>   (app: lowercase letters, digits, dashes)"; exit 1; }

conf() { sed -nE "s/^[[:space:]]*$1=['\"]?([^'\"]*)['\"]?[[:space:]]*$/\1/p" "$SRC_CONF" | tail -n 1; }
[[ "$(conf APP_NAME)" == "$APP" ]] || { echo "APP_NAME in $SRC_CONF must be '$APP'"; exit 1; }
app_dir="$(conf APP_DIR)"
[[ -d "$app_dir/.git" ]] || { echo "APP_DIR '$app_dir' in $SRC_CONF is not a git checkout"; exit 1; }
restart_unit="$(conf RESTART_UNIT)"
pre_deploy_unit="$(conf PRE_DEPLOY_UNIT)"
replaces_timer="$(conf REPLACES_TIMER)"

for tool in git gh flock python3 systemctl visudo; do
  command -v "$tool" >/dev/null || { echo "$tool not found (brew install gh flock)"; exit 1; }
done
gh auth status --hostname github.com >/dev/null 2>&1 \
  || echo ">>> gh is not logged in; deploys will fail until you run gh auth login (or set GH_TOKEN)"

sudo -v  # one password prompt for everything below
echo ">>> Config in $ETC"
sudo install -d -o root -g root -m 755 "$ETC"
sudo install -o root -g root -m 644 "$SRC_CONF" "$ETC/$APP.conf"
if ! sudo test -f "$ETC/ops.env"; then
  sudo install -o root -g "$RUN_GROUP" -m 640 "$CI_DIR/pi/ops.env.example" "$ETC/ops.env"
fi

echo ">>> systemd templates (running as $RUN_USER)"
for unit in ci-gated-update@.service ci-gated-update@.timer ci-gated-update-alert@.service; do
  sed -e "s|@USER@|$RUN_USER|g" -e "s|@GROUP@|$RUN_GROUP|g" -e "s|@CI_DIR@|$CI_DIR|g" \
      "$CI_DIR/pi/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done

# The updater runs unattended, so it can't type a password: allow only this app's units.
SYSTEMCTL="$(command -v systemctl)"
allowed=()
[[ -z "$restart_unit" ]] || allowed+=("$SYSTEMCTL restart $restart_unit")
[[ -z "$pre_deploy_unit" ]] || allowed+=("$SYSTEMCTL start $pre_deploy_unit")
sudoers_path="/etc/sudoers.d/ci-gated-update-$APP"
if (( ${#allowed[@]} )); then
  commands="$(printf '%s, ' "${allowed[@]}")"
  sudoers="$(mktemp)"
  { echo "# Installed by rishi-desai/ci pi/install.sh for ci-gated-update@$APP."
    echo "$RUN_USER ALL=(root) NOPASSWD: ${commands%, }"
  } > "$sudoers"
  sudo visudo -cqf "$sudoers"
  sudo install -o root -g root -m 440 "$sudoers" "$sudoers_path"
  rm -f "$sudoers"
else
  sudo rm -f "$sudoers_path"
fi

sudo systemctl daemon-reload
if [[ -n "$replaces_timer" ]] && systemctl is-enabled --quiet "$replaces_timer" 2>/dev/null; then
  echo ">>> Disabling $replaces_timer: ci-gated-update@$APP replaces it"
  sudo systemctl disable --now "$replaces_timer"
fi
sudo systemctl enable --now "ci-gated-update@$APP.timer"
echo ">>> Installed. Try a run now:   sudo systemctl start ci-gated-update@$APP"
echo ">>> Then read it:               journalctl -u ci-gated-update@$APP -n 20"
echo ">>> Failure alerts: set ALERT_URL in $ETC/ops.env"
