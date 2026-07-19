#!/bin/bash
# Penny — install / uninstall
# Usage: bash install.sh [--uninstall]

set -euo pipefail

PENNY_DIR="$HOME/.penny"
PENNY_CLAUDE="$PENNY_DIR/claude"
PENNY_CLI="$PENNY_DIR/penny"
PLIST_DST="$HOME/Library/LaunchAgents/com.penny.app.plist"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e " ${GREEN}✓${NC} $1"; }
info() { echo -e " ${CYAN}→${NC} $1"; }
err()  { echo -e " ${RED}✗${NC} $1"; }

detect_shell_config() {
    case "$SHELL" in
        */zsh) echo "$HOME/.zshrc" ;;
        */bash)
            if [[ "$(uname)" == "Darwin" ]]; then echo "$HOME/.bash_profile"
            else echo "$HOME/.bashrc"; fi ;;
        */fish) echo "$HOME/.config/fish/config.fish" ;;
        *) echo "$HOME/.profile" ;;
    esac
}

SHELL_CONFIG=$(detect_shell_config)
PENNY_PATH_LINE="export PATH=\"\$HOME/.penny:\$PATH\""

do_uninstall() {
    echo ""; echo "Uninstalling Penny..."; echo ""

    # Remove from shell config
    if [[ -f "$SHELL_CONFIG" ]] && grep -q "penny" "$SHELL_CONFIG" 2>/dev/null; then
        TMP=$(mktemp)
        grep -v "penny" "$SHELL_CONFIG" > "$TMP" 2>/dev/null || true
        mv "$TMP" "$SHELL_CONFIG"
        ok "Removed Penny from $SHELL_CONFIG"
    fi

    # Unload launchd
    if [[ -f "$PLIST_DST" ]]; then
        launchctl unload "$PLIST_DST" 2>/dev/null || true
        rm "$PLIST_DST"
        ok "Unloaded launchd agent"
    fi

    # Remove stop hook from claude settings
    CLAUDE_SETTINGS="$HOME/.claude/settings.json"
    if [[ -f "$CLAUDE_SETTINGS" ]]; then
        TMP=$(mktemp)
        python3 -c "
import json
with open('$CLAUDE_SETTINGS') as f: cfg = json.load(f)
hooks = cfg.get('hooks', {})
stop = hooks.get('Stop', [])
stop = [h for h in stop if 'penny' not in json.dumps(h)]
if stop:
    hooks['Stop'] = stop; cfg['hooks'] = hooks
else:
    cfg.pop('hooks', None)
with open('$TMP', 'w') as f: json.dump(cfg, f, indent=2)
" 2>/dev/null || true
        mv "$TMP" "$CLAUDE_SETTINGS"
        ok "Removed stop hook from Claude settings"
    fi

    # Remove ~/.penny/ stop hook symlink
    rm -f "$HOME/.claude/stop-hooks/penny-hook.py" 2>/dev/null || true

    # Remove all penny files
    if [[ -d "$PENNY_DIR" ]]; then
        rm -rf "$PENNY_DIR"
        ok "Removed $PENNY_DIR"
    fi

    echo ""; echo "  Penny uninstalled. Start a new terminal or run: source $SHELL_CONFIG"; echo ""
    exit 0
}

# Support both direct and via `penny install --uninstall`
if [[ "${1:-}" == "--uninstall" ]] || [[ "${2:-}" == "--uninstall" ]]; then
    do_uninstall
fi

# --------------- install ---------------
echo ""; echo "  ╔══════════════════════════╗"
echo "  ║      Penny Install       ║"
echo "  ╚══════════════════════════╝"; echo ""

PYTHON=$(command -v python3 || command -v python)
if [[ -z "$PYTHON" ]]; then
    err "Python 3 is required but not found."; exit 1
fi
PY_VER=$("$PYTHON" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
info "Python $PY_VER found at $PYTHON"

# Find or fetch source files
SOURCE_DIR=""
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
if [[ -d "$SCRIPT_DIR" ]] && [[ -f "$SCRIPT_DIR/cli.py" ]] && [[ -f "$SCRIPT_DIR/wrapper.sh" ]]; then
    SOURCE_DIR="$SCRIPT_DIR"
fi

if [[ -z "$SOURCE_DIR" ]]; then
    info "No local source found. Cloning from GitHub..."
    TMP_CLONE=$(mktemp -d)
    git clone --depth 1 https://github.com/your-username/penny.git "$TMP_CLONE" 2>/dev/null || {
        TMP_CLONE2=$(mktemp -d); echo "$PENNY_CLI" > "$TMP_CLONE2/need_source"
        err "Could not clone. Place install.sh alongside the Penny source files."
        rm -rf "$TMP_CLONE" "$TMP_CLONE2"; exit 1
    }
    SOURCE_DIR="$TMP_CLONE"
fi

# Copy files
mkdir -p "$PENNY_DIR"
cp "$SOURCE_DIR"/*.py "$SOURCE_DIR"/*.sh "$SOURCE_DIR"/pricing.json "$SOURCE_DIR"/com.penny.app.plist "$PENNY_DIR/" 2>/dev/null || true

chmod +x "$PENNY_DIR/wrapper.sh" 2>/dev/null || true
ok "Files installed to $PENNY_DIR"

# Create `penny` CLI wrapper
cat > "$PENNY_CLI" << 'PYWRAP'
#!/bin/bash
exec python3 "$HOME/.penny/cli.py" "$@"
PYWRAP
chmod +x "$PENNY_CLI"
ok "Created $PENNY_CLI"

# Create `claude` wrapper (prepends to PATH via shell config)
cp "$PENNY_DIR/wrapper.sh" "$PENNY_CLAUDE"
chmod +x "$PENNY_CLAUDE"
ok "Created $PENNY_CLAUDE"

# Add to PATH in shell config
if ! grep -qF "$PENNY_PATH_LINE" "$SHELL_CONFIG" 2>/dev/null; then
    printf "\n# Penny — smarter model switching for Claude Code\n%s\n" "$PENNY_PATH_LINE" >> "$SHELL_CONFIG"
    ok "Added Penny to PATH in $SHELL_CONFIG"
else
    ok "Penny already in PATH in $SHELL_CONFIG"
fi

# Install Python deps
info "Installing Python dependencies (rumps, rich)..."
"$PYTHON" -m pip install --quiet rumps rich 2>/dev/null && ok "Dependencies installed" || err "Could not install deps. Try: pip3 install rumps rich"

# Install launchd plist
if [[ -f "$PENNY_DIR/com.penny.app.plist" ]]; then
    mkdir -p "$HOME/Library/LaunchAgents"
    sed "s|___PENNY_DIR___|$HOME/.penny|g" "$PENNY_DIR/com.penny.app.plist" > "$PLIST_DST"
    launchctl load "$PLIST_DST" 2>/dev/null && ok "Launchd agent loaded — menu bar running" || info "Launchd created but not loaded (may need to log in)"
fi

# Install stop hook
mkdir -p "$HOME/.claude/stop-hooks"
ln -sf "$PENNY_DIR/hook.py" "$HOME/.claude/stop-hooks/penny-hook.py"
ok "Post-session hook installed"

# Try claude hook add if available
if command -v claude &>/dev/null; then
    claude hook add stop "python3 $PENNY_DIR/hook.py" 2>/dev/null || true
fi

# Clean up temp clone
if [[ -n "${TMP_CLONE:-}" ]] && [[ -d "$TMP_CLONE" ]]; then
    rm -rf "$TMP_CLONE"
fi

# Done
echo ""
echo "  ── Installation complete ──"
echo ""
echo "  What just happened:"
echo "    • Files → $PENNY_DIR"
echo "    • 'penny' and 'claude' commands → on PATH"
echo "      (prepend $PENNY_DIR in $SHELL_CONFIG)"
echo "    • Menu bar app → running (shows weekly spend)"
echo "    • Post-session hook → active (tracks + learns)"
echo ""
echo "  Next:"
echo "    1. source $SHELL_CONFIG"
echo "    2. claude \"fix typo in README\""
echo "    3. penny watch"
echo ""
echo "  Uninstall: bash $PENNY_DIR/install.sh --uninstall"
echo ""
