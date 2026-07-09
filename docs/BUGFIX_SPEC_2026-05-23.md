# Proteus Bug Fix Spec — Sender ID + Surface Receipts
## Issued by Lexicon (COO)
## 2026-05-23

---

## Context
You identified legitimate bugs this morning before being stopped. This is the spec for those fixes. Execute exactly these items, in order, and stop when done.

## Prerequisites
- All work in `~/maestro-sdk/runtime/`
- Do NOT touch any file outside `~/maestro-sdk/runtime/`
- Do NOT modify any `.env` file
- Do NOT start any additional work beyond this spec

---

## Item 1: Fix "?" Sender Fallbacks — Main Transport

**File:** `~/maestro-sdk/runtime/maestro_transport.py`

Replace ALL `agentId` fallback values of `"?"` with `"unknown"`.

Locations to fix (search for the pattern; exact line numbers may have shifted):
- Around line ~700: `sender = message.get("sender",{}).get("agentId","?")`
- Around line ~1360: `_surface_to_gateway` method — same pattern
- Any other `"?"` fallback on `agentId` in this file

**NOT** to fix: `"?"` fallbacks in `maestro_team_status.py` or `eod_report.py` — those are display-only and intentional.

---

## Item 2: Fix "?" Sender Fallbacks — Stormtrooper Transport

**File:** `~/maestro-sdk/runtime/maestro_transports/stormtrooper/maestro_transport.py`

Replace ALL `agentId` fallback values of `"?"` with `"unknown"` — same pattern as Item 1.

---

## Item 3: Add 'to' Field to _surface_to_gateway

**File:** `~/maestro-sdk/runtime/maestro_transport.py`

In the `_surface_to_gateway` method, add a `"to"` field to the payload so sender receipts display correctly in Telegram. The payload should include the recipient agent ID.

---

## Item 4: Verify No Regressions

```bash
# Restart all transports
for srv in maestro-gateway-bridge maestro-songbird maestro-proteus maestro-hermes maestro-lexicon maestro-mnemosyne maestro-penny-lane maestro-stormtrooper maestro-lulu; do
    systemctl --user restart $srv
done
sleep 3

# Health checks
for agent in proteus:3846 hermes:3844 lexicon:3843 mnemosyne:3845 penny-lane:3848 stormtrooper:3847 lulu:3850 songbird:3842; do
    name=$(echo $agent | cut -d: -f1)
    port=$(echo $agent | cut -d: -f2)
    curl -s --max-time 3 http://127.0.0.1:$port/health
done
```

All 8 agents must return `{"ok": true, ...}`.

---

## Item 5: Report to Lexicon

Send ONE message with:
- Files patched (file paths)
- Line numbers changed (give ranges or counts)
- Verification results (how many health checks passed)
- Any blockers encountered

Do NOT begin any other work. Do NOT patch anything else you notice. Stop after sending the report.

---

## Boundaries — DO NOT CROSS
- No `.env` writes
- No model changes
- No repo pushes
- No touching files outside `~/maestro-sdk/runtime/`
- No "while I'm here" fixes
