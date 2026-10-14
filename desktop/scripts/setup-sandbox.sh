#!/usr/bin/env bash
# Let Electron's Chromium sandbox start on Ubuntu 23.10+ / 24.04 (and other distros that restrict
# unprivileged user namespaces with AppArmor) WITHOUT falling back to --no-sandbox.
#
# Preferred: an AppArmor profile that grants `userns` to this one Electron binary (what Ubuntu
# recommends; survives `npm install`). Fallback: make chrome-sandbox setuid root (must be redone
# after every `npm install`, because npm re-extracts the file as your user).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$DIR/node_modules/electron/dist/electron"
HELPER="$DIR/node_modules/electron/dist/chrome-sandbox"
PROFILE=/etc/apparmor.d/hermes-trader-electron

if [ ! -x "$BIN" ]; then
  echo "Electron not found at $BIN. Run 'npm install' first." >&2
  exit 1
fi

restricted="$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)"

if [ "$restricted" = "1" ] && command -v apparmor_parser >/dev/null 2>&1; then
  echo "AppArmor restricts user namespaces: installing $PROFILE for $BIN"
  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
# Installed by hermes-trader desktop/scripts/setup-sandbox.sh
abi <abi/4.0>,
include <tunables/global>

profile hermes-trader-electron "$BIN" flags=(unconfined) {
  userns,

  include if exists <local/hermes-trader-electron>
}
EOF
  sudo install -m 0644 "$tmp" "$PROFILE"
  rm -f "$tmp"
  if sudo apparmor_parser -r "$PROFILE"; then
    echo "Done. Start the app with: npm start"
    exit 0
  fi
  echo "apparmor_parser rejected the profile; falling back to a setuid sandbox helper." >&2
  sudo rm -f "$PROFILE"
fi

echo "Making chrome-sandbox setuid root (repeat this after every 'npm install')"
sudo chown root:root "$HELPER"
sudo chmod 4755 "$HELPER"
echo "Done. Start the app with: npm start"
