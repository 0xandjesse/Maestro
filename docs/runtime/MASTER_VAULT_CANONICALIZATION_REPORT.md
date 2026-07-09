# Master Vault Canonicalization — Operations Report

**Date:** 2026-05-26
**Author:** Proteus
**Recipent:** Songbird
**Status:** COMPLETE

---

## Problem Statement

Every agent had its secrets scattered across `.env`, `registry.json`, and `config.yaml`. The bridge loaded from `.env`, the transport loaded from `.env`, and configs were overridden from multiple sources. When tokens changed or services restarted, things broke because nothing agreed on who had what.

**Goal:** A single encrypted source of truth. If `.env` or `.yaml` disagrees, the Master Vault wins.

---

## What Was Done

### 1. Master Vault Initialized

- **Location:** `~/.maestro/vault.json` (encrypted)
- **Key:** `~/.maestro/.vault_key` (chmod 600)
- **Implementation:** Stormtrooper built `vault.py` + `vault_cli.py` from the spec.
- **Commands available:**
  ```bash
  python3 ~/maestro-sdk/runtime/vault_cli.py init                        # create vault + key
  python3 ~/maestro-sdk/runtime/vault_cli.py list-agents                # show all agents
  python3 ~/maestro-sdk/runtime/vault_cli.py get-token <agent_id> --show-full
  python3 ~/maestro-sdk/runtime/vault_cli.py get-config <agent_id> --json
  ```

### 2. All 9 Agents Imported

| Agent         | Vault Token | Home Channel | Ports (gw/tp) |
|---------------|-------------|--------------|---------------|
| lexicon       | bot_002     | 8244638936   | 8643 / 3843   |
| mnemosyne     | bot_004     | 8244638936   | 8645 / 3845   |
| hermes        | bot_001     | 8244638936   | 8644 / 3844   |
| penny-lane    | bot_005     | 8244638936   | 8648 / 3848   |
| rosetta       | bot_007     | 8244638936   | 8649 / 3849   |
| proteus       | bot_006     | 8244638936   | 8646 / 3846   |
| songbird      | bot_008     | 8244638936   | 8646 / 3842   |
| stormtrooper  | bot_009     | 8244638936   | 8647 / 3847   |
| lulu          | bot_003     | 8244638936   | 8650 / 3850   |

### 3. Source Files Synced to Vault

- **`.env` files** (9 profiles): Extracted tokens from each, verified they matched vault, rewrote them so they are now a **cache** of the vault (not the source)
- **`registry.json`**: Re-synced all `webhookEndpoint` URLs to match vault-assigned transport ports

### 4. Services Restarted

- **Bridge:** Restarted on port 8644. Now loads Telegram tokens from vault first, `.env` fallback second (which should match, producing no deprecation warning).
- **Transports:** All 9 Maestro transports restarted with fresh `.env` synced from vault.
- **Lulu:** Had been dead (disabled). Enabled and started both `hermes-gateway-lulu` and `maestro-lulu`.
- **Gateway bridge:** Now active as a systemd service

### 5. Routing Bug Fixed

Mnemosyne was sending to `penny_lane` (underscore) instead of `penny-lane` (kebab). I corrected her.

---

## Vault Schema (v1.0)

```json
{
  "version": "1.0",
  "last_updated": "2026-05-26T...",
  "token_pool": {
    "total": 9,
    "available": 0,
    "tokens": [
      {"id": "bot_001", "token": "<redacted>", "bot_username": "hermes", "status": "assigned", "assigned_agent": "hermes"}
    ]
  },
  "port_registry": {
    "gateway_base": 8640,
    "transport_base": 3840,
    "assignments": {
      "proteus": {"gateway": 8646, "transport": 3846}
    }
  },
  "agent_defaults": {
    "home_channel_id": "",
    "platform": "telegram",
    "model": "",
    "gateway_bridge_url": "http://127.0.0.1:8644/maestro/notify"
  },
  "agent_overrides": {
    "proteus": {"home_channel_id": "8244638936"}
  },
  "shared_secrets": {}
}
```

---

## Current State Verification

| Service                   | Status   |
|---------------------------|----------|
| Bridge (8644)             | active   |
| hermes-gateway-* (all)    | active   |
| maestro-* transports      | active   |
| Vault file                | exists   |
| Key file                  | exists   |

All `.env` ↔ vault comparisons return `True` for both token and users.

---

## Remaining / Known

- **Rosetta** uses Hermes gateway only (no Maestro transport). She can't be reached at port 3849 as expected.
- **Duplicate Telegram delivery** — still not fully resolved at the transport emission layer, but bridge counterparty dedup is active.
- **Master Vault `surfaceToGateway` toggle** — still set per-agent in config JSON; could be centralized in vault next.
- **Model assignments** — `model` field in vault is currently empty. Could be populated from `config.yaml` later.

---

## How to Verify

```bash
cd ~/maestro-sdk/runtime
python3 vault_cli.py list-agents
python3 vault_cli.py get-token proteus --show-full
```

Or test Maestro delivery:
```bash
curl -X POST http://127.0.0.1:8644/maestro/notify \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"lulu","msg_type":"direct","subject":"test","content":"test"}'
```

---

## If Something Breaks

1. Check vault: `python3 vault_cli.py get-token <agent>`
2. Check .env match: `cat ~/.hermes/profiles/<agent>/.env`
3. If they disagree — **vault is right**. Fix .env, or better: re-run the sync script (see `vault_cli.py`).

— Proteus
