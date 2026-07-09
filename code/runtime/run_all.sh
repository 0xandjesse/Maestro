#!/usr/bin/env bash
# run_all.sh — Maestro OLI clean-room test harness (v3)
# Fixes from v2:
#   - Phase 6 uses -p1 for git a/b patches, skips transport-shim (not a Hermes patch)
#   - memory_tool.py verified via direct copy (patch removed)
#   - Handler count grep fixed (no multi-line newline via -h with -c)
#   - Gateway smoke profile changed from 'test' to 'testoli' (not reserved)
#   - install.sh auto-detects patch level

set -e

PASSES=0
FAILURES=0
TEST_HOME="/tmp/maestro-oli-test"
HERMES_HOME="$TEST_HOME/hermes-agent"
RUNTIME_DIR="$HOME/maestro-sdk/runtime"
TIMESTAMP=$(date -Iseconds)

echo "============================================="
echo "  Maestro OLI Clean-Room Test v3"
echo "  $TIMESTAMP"
echo "============================================="

# ── Phase 1: Clean room setup ──────────────────────
echo ""
echo "[1/6] Setting up test environment..."
rm -rf "$HERMES_HOME"
mkdir -p "$TEST_HOME"
cd "$TEST_HOME"

git clone https://github.com/NousResearch/hermes-agent.git --depth 1 "$HERMES_HOME" > /dev/null 2>&1
cd "$HERMES_HOME"

python3 -m venv venv > /dev/null 2>&1
source venv/bin/activate
pip install -e . > /dev/null 2>&1

mkdir -p "$TEST_HOME/snapshots"
cp -r tools "$TEST_HOME/snapshots/tools-before"
cp -r gateway "$TEST_HOME/snapshots/gateway-before"
cp -r hermes_cli "$TEST_HOME/snapshots/hermes_cli-before"
cp -r agent "$TEST_HOME/snapshots/agent-before"
cp toolsets.py "$TEST_HOME/snapshots/toolsets.py.before"
echo "✓ Test environment ready"
PASSES=$((PASSES + 1))

# ── Phase 2: Run install.sh ─────────────────────────
echo ""
echo "[2/6] Running install.sh..."
bash "$RUNTIME_DIR/install.sh" 2>&1 | tee "$TEST_HOME/install.log"
INSTALL_EXIT="${PIPESTATUS[0]}"
if [ "$INSTALL_EXIT" -eq 0 ]; then
    echo "✓ install.sh exit 0"
    PASSES=$((PASSES + 1))
else
    echo "✗ install.sh exit $INSTALL_EXIT"
    FAILURES=$((FAILURES + 1))
fi

# ── Phase 3: Tool files, patches, package, deps ─────
echo ""
echo "[3/6] Verifying tool files, patches, package, deps..."

source "$HERMES_HOME/venv/bin/activate"

# --- 3a: Tool files identical ---
for f in send_message_tool.py maestro_memory.py bb_tool.py checklist_tool.py memory_tool.py; do
    if diff -q "$RUNTIME_DIR/tools/$f" "$HERMES_HOME/tools/$f" > /dev/null 2>&1; then
        echo "  ✓ tools/$f"
        PASSES=$((PASSES + 1))
    else
        echo "  ✗ tools/$f DIFFERS"
        FAILURES=$((FAILURES + 1))
    fi
done

# --- 3b: Slash commands registered in commands.py ---
for cmd in maestro bb bball log memory memoryall cl clshow; do
    if grep -q "\"$cmd\"" "$HERMES_HOME/hermes_cli/commands.py" 2>/dev/null; then
        echo "  ✓ /$cmd registered"
        PASSES=$((PASSES + 1))
    else
        echo "  ✗ /$cmd MISSING"
        FAILURES=$((FAILURES + 1))
    fi
done

# --- 3c: Patch markers in patched files ---
if grep -q "_MAESTRO_HOME\|_load_maestro_visibility" "$HERMES_HOME/gateway/run.py" 2>/dev/null; then
    echo "  ✓ gateway/run.py Maestro additions"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ gateway/run.py MISSING Maestro additions"
    FAILURES=$((FAILURES + 1))
fi

if grep -q "explicit" "$HERMES_HOME/gateway/platforms/telegram.py" 2>/dev/null; then
    echo "  ✓ telegram.py slash bypass"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ telegram.py MISSING slash bypass"
    FAILURES=$((FAILURES + 1))
fi

if grep -q "hermes.*reserved" "$HERMES_HOME/hermes_cli/gateway.py" 2>/dev/null; then
    echo "  ✓ gateway.py hermes profile bypass"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ gateway.py MISSING hermes bypass"
    FAILURES=$((FAILURES + 1))
fi

if grep -q "agent_memory\|checklist_create" "$HERMES_HOME/toolsets.py" 2>/dev/null; then
    echo "  ✓ toolsets.py Maestro toolsets"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ toolsets.py MISSING Maestro toolsets"
    FAILURES=$((FAILURES + 1))
fi

if [ -f "$HERMES_HOME/agent/audit_log.py" ]; then
    echo "  ✓ agent/audit_log.py exists"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ agent/audit_log.py MISSING"
    FAILURES=$((FAILURES + 1))
fi

if grep -qi "Persistent agent memory\|cross-session key/value" "$HERMES_HOME/tools/memory_tool.py" 2>/dev/null; then
    echo "  ✓ memory_tool.py Maestro version"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ memory_tool.py NOT replaced"
    FAILURES=$((FAILURES + 1))
fi

# --- 3d: No duplicate handler definitions ---
for handler in _handle_bb_command _handle_bball_command _handle_log_command _handle_memory_command _handle_memoryall_command; do
    count=$(grep -c "def $handler" "$HERMES_HOME/gateway/run.py" 2>/dev/null | tail -1)
    if [ "$count" -eq 1 ]; then
        echo "  ✓ $handler (1 def)"
        PASSES=$((PASSES + 1))
    else
        echo "  ✗ $handler ($count defs)"
        FAILURES=$((FAILURES + 1))
    fi
done

# --- 3e: No conflict markers ---
CONFLICTS=$(grep -rl '<<<<<<<\|>>>>>>>' "$HERMES_HOME"/{gateway,hermes_cli,tools,agent}/*.py 2>/dev/null || true)
if [ -n "$CONFLICTS" ]; then
    echo "  ✗ CONFLICT MARKERS FOUND"
    echo "$CONFLICTS" | while read ln; do echo "    $ln"; done
    FAILURES=$((FAILURES + 1))
else
    echo "  ✓ No conflict markers"
    PASSES=$((PASSES + 1))
fi

# --- 3f: maestro package importable ---
if python3 -c "import maestro" 2>/dev/null; then
    echo "  ✓ maestro package"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ maestro package MISSING"
    FAILURES=$((FAILURES + 1))
fi

# --- 3g: Dependencies ---
for pkg in aiohttp fastapi uvicorn websockets; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "  ✓ $pkg"
        PASSES=$((PASSES + 1))
    else
        echo "  ✗ $pkg MISSING"
        FAILURES=$((FAILURES + 1))
    fi
done

if python3 -c "import dateutil" 2>/dev/null; then
    echo "  ✓ dateutil"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ dateutil MISSING"
    FAILURES=$((FAILURES + 1))
fi

# ── Phase 4: Gateway smoke test ─────────────────────
echo ""
echo "[4/6] Gateway smoke test..."

mkdir -p "$TEST_HOME/gw-home/.hermes/profiles/testoli"
cat > "$TEST_HOME/gw-home/.hermes/profiles/testoli/config.yaml" <<'YEOF'
model:
  default: test-model
  provider: custom
  base_url: http://localhost:11434/v1
  api_key: none
providers: {}
toolsets: []
agent:
  max_turns: 10
gateway:
  api_server:
    port: 19999
telegram:
  token: ''
platforms:
  api_server:
    extra:
      port: 19999
  telegram:
    token: ''
YEOF

echo -e "HERMES_MAX_ITERATIONS=10\nGATEWAY_ALLOW_ALL_USERS=true" > "$TEST_HOME/gw-home/.hermes/profiles/testoli/.env"

export HERMES_HOME="$TEST_HOME/gw-home/.hermes"
timeout 15 python3 -m hermes_cli.main --profile testoli gateway run > "$TEST_HOME/gateway.log" 2>&1 || true

if grep -Eil 'Traceback|traceback' "$TEST_HOME/gateway.log" 2>/dev/null | grep -qv "DeprecationWarning\|warn\|hermes.*reserved"; then
    echo "  ✗ Gateway traceback found"
    FAILURES=$((FAILURES + 1))
else
    echo "  ✓ No gateway traceback"
    PASSES=$((PASSES + 1))
fi

# Slash commands in gateway routing (canonical == pattern)
for cmd in maestro bb bball log memory memoryall cl clshow; do
    if grep -q "canonical.*==.*$cmd" "$TEST_HOME/hermes-agent/gateway/run.py" 2>/dev/null; then
        echo "  ✓ /$cmd routed"
        PASSES=$((PASSES + 1))
    else
        echo "  ✗ /$cmd NOT routed"
        FAILURES=$((FAILURES + 1))
    fi
done

# ── Phase 5: Transport + loop guards + checklist ────
echo ""
echo "[5/6] Transport, loop guards, convenience scripts, checklist..."

mkdir -p "$TEST_HOME/.maestro/configs"
cat > "$TEST_HOME/.maestro/configs/test-transport.json" <<'EOF'
{"agent_id":"test-agent","port":19998,"hermes_api_url":"http://127.0.0.1:19999","seed_peers":{}}
EOF

source "$TEST_HOME/hermes-agent/venv/bin/activate"
python3 "$RUNTIME_DIR/maestro_transport.py" \
    --config "$TEST_HOME/.maestro/configs/test-transport.json" \
    > "$TEST_HOME/transport.log" 2>&1 &
TRANSPORT_PID=$!
sleep 3

if curl -s http://127.0.0.1:19998/health 2>/dev/null | grep -q '"ok"'; then
    echo "  ✓ Transport health OK"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ Transport health FAIL"
    FAILURES=$((FAILURES + 1))
fi

kill $TRANSPORT_PID 2>/dev/null || true
wait $TRANSPORT_PID 2>/dev/null || true

# Loop guard features
for feature in "_cooldown_until" "_notify_loop_detected" "inReplyTo" "rate_limit" "_answered_ids"; do
    if grep -q "$feature" "$RUNTIME_DIR/maestro_transport.py" 2>/dev/null; then
        echo "  ✓ loop guard: $feature"
        PASSES=$((PASSES + 1))
    else
        echo "  ✗ loop guard: $feature MISSING"
        FAILURES=$((FAILURES + 1))
    fi
done

# Convenience scripts
if bash -n ~/.local/bin/maestro-bridge 2>/dev/null; then
    echo "  ✓ maestro-bridge syntax OK"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ maestro-bridge syntax FAIL"
    FAILURES=$((FAILURES + 1))
fi

if grep -q "maestro_gateway_bridge.py" ~/.local/bin/maestro-bridge 2>/dev/null; then
    echo "  ✓ maestro-bridge path OK"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ maestro-bridge path UNKNOWN"
    FAILURES=$((FAILURES + 1))
fi

export PATH="$HOME/.local/bin:$PATH"
rm -f "$HOME/.hermes/maestro_visibility.json"
maestro-visibility short testoli 2>/dev/null || true
VIS_FILE="$HOME/.hermes/maestro_visibility.json"
if [ -f "$VIS_FILE" ]; then
    echo "  ✓ maestro-visibility wrote config"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ maestro-visibility no output"
    FAILURES=$((FAILURES + 1))
fi

# Checklist backend
source "$TEST_HOME/hermes-agent/venv/bin/activate"
if python3 -c "
import sys
sys.path.insert(0, '$RUNTIME_DIR')
from checklist_manager import create_checklist, read_checklist, update_item, list_checklists, cancel_checklist
cl_id = create_checklist('songbird', 'testoli', 'Test Checklist', ['A', 'B'])
cl = read_checklist(cl_id)
assert cl['title'] == 'Test Checklist'
assert len(cl['items']) == 2
assert cl['items'][0]['status'] == 'pending'
update_item(cl_id, 'A', status='done', summary='ok')
cl = read_checklist(cl_id)
assert cl['items'][0]['status'] == 'done'
checklists = list_checklists(agent_id='testoli')
assert len(checklists) >= 1
cancel_checklist(cl_id)
print('Checklist backend: ALL OK')
" 2>&1; then
    echo "  ✓ Checklist backend OK"
    PASSES=$((PASSES + 1))
else
    echo "  ✗ Checklist backend FAIL"
    FAILURES=$((FAILURES + 1))
fi

# ── Phase 6: Patch dry-run on production Hermes ─────
echo ""
echo "[6/6] Patch dry-run on production Hermes..."

PROD_HERMES="$HOME/.hermes/hermes-agent"
PATCH_DIR="$RUNTIME_DIR/patches"

if [ -d "$PROD_HERMES" ]; then
    cd "$PROD_HERMES"
    for patch in "$PATCH_DIR"/*.patch; do
        base=$(basename "$patch")
        # Skip transport-shim (not a Hermes file patch)
        if [[ "$base" == *transport-shim* ]]; then
            echo "  — $base (skip — not a Hermes patch)"
            continue
        fi
        # audit_log is new file — informational only
        if [[ "$base" == *audit_log* ]]; then
            if [ ! -f agent/audit_log.py ]; then
                echo "  ✓ $base (new file, no conflict)"
                PASSES=$((PASSES + 1))
            else
                echo "  ⚠ $base (target already exists in production)"
            fi
            continue
        fi
        # Determine patch format
        if grep -q '^--- a/' "$patch" || grep -q '^+++ b/' "$patch"; then
            strip_opt="-p1"
        else
            strip_opt="-p0"
        fi
        if grep -q "_MAESTRO_HOME\|_load_maestro_visibility\|explicit.*slash\|checklist_create\|agent_memory" "$PROD_HERMES/gateway/run.py" "$PROD_HERMES/hermes_cli/commands.py" "$PROD_HERMES/toolsets.py" 2>/dev/null; then
            echo "  ✓ Maestro additions already present in production — skipping dry-run"
            PASSES=$((PASSES + 1))
            continue
        fi
        if patch --dry-run $strip_opt -i "$patch" > /dev/null 2>&1; then
            echo "  ✓ $base applies cleanly ($strip_opt)"
            PASSES=$((PASSES + 1))
        else
            echo "  ✗ $base WOULD FAIL — drift detected ($strip_opt)"
            FAILURES=$((FAILURES + 1))
        fi
    done
else
    echo "  ⚠ Production Hermes not found at $PROD_HERMES — skipping"
fi

# ── Summary ──────────────────────────────────────────
echo ""
echo "============================================="
echo "  Result: $PASSES passes, $FAILURES failures"
if [ "$FAILURES" -eq 0 ]; then
    echo "  ALL CHECKS PASSED"
else
    echo "  $FAILURES check(s) FAILED — review above"
fi
echo "  Timestamp: $TIMESTAMP"
echo "============================================="

cat > "$TEST_HOME/results.json" <<EOF
{"passes": $PASSES, "failures": $FAILURES, "timestamp": "$TIMESTAMP"}
EOF

exit $FAILURES
