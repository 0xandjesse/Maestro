# Checklist Wiring + Duplicate Handler Cleanup — Specification

**Status:** Ready for implementation  
**Target:** `patches/gateway_run.py.patch` + `tools/checklist_tool.py`  
**Implementer:** Proteus

---

## Overview

Two fixes in one spec:
1. Wire `/cl` and `/clshow` gateway handlers to `checklist_manager.py` (they're stubs)
2. Remove 5 duplicate handler definitions in the gateway patch (bulldozer artifact)

---

## 1. Fix `/cl` — List active Checklists

**Current stub (gateway_run.py.patch, offset ~23349):**
```python
async def _handle_cl_command(self, event) -> str:
    """Handle /cl [agent] -- list active Checklists for an agent."""
    import json, pathlib
    CL_ROOT = _MAESTRO_HOME / "checklists"
    args = event.get_command_args().strip().split()
    agent_id = args[0] if args else None
    if not agent_id:
        return "Usage: /cl <agent_id>  (e.g. /cl proteus)"
    # ... NOTHING HERE — returns None, user sees nothing
```

**Replace with:**
```python
async def _handle_cl_command(self, event) -> str:
    """Handle /cl [agent] -- list active Checklists for an agent."""
    import json, pathlib, datetime
    args = event.get_command_args().strip().split()
    agent_id = args[0] if args else None
    if not agent_id:
        return "Usage: /cl <agent_id>  (e.g. /cl proteus)"
    
    CL_ROOT = _MAESTRO_HOME / "checklists"
    if not CL_ROOT.exists():
        return f"No checklists directory found."
    
    active = []
    for p in sorted(CL_ROOT.glob("*.json")):
        try:
            cl = json.loads(p.read_text())
            if cl.get("created_by") == agent_id or cl.get("assigned_to") == agent_id:
                active.append(cl)
        except Exception:
            continue
    
    if not active:
        return f"No active checklists for {agent_id}."
    
    lines = [f"Checklists for {agent_id}:", "─" * 30]
    for cl in active:
        cid = cl.get("id", "?")
        title = cl.get("title", "Untitled")
        status = cl.get("status", "?")
        items = cl.get("items", [])
        done = sum(1 for i in items if i.get("status") == "done")
        total = len(items)
        lines.append(f"{cid}  [{status}]  {title}  ({done}/{total} done)")
    
    return "\n".join(lines)
```

---

## 2. Fix `/clshow` — Show a Checklist with item statuses

**Current stub (gateway_run.py.patch, offset ~24706):**
Same pattern — parses args and returns nothing.

**Replace with:**
```python
async def _handle_clshow_command(self, event) -> str:
    """Handle /clshow <checklist_id> -- show a Checklist with item statuses."""
    import json, pathlib, datetime
    args = event.get_command_args().strip().split()
    checklist_id = args[0] if args else None
    if not checklist_id:
        return "Usage: /clshow <checklist_id>  (e.g. /clshow CL-proteus-a1b2c3d4)"
    
    CL_ROOT = _MAESTRO_HOME / "checklists"
    p = CL_ROOT / f"{checklist_id.strip('/')}.json"
    if not p.exists():
        return f"Checklist {checklist_id} not found."
    
    try:
        cl = json.loads(p.read_text())
    except Exception as e:
        return f"Error reading checklist: {e}"
    
    title = cl.get("title", "Untitled")
    status = cl.get("status", "?")
    created_by = cl.get("created_by", "?")
    assigned_to = cl.get("assigned_to", "?")
    items = cl.get("items", [])
    
    lines = [
        f"{checklist_id} — {title}",
        f"Status: {status}  |  Created by: {created_by}  |  Assigned to: {assigned_to}",
        "─" * 30,
    ]
    
    for item in items:
        iid = item.get("id", "?")
        desc = item.get("description", "?")
        istatus = item.get("status", "pending")
        emoji = {"done": "✅", "in_progress": "🔄", "blocked": "🚫", "pending": "⬜"}.get(istatus, "⬜")
        lines.append(f"{emoji} [{iid}] {desc}  — {istatus}")
    
    return "\n".join(lines)
```

---

## 3. Fix `tools/checklist_tool.py` dead path

**File:** `runtime/tools/checklist_tool.py`  
**Problem:** Line 18 hardcodes `MT_DIR = "/home/andjesse/maestro-transport"` — dead directory.

**Fix:** Replace with dynamic resolution based on the tool's own location:

```python
# Old (broken):
MT_DIR = "/home/andjesse/maestro-transport"
if MT_DIR not in sys.path:
    sys.path.insert(0, MT_DIR)

# New (self-resolving):
import os
MT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # runtime/ dir
if MT_DIR not in sys.path:
    sys.path.insert(0, MT_DIR)
```

This resolves: `tools/checklist_tool.py` → parent `tools/` → parent `runtime/` → that's where `checklist_manager.py` lives.

---

## 4. Remove duplicate handlers (Gap 4)

**Problem:** `gateway_run.py.patch` defines these handlers TWICE:
- `_handle_bb_command` at offsets ~6244 and ~16977
- `_handle_bball_command` at offsets ~7866 and ~18217  
- `_handle_log_command` at offsets ~9493 and ~19621
- `_handle_memory_command` at offsets ~11029 and ~20782
- `_handle_memoryall_command` at offsets ~12647 and ~22201

Python uses the **second** definition. The first set is dead code and confuses anyone reading the file.

### Action: Remove the FIRST set (lower offsets)

Between the two sets, the patch adds the first batch around offset 6244-16360 and the second batch around offset 16977-22900. The first batch uses `event.get_command_args()`, the second uses `event.text.split()`.

**Keep the second set** (uses `event.text` — standard for gateway handler parsing).

### How to remove:

Find the patch hunks that add the first batch and delete them. Specifically, between the line:
```
+    # Agent Memory System slash commands
```
...and the `_handle_maestroin_command` definition, the first set of BB/Log/Memory handlers are added. Remove those hunks, keeping only the second set (which appears later in the patch after the `_handle_maestrooff_command` definition).

The second set starts with a second:
```
+    # ── Agent Memory System slash commands ──────────────────────────────
```

**Verification:** After removal, `grep -c "async def _handle_bb_command" gateway_run.py.patch` should return `1`.

---

## 5. Hard Boundaries

1. **Do not modify any agent config or .env files**
2. **Do not touch GitHub**
3. **Test `/cl proteus` and `/clshow <id>` from a gateway-connected agent**
4. **Verify checklist_tool.py imports work after path fix**
5. **Report results and STOP**

---

## 6. Verification Checklist

- [ ] `/cl proteus` returns active checklists with ID, status, title, progress
- [ ] `/cl none` returns "No active checklists" (not a crash)
- [ ] `/clshow CL-xxx` shows checklist with item statuses and emojis
- [ ] `/clshow bad-id` returns "not found" (not a crash)
- [ ] `checklist_tool.py` imports `checklist_manager` successfully
- [ ] `grep -c "async def _handle_bb_command" gateway_run.py.patch` returns `1`
- [ ] All 5 handlers defined exactly once in the patch file
- [ ] `/bb`, `/bball`, `/log`, `/memory`, `/memoryall` still work after cleanup
