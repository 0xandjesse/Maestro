# OLI Fix Spec — May 23, 2026
> For: Proteus | From: Lex (via Jesse directive) | Priority: BLOCKING

## Background

Full clean-room OLI test ran against `~/maestro-sdk/runtime/install.sh`. 3 real failures block ship.

---

## Bug 1: python-dateutil import failure

**Symptom:** `pip install python-dateutil` succeeds but `import python_dateutil` fails.

**Root cause:** `install.sh` line 115 installs `python-dateutil` but the package name is `python-dateutil` (pip) while the import name is `dateutil`. Package installs correctly — the test just checked the wrong import name.

**However**, verify the package ACTUALLY installed — check pip output for errors.

**Fix:** `install.sh` line 115 is already correct (`pip install ... python-dateutil`). Add a post-install verification step after line 115:

```bash
$PYTHON -c "import dateutil; print('dateutil OK')" || echo "⚠ dateutil import FAILED"
```

---

## Bug 2: 7/8 patches drift against production Hermes checkout

**Symptom:** `patch --dry-run` fails for 7 patches against `~/.hermes/hermes-agent/`. Clean-room test (fresh clone) works fine — patches apply with only minor offsets.

**Root cause:** Production Hermes checkout at `~/.hermes/hermes-agent/` has diverged from the baseline the patches were created against. This is normal drift — the patches aren't broken, their target files have moved.

**Fix:** Three options, ranked:

**Option A (recommended):** Document that OLI requires a clean clone. `install.sh` already verifies Hermes exists but doesn't verify patch target freshness. Add a note in the README and installer output: "OLI works against a fresh `git clone` of Hermes. If you've modified your Hermes checkout, re-clone first."

**Option B:** Regenerate patches against the current production checkout. This fixes drift once but will drift again. Fragile.

**Option C:** Convert patches to `sed`-based surgical edits that are less position-dependent. Higher engineering effort.

**Action:** Implement Option A. Add to `install.sh` header:
```
# ⚠ This installer overlays patches against a fresh Hermes checkout.
# If patches fail with "patch may already be applied or rejected", re-clone:
#   cd ~/.hermes && mv hermes-agent hermes-agent.old
#   git clone https://github.com/NousResearch/hermes-agent.git --depth 1
```

---

## Bug 3: agent/audit_log.py patch has no target

**Symptom:** `install.sh` line 105 tries to patch `$H_HOME/agent/audit_log.py` but this file doesn't exist in new Hermes clones.

**Root cause:** `agent_audit_log.py.patch` creates a NEW file. `install.sh`'s `apply_patch()` function skips if target doesn't exist (line 54-56), so the patch is silently dropped.

**Fix:** Change `install.sh` `apply_patch()` to handle new-file creation. Replace lines 47-65 with:

```bash
apply_patch() {
    local patch_file="$1"
    local target="$2"
    if [ ! -f "$patch_file" ]; then
        echo "   ⚠ patch file not found: $patch_file"
        return
    fi
    if [ ! -f "$target" ]; then
        # NEW FILE: create empty target, then patch will populate it
        echo "   ⚠ target does not exist — creating: $target"
        mkdir -p "$(dirname "$target")"
        touch "$target"
    fi
    if patch --dry-run -p0 -i "$patch_file" "$target" > /dev/null 2>&1; then
        patch -p0 -i "$patch_file" "$target"
        echo "   ✓ applied patch to $target"
    else
        echo "   ⚠ patch for $target may already be applied or rejected"
    fi
}
```

This makes the new-file case explicit instead of silently skipping.

---

## Implementation

1. Patch `install.sh` with fixes for Bugs 1 and 3
2. Add the fresh-clone note for Bug 2
3. Re-run OLI test to verify all 3 fixes
4. Update checklist_tool.py line 18 if still broken (separate task — may be fixed already)

---

## Test Verification

After fixes, re-run: `bash /tmp/maestro-oli-test/run_all.sh`
Expected: python-dateutil ✓, audit_log ✓, patch dry-run passes or clear guidance given.

## Files Affected

- Edit: `~/maestro-sdk/runtime/install.sh` (lines 47-65, after 115)
