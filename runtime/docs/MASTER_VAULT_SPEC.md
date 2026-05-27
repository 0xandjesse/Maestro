# Master Vault Technical Specification

**Author:** Lexicon (concept), Proteus (spec)  
**Version:** 1.0  
**Status:** Ready for implementation

---

## 1. Problem Statement

Bot tokens scattered across 9 `.env` files. Gateway ports assigned ad-hoc. Transport ports edited by hand in `registry.json`. Model assignments in per-agent `config.yaml`. Every new agent requires Jesse to do a BotFather dance. No single source of truth exists.

## 2. Design Principles

1. **Single source of truth.** One file answers all questions about bot tokens, ports, models, and channels.
2. **Encrypted at rest.** Tokens are secrets — the vault never sits on disk in plaintext.
3. **Backward compatible.** Existing `.env` and `config.yaml` files continue to work but are **deprecated**. Log a single warning on read.
4. **Read-only for agents.** Agents query the vault. They never write to it.
5. **Pre-provisioned tokens.** Jesse creates 5–10 bots once, dumps tokens into the vault pool. Future spin-ups draw from the pool without touching BotFather.

## 3. File Location & Encryption

- **Path:** `~/.maestro/vault.json`
- **Encryption:** AES-256-GCM with a 32-byte key derived from a passphrase stored at `~/.maestro/.vault_key` (permissions `600`).
- **Plaintext during read:** The vault module decrypts into memory only. Never writes plaintext temp files.
- **Backup:** On every write, a timestamped copy is saved to `~/.maestro/vault.json.bak-{timestamp}` (also encrypted).

## 4. Schema (v1)

```json
{
  "version": "1.0",
  "last_updated": "2026-05-26T16:30:00Z",
  "master_passphrase_hash": "<argon2id hash>",
  
  "token_pool": {
    "total": 10,
    "available": 8,
    "tokens": [
      {
        "id": "bot_001",
        "token": "<encrypted_bot_token>",
        "bot_username": "agent1_bot",
        "status": "available",
        "assigned_agent": null,
        "created": "2026-05-26T16:00:00Z"
      },
      {
        "id": "bot_002",
        "token": "<encrypted_bot_token>",
        "bot_username": "lexicon_bot",
        "status": "assigned",
        "assigned_agent": "lexicon",
        "created": "2026-05-26T16:00:00Z"
      }
    ]
  },

  "port_registry": {
    "gateway_base": 8640,
    "transport_base": 3840,
    "assignments": {
      "lexicon":   { "gateway": 8643, "transport": 3843 },
      "proteus":   { "gateway": 8646, "transport": 3846 },
      "songbird":  { "gateway": 8645, "transport": 3845 },
      "hermes":    { "gateway": 8647, "transport": 3847 },
      "mnemosyne": { "gateway": 8648, "transport": 3848 }
    }
  },

  "agent_defaults": {
    "home_channel_id": "8244638936",
    "platform": "telegram",
    "model": "qwen3:30b-a3b",
    "gateway_bridge_url": "http://127.0.0.1:8644/maestro/notify"
  },

  "agent_overrides": {
    "songbird": {
      "model": "claude-opus-4"
    },
    "lexicon": {
      "model": "llama3-70b"
    }
  },

  "shared_secrets": {
    "maestro_api_key": "<encrypted>"
  }
}
```

### Field semantics

- **`token_pool.tokens[].status`**: `available` | `assigned` | `revoked`
- **`token_pool.tokens[].assigned_agent`**: agent ID string or `null`
- **`port_registry.assignments`**: maps agent_id → `{gateway, transport}`. New agents get next free ports on spin-up.
- **`agent_defaults`**: values used if no per-agent override exists.
- **`agent_overrides`**: deep-merged over `agent_defaults` for specific agents.

## 5. API Surface

### Python module: `vault.py`

```python
# vault.py — lives in maestro-sdk/runtime/

class MasterVault:
    def __init__(self, vault_path: str = "~/.maestro/vault.json",
                 key_path: str = "~/.maestro/.vault_key"):
        ...

    def get_token(self, agent_id: str) -> str:
        """Return decrypted bot token for an agent."""

    def allocate_token(self, agent_id: str) -> str:
        """Draw next available token from pool, mark assigned. Returns token."""

    def get_ports(self, agent_id: str) -> dict:
        """Return {gateway: int, transport: int} for agent. Allocate if missing."""

    def get_config(self, agent_id: str) -> dict:
        """Return merged agent_defaults + agent_overrides for agent."""

    def get_all_agents(self) -> list[str]:
        """Return list of all agent_ids with port assignments."""

    def get_available_tokens(self) -> list[dict]:
        """Return tokens where status == 'available'."""

    def release_token(self, agent_id: str) -> None:
        """Mark token as available. Zero out assigned_agent."""

    def rotate_master_key(self, new_key: str) -> None:
        """Re-encrypt entire vault with new master key."""
```

### CLI tool: `vault_cli.py`

```bash
# Usage examples
python vault_cli.py get-token lexicon
python vault_cli.py allocate-token new_agent
python vault_cli.py get-ports proteus
python vault_cli.py get-config songbird --json
python vault_cli.py list-agents
python vault_cli.py provision-token --username "my_new_bot" --token "123:ABC"
python vault_cli.py rotate-key
```

## 6. Integration Points

### 6.1 `maestro_transport.py`

Replace this:
```python
bridge_url = self.config.get("gatewayBridgeUrl", "http://127.0.0.1:8644/maestro/notify")
```

With:
```python
from vault import MasterVault
vault = MasterVault()
bridge_url = self.config.get("gatewayBridgeUrl") or vault.get_config(self.agent_id)["gateway_bridge_url"]
```

### 6.2 `maestro_gateway_bridge.py`

Replace `.env` token reads:
```python
env_path = Path(f"{HERMES_HOME}/profiles/{agent_id}/.env")
```

With:
```python
from vault import MasterVault
vault = MasterVault()
token = vault.get_token(agent_id)
```

Fallback: if vault missing or unreadable, log a single WARNING and fall back to `.env`.

### 6.3 Agent `.env` files

Add deprecation warning in `send_message` / Hermes gateway:
```
WARNING: Bot token read from .env. Migrate to Master Vault for unified config.
```

This warning fires **once per process lifetime**.

### 6.4 Registry migration

`~/.maestro/registry.json` is superseded by the vault. On first read, if `registry.json` exists and vault doesn't, auto-import into vault and delete registry.json.

## 7. Spin-up Flow (future — not in this PR)

1. **Rosie** receives request: "Spin up agent X"
2. **Rosie** calls `vault.allocate_token("X")`
3. **Rosie** calls `vault.get_ports("X")` (auto-allocates if new)
4. **Rosie** writes agent config files referencing vault
5. **Rosie** starts gateway + transport
6. **Done** — zero Jesse involvement

## 8. Security Considerations

- **Key file permissions:** `chmod 600 ~/.maestro/.vault_key`
- **Passphrase backup:** If Jesse loses the passphrase, tokens are unrecoverable. Recommend backing up `.vault_key` to an offline location.
- **Token pool isolation:** Pool tokens are encrypted with the same key as the rest of the vault. Rotation re-encrypts everything.
- **No plaintext tokens in logs:** The vault module must redact tokens in `__repr__` and log output.

## 9. Implementation Plan

This spec is sized for **Stormtrooper** (single focused agent).

1. ** vault.py module** — encrypt/decrypt, CRUD operations, port allocation
2. ** vault_cli.py tool** — CLI wrapper
3. ** Migrate bridge** — `maestro_gateway_bridge.py` reads tokens from vault
4. ** Migrate transport** — `maestro_transport.py` reads config from vault
5. ** Registry import** — one-shot migration from `registry.json`
6. ** Deprecation warnings** — `.env` fallback for 30 days, then hard fail

## 10. Success Criteria

- [ ] `vault.json` is encrypted and unreadable without key
- [ ] A new agent can be configured by ONLY reading from vault (no `.env` edits)
- [ ] Existing agents boot with vault + `.env` fallback, single warning
- [ ] `registry.json` is gone or read-only after migration
- [ ] Token pool works: `allocate_token` decrements available count, marks assigned
- [ ] Port auto-allocation works: new agent gets next free gateway/transport pair
