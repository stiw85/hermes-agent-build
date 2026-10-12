#!/usr/bin/env bash
# One-shot setup for this fork: Hermes Agent from this repository plus the vendored Herald OS
# desktop, wired together. After it finishes, `herald` (or "Herald OS" in the app menu) starts
# the GUI against the Hermes it installed.
#
#   bash scripts/setup-herald.sh                 # from a checkout
#   curl -fsSL https://raw.githubusercontent.com/stiw85/hermes-agent-build/claude/native-memory/scripts/setup-herald.sh | bash
#
# Idempotent: re-running updates the Hermes checkout (scripts/install.sh's update path) and
# re-runs Herald's own bootstrap, which is safe to repeat. Overrides:
#   HERMES_REPO_URL    the repository to install from (default: this fork)
#   HERMES_BRANCH      the branch to install         (default: claude/native-memory)
#   HERMES_HOME        the Hermes home               (default: ~/.hermes)
# HERALD_SETUP_DRY_RUN=1 prints the plan without changing anything (used by the tests).
set -euo pipefail

REPO_URL="${HERMES_REPO_URL:-https://github.com/stiw85/hermes-agent-build.git}"
BRANCH="${HERMES_BRANCH:-claude/native-memory}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CHECKOUT="${HERMES_INSTALL_DIR:-$HERMES_HOME/hermes-agent}"
HERALD_DIR="$CHECKOUT/integrations/herald-os"
BIN_DIR="${HERALD_SETUP_BIN_DIR:-$HOME/.local/bin}"
APP_DIR="${HERALD_SETUP_APP_DIR:-$HOME/.local/share/applications}"
DRY_RUN="${HERALD_SETUP_DRY_RUN:-0}"
NODE_MIN_MAJOR=22
NODE_MIN_MINOR=12

step() { echo "==> $*"; }
note() { echo "    $*"; }
warn() { echo "    WARNING: $*" >&2; }

# In a dry run a missing prerequisite is reported, not fatal, so the plan always prints whole.
need() {
    if [ "$DRY_RUN" = 1 ]; then warn "$1"; return 0; fi
    echo "setup-herald: $1" >&2
    exit 1
}

run() {
    if [ "$DRY_RUN" = 1 ]; then
        echo "    + $*"
        return 0
    fi
    "$@"
}

step "Checking prerequisites"
command -v git >/dev/null 2>&1 || need "git is required (sudo apt install git)"
command -v curl >/dev/null 2>&1 || need "curl is required (sudo apt install curl)"
if command -v node >/dev/null 2>&1; then
    node_version="$(node -v 2>/dev/null | sed 's/^v//')"
    node_major="${node_version%%.*}"
    node_rest="${node_version#*.}"
    node_minor="${node_rest%%.*}"
    case "$node_major$node_minor" in (*[!0-9]*) node_major=0; node_minor=0 ;; esac
    if [ "$node_major" -lt "$NODE_MIN_MAJOR" ] || { [ "$node_major" -eq "$NODE_MIN_MAJOR" ] && [ "$node_minor" -lt "$NODE_MIN_MINOR" ]; }; then
        need "Herald OS needs Node $NODE_MIN_MAJOR.$NODE_MIN_MINOR or newer; this machine has $node_version. On Ubuntu: curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs"
    else
        note "node $node_version"
    fi
else
    need "Node $NODE_MIN_MAJOR.$NODE_MIN_MINOR+ is required. On Ubuntu: curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs"
fi

step "Installing Hermes Agent from $REPO_URL ($BRANCH)"
# Prefer the install.sh beside this script (a checkout run); standalone, fetch it from the same
# repository and branch being installed, so the installer always matches the tree it installs.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
installer="$script_dir/install.sh"
cleanup_dir=""
if [ ! -f "$installer" ]; then
    raw_base="$(printf '%s' "$REPO_URL" | sed -e 's#^https://github.com/#https://raw.githubusercontent.com/#' -e 's#\.git$##')"
    cleanup_dir="$(mktemp -d)"
    installer="$cleanup_dir/install.sh"
    note "fetching installer: $raw_base/$BRANCH/scripts/install.sh"
    run curl -fsSL "$raw_base/$BRANCH/scripts/install.sh" -o "$installer"
fi
run env HERMES_REPO_URL="$REPO_URL" HERMES_HOME="$HERMES_HOME" bash "$installer" --branch "$BRANCH"
[ -n "$cleanup_dir" ] && rm -rf "$cleanup_dir"

step "Wiring in Herald OS from $HERALD_DIR"
if [ ! -f "$HERALD_DIR/scripts/bootstrap.sh" ] && [ "$DRY_RUN" != 1 ]; then
    echo "setup-herald: $HERALD_DIR/scripts/bootstrap.sh is missing; the installed branch has no vendored Herald OS" >&2
    exit 1
fi
# Herald's own bootstrap: npm workspaces, the Electron binary, the bridge plugin link into
# $HERMES_HOME/plugins, `hermes plugins enable herald-os-bridge` and `hermes tools enable herald_os`.
run env HERMES_HOME="$HERMES_HOME" bash "$HERALD_DIR/scripts/bootstrap.sh"

step "Installing the herald launcher"
launcher="$BIN_DIR/herald"
if [ "$DRY_RUN" = 1 ]; then
    echo "    + write $launcher"
    echo "    + write $APP_DIR/herald-os.desktop"
else
    mkdir -p "$BIN_DIR" "$APP_DIR"
    cat >"$launcher" <<LAUNCHER
#!/usr/bin/env bash
# Starts the Herald OS desktop against the Hermes install at $HERMES_HOME.
# Written by scripts/setup-herald.sh; re-run that script after a Hermes update.
set -euo pipefail
HERALD_DIR="$HERALD_DIR"
if [ ! -d "\$HERALD_DIR/node_modules" ]; then
    echo "herald: first run after an update; bootstrapping (a few minutes)..."
    HERMES_HOME="$HERMES_HOME" bash "\$HERALD_DIR/scripts/bootstrap.sh"
fi
cd "\$HERALD_DIR"
exec npm run dev
LAUNCHER
    chmod 755 "$launcher"
    cat >"$APP_DIR/herald-os.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Herald OS
Comment=Agent-native desktop on Hermes Agent
Exec=$launcher
Icon=$HERALD_DIR/apps/desktop/build/icon.png
Terminal=false
Categories=Utility;
DESKTOP
fi
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on PATH; log out and back in (Ubuntu adds it when it exists), or run $launcher directly" ;;
esac

step "Done"
note "start Herald OS with: herald    (or Herald OS in the application menu)"
note "Hermes needs a model provider on first use: hermes setup, or the sign-in card Herald shows"
