#!/usr/bin/env bash
set -e

# Maestro Transport Installer
# Prerequisites: Hermes agent installed at ~/.hermes/hermes-agent/
# This applies overlay patches so Maestro works with Hermes
#
# ⚠ This installer overlays patches against a fresh Hermes checkout.
# If patches fail with "patch may already be applied or rejected", re-clone:
#   cd ~/.hermes && mv hermes-agent hermes-agent.old
#   git clone https://github.com/NousResearch/hermes-agent.git --depth 1

MAESTRO_DIR="$(cd "$(dirname "$0")" && pwd)"
H_HOME="${HERMES_HOME:-$HOME/.hermes/hermes-agent}"
VENV="$H_HOME/venv"

echo "═══════════════════════════════════════════════════════"
echo "  Maestro Transport Installer"
echo "═══════════════════════════════════════════════════════"
echo ""

# Verify Hermes exists
if [ ! -d "$H_HOME/gateway" ]; then
    echo "❌ Hermes agent not found at $H_HOME"
    echo "   Clone it first:"
    echo "     git clone https://github.com/NousResearch/hermes-agent.git ~/.hermes/hermes-agent"
    echo "     cd ~/.hermes/hermes-agent && python3 -m venv venv && source venv/bin/activate && pip install -e ."
    exit 1
fi
echo "✓ Hermes found at $H_HOME"

# Detect venv
if [ -d "$H_HOME/.venv" ]; then VENV="$H_HOME/.venv"; fi
if [ -d "$H_HOME/venv" ]; then VENV="$H_HOME/venv"; fi
if [ -f "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
    echo "✓ Found venv: $VENV"
else
    PYTHON="python3"
    echo "⚠ No venv found — using system Python"
fi

# Determine Python site-packages for symlinks or install
SITE_PKGS="$($PYTHON -c 'import site; print(site.getsitepackages()[0])' 2>/dev/null || echo "")"
if [ -z "$SITE_PKGS" ]; then
    echo "❌ Cannot detect Python site-packages"
    exit 1
fi
echo "✓ Python site-packages: $SITE_PKGS"

# ── apply_patch: auto-detects git a/b (-p1) vs old-style (-p0) ────
apply_patch() {
    local patch_file="$1"
    local target="$2"
    if [ ! -f "$patch_file" ]; then
        echo "   ⚠ patch file not found: $patch_file"
        return
    fi
    if [ ! -f "$target" ]; then
        echo "   ⚠ target does not exist — creating: $target"
        mkdir -p "$(dirname "$target")"
        touch "$target"
    fi
    # Detect patch format
    local strip_opt="-p0"
    if grep -q "^--- a/" "$patch_file" 2>/dev/null || grep -q "^+++ b/" "$patch_file" 2>/dev/null; then
        strip_opt="-p1"
    fi
    if patch --dry-run $strip_opt -i "$patch_file" > /dev/null 2>&1; then
        patch $strip_opt -i "$patch_file"
        echo "   ✓ applied patch to $target ($strip_opt)"
    else
        echo "   ⚠ patch for $target may already be applied or rejected ($strip_opt)"
    fi
}

# ── 1. Copy Maestro tools into Hermes ────
echo ""
echo "[1/4] Copying Maestro tools into Hermes..."
for f in send_message_tool.py maestro_memory.py bb_tool.py checklist_tool.py memory_tool.py; do
    src="$MAESTRO_DIR/tools/$f"
    dst="$H_HOME/tools/$f"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "   ✓ tools/$f"
    else
        echo "   ⚠ tools/$f not found in Maestro repo"
    fi
done

# ── 2. Install maestro package as editable ──────────
echo ""
echo "[2/4] Installing maestro package (editable)..."
if [ -d "$MAESTRO_DIR/maestro" ] && [ -f "$MAESTRO_DIR/maestro/__init__.py" ]; then
    PYVER="$($PYTHON -c 'import sys; print("python%d.%d" % sys.version_info[:2])')"
    MAESTRO_DST="$SITE_PKGS/maestro-editable"
    mkdir -p "$MAESTRO_DST"
    cp "$MAESTRO_DIR"/maestro/*.py "$MAESTRO_DST/" 2>/dev/null
    ln -sf "$MAESTRO_DST" "$SITE_PKGS/maestro" 2>/dev/null || true
    echo "   ✓ maestro package installed at $MAESTRO_DST"
else
    echo "   ⚠ maestro/__init__.py not found — skipping"
fi

# ── 3. Apply overlay patches to Hermes ──────────────
echo ""
echo "[3/4] Applying Hermes overlay patches..."
if [ -d "$MAESTRO_DIR/patches" ]; then
    apply_patch "$MAESTRO_DIR/patches/gateway_run.py.patch"         "$H_HOME/gateway/run.py"
    apply_patch "$MAESTRO_DIR/patches/platforms_telegram.py.patch"  "$H_HOME/gateway/platforms/telegram.py"
    apply_patch "$MAESTRO_DIR/patches/hermes_cli_commands.py.patch" "$H_HOME/hermes_cli/commands.py"
    apply_patch "$MAESTRO_DIR/patches/hermes_cli_gateway.py.patch" "$H_HOME/hermes_cli/gateway.py"
    apply_patch "$MAESTRO_DIR/patches/agent_audit_log.py.patch"    "$H_HOME/agent/audit_log.py"
    apply_patch "$MAESTRO_DIR/patches/toolsets.py.patch"           "$H_HOME/toolsets.py"
else
    echo "   ⚠ patches/ directory not found"
fi

# ── 4. Install dependencies ─────────────────────────
echo ""
echo "[4/4] Installing Maestro dependencies..."
$PYTHON -m pip install aiohttp fastapi uvicorn websockets python-dateutil 2>&1 | tail -3
$PYTHON -c "import dateutil; print('dateutil OK')" || echo "⚠ dateutil import FAILED"

# ── 5. Create convenience symlinks ──────────────────
echo ""
echo "[Symlinks] Creating handy shortcuts..."
mkdir -p ~/.local/bin 2>/dev/null || true

if [ -f "$MAESTRO_DIR/maestro_gateway_bridge.py" ]; then
    cat > ~/.local/bin/maestro-bridge <<EOF
#!/usr/bin/env bash
# Start Maestro Gateway Bridge
exec $PYTHON $MAESTRO_DIR/maestro_gateway_bridge.py "\$@"
EOF
    chmod +x ~/.local/bin/maestro-bridge
    echo "   ✓ ~/.local/bin/maestro-bridge"
fi

cat > ~/.local/bin/maestro-visibility <<'EOF'
#!/usr/bin/env bash
# maestro-visibility — toggle Maestro notification mode
MODE="${1:-short}"
PROFILE="${2:-default}"
VIS_FILE="$HOME/.hermes/maestro_visibility.json"
mkdir -p "$(dirname $VIS_FILE)"
if python3 -c "import json; open('$VIS_FILE','w').write(json.dumps({'$PROFILE':{'display_mode':'$MODE','in':True,'out':True}},indent=2))" 2>/dev/null; then
    echo "Maestro visibility set to: $MODE (profile: $PROFILE)"
else
    echo "⚠ Failed to write visibility config"
fi
EOF
chmod +x ~/.local/bin/maestro-visibility
echo "   ✓ ~/.local/bin/maestro-visibility"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Maestro installation complete"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "Quick commands:"
echo "  maestro-bridge            # start bridge daemon"
echo "  maestro-visibility long   # set your profile to long mode"
echo "  maestro-visibility short  # set your profile to short mode"
echo "  maestro-visibility off    # disable Maestro notifications"
echo ""
echo "To start everything:"
echo "  cd $H_HOME && source venv/bin/activate"
echo "  maestro-bridge --port 8644 &"
echo "  python -m hermes_cli.main --profile proteus gateway run"
