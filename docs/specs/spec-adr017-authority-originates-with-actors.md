# ADR-017 Implementation Specification — Authority Originates with Actors

**Spec ID:** songbird-spec-adr017-20260706
**Author:** Songbird (CTO)
**Date:** 2026-07-06
**Status:** Draft
**Assignee:** Proteus (Tech Lead)
**Source ADR:** ~/Projects/Maestro/docs/adrs/adr-017-authority-originates-with-actors.md

---

## 1. Summary of Changes

Three code changes, one data migration, one config change:

1. `_check_dm_policy()` — check recipient-issued tokens instead of Lexicon-issued tokens
2. `MaestroTransport.__init__()` — remove `dm_policy.enabled` boolean, remove hardcoded Lexicon public key
3. Token storage — reorganize from flat to `issued/` and `received/` directories
4. Migration — dual-acceptance grace period for existing Lexicon-issued tokens
5. Config — remove `dm_policy.enabled` and `dm_policy.lexicon_public_key` from all agent configs

---

## 2. Current State (Baseline)

### 2.1 Token Storage

```
~/.maestro/dm_tokens/
  songbird.json       ← Lexicon-issued token for songbird
  proteus.json        ← Lexicon-issued token for proteus
  lexicon.json        ← Lexicon-issued token for lexicon
  hermes-prime.json   ← Lexicon-issued token for hermes-prime
  mnemosyne.json      ← Lexicon-issued token for mnemosyne
  sentinel.json       ← Lexicon-issued token for sentinel
  hermes.json         ← Lexicon-issued token for hermes
```

All tokens have `issuer_id: "lexicon"`. The filename is `{bearer_id}.json`.

### 2.2 Token Format (Current)

```json
{
  "token_id": "f8feca82-...",
  "version": 1,
  "issuer_id": "lexicon",
  "bearer_id": "songbird",
  "issuer_public_key": "4a23b487...",
  "payload": {
    "ven": "org.dm",
    "tgt": ["lexicon", "songbird", "hermes", "proteus", "mnemosyne"],
    "scope": ["dm", "delegate", "bb_write"]
  },
  "expiry": 1784906955,
  "issued_at": 1782314955,
  "nonce": "97281617...",
  "signature": "6a598c0d..."
}
```

### 2.3 Transport Config (Current)

```python
# maestro_transport.py lines 830-836
dm_policy = config.get("dm_policy", {})
self._dm_policy_enabled = bool(dm_policy.get("enabled", False))
self._dm_token_dir = Path(
    os.path.expanduser(dm_policy.get("token_dir", "~/.maestro/dm_tokens"))
)
self._dm_issuer_pubkey = dm_policy.get("lexicon_public_key", "") or dm_policy.get("sentinel_public_key", "")
self._dm_venue = dm_policy.get("venue", "org.dm")
```

### 2.4 DM Policy Check (Current)

```python
# maestro_transport.py lines 892-935
def _check_dm_policy(self, sender_id, recipient_id):
    token_path = self._dm_token_dir / f"{sender_id}.json"  # ← sender's token
    # ... load token ...
    # Check: is issuer Lexicon?
    if token.get("issuer_public_key", "") != self._dm_issuer_pubkey:
        return False, "untrusted_issuer"
    # Check: venue discriminator
    if payload.get("ven") != self._dm_venue:
        return False, "wrong_venue"
    # Check: is recipient in tgt list?
    if recipient_id not in tgt:
        return False, f"not_allowed:{recipient_id}"
```

### 2.5 DM Policy Gate (Current)

```python
# maestro_transport.py lines 1012-1022
if self._dm_policy_enabled and msg_type in ("direct", "directive"):
    if sender != "system":
        ok, reason = self._check_dm_policy(sender, recipient)
        if not ok:
            return web.json_response(
                {"accepted": False, "reason": f"dm_denied:{reason}"},
                status=403,
            )
```

### 2.6 tokens.py (Current)

`issue_token()` already supports any issuer — no changes needed.
`validate_token()` does cryptographic validation only — no policy — no changes needed.

---

## 3. Target State

### 3.1 Token Storage (Target)

```
~/.maestro/dm_tokens/
  issued/                    ← Tokens I (this agent) have issued to others
    proteus.json             ← I issued this to proteus
    lexicon.json             ← I issued this to lexicon
  received/                  ← Tokens others have issued to me
    lexicon.json             ← Lexicon issued this to me
```

The filename in `issued/` is `{bearer_id}.json` (who I gave it to).
The filename in `received/` is `{issuer_id}.json` (who gave it to me).

### 3.2 Token Format (Target)

No format changes. The token schema is unchanged. The only difference is `issuer_id` changes from `"lexicon"` to the actual issuing agent's ID.

### 3.3 Transport Config (Target)

```python
# maestro_transport.py — new init
dm_policy = config.get("dm_policy", {})
self._dm_token_dir = Path(
    os.path.expanduser(dm_policy.get("token_dir", "~/.maestro/dm_tokens"))
)
self._dm_venue = dm_policy.get("venue", "org.dm")
# REMOVED: self._dm_policy_enabled
# REMOVED: self._dm_issuer_pubkey
```

### 3.4 DM Policy Check (Target)

```python
def _check_dm_policy(self, sender_id, recipient_id):
    """Check DM permission: does the RECIPIENT have a token they issued for the SENDER?"""
    # Look up: recipient's issued tokens → does sender have one?
    token_path = self._dm_token_dir / "issued" / f"{sender_id}.json"
    if not token_path.exists():
        return False, "no_dm_token"

    try:
        token = json.loads(token_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False, "token_unreadable"

    # Cryptographic validation (unchanged)
    if TOKENS_AVAILABLE and _validate_token:
        valid, reason = _validate_token(token)
        if not valid:
            return False, f"token_invalid:{reason}"

    # Issuer check: did the RECIPIENT issue this token?
    if token.get("issuer_id") != recipient_id:
        return False, "not_my_token"

    # Bearer check: is the SENDER the bearer?
    if token.get("bearer_id") != sender_id:
        return False, "wrong_bearer"

    # Venue discriminator (unchanged)
    payload = token.get("payload", {})
    if payload.get("ven") != self._dm_venue:
        return False, "wrong_venue"

    return True, ""
```

Key changes from current:
- Token path: `issued/{sender_id}.json` instead of `{sender_id}.json`
- Issuer check: `issuer_id == recipient_id` instead of `issuer_public_key == lexicon_pubkey`
- Added: bearer check (`bearer_id == sender_id`)
- Removed: `tgt` list check (the token IS the authorization — no separate target list needed)
- Removed: `issuer_public_key` trust check (replaced by issuer_id match)

### 3.5 DM Policy Gate (Target)

```python
# Always-on for agents with tokens. No boolean toggle.
# Check: does the dm_tokens/issued/ directory exist and have entries?
if msg_type in ("direct", "directive"):
    if sender != "system":
        issued_dir = self._dm_token_dir / "issued"
        if issued_dir.exists() and any(issued_dir.iterdir()):
            ok, reason = self._check_dm_policy(sender, recipient)
            if not ok:
                # Migration grace period: also check old flat tokens
                ok_migration, _ = self._check_dm_policy_legacy(sender, recipient)
                if not ok_migration:
                    log.warning(f"DM denied: {sender} → {recipient} ({reason})")
                    return web.json_response(
                        {"accepted": False, "reason": f"dm_denied:{reason}"},
                        status=403,
                    )
```

The gate is always-on when the agent has issued tokens. No `dm_policy.enabled` boolean. The migration grace period is a fallback check against old Lexicon-issued tokens.

---

## 4. Migration Plan

### 4.1 Grace Period Mechanics

During migration, `_check_dm_policy` has a fallback path:

```python
def _check_dm_policy_legacy(self, sender_id, recipient_id):
    """Fallback: check old flat Lexicon-issued tokens during migration."""
    token_path = self._dm_token_dir / f"{sender_id}.json"  # old flat path
    if not token_path.exists():
        return False, "no_legacy_token"

    try:
        token = json.loads(token_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False, "token_unreadable"

    # Cryptographic validation
    if TOKENS_AVAILABLE and _validate_token:
        valid, reason = _validate_token(token)
        if not valid:
            return False, f"token_invalid:{reason}"

    # Legacy: check Lexicon-issued
    if token.get("issuer_id") != "lexicon":
        return False, "not_lexicon_token"

    # Legacy: check tgt list
    payload = token.get("payload", {})
    tgt = payload.get("tgt", [])
    if recipient_id not in tgt:
        return False, f"not_allowed:{recipient_id}"

    return True, ""
```

The legacy fallback is temporary. It is removed after all agents have migrated.

### 4.2 Migration Steps (Per Agent)

For each agent, in order:

1. **Create directory structure:**
   ```bash
   mkdir -p ~/.maestro/dm_tokens/issued
   mkdir -p ~/.maestro/dm_tokens/received
   ```

2. **Move existing tokens to received/:**
   The agent's own token (where they are the bearer) goes to `received/{issuer_id}.json`.
   ```bash
   # Example for songbird:
   # songbird.json has issuer_id=lexicon, bearer_id=songbird
   # → move to received/lexicon.json
   mv ~/.maestro/dm_tokens/songbird.json ~/.maestro/dm_tokens/received/lexicon.json
   ```

3. **Issue self-tokens to peers:**
   For each peer the agent wants to accept DMs from, issue a token:
   ```python
   from maestro.tokens import issue_token
   token = issue_token(
       bearer_id="proteus",
       payload={"ven": "org.dm"},
       issuer_id="songbird",
       issuer_private_key_hex=PRIVATE_KEY,
       issuer_public_key_hex=PUBLIC_KEY,
   )
   # Save to issued/proteus.json
   ```

4. **Update transport config:**
   Remove `dm_policy.enabled` and `dm_policy.lexicon_public_key` from the agent's `~/.maestro/configs/<agent>.json`.

5. **Restart transport:**
   ```bash
   systemctl --user restart maestro-transport-<agent>.service
   ```

6. **Verify:**
   ```bash
   # Check new token works
   curl -s -X POST http://127.0.0.1:<transport_port>/message \
     -H "Content-Type: application/json" \
     -d '{"id":"test-001","type":"direct","sender":{"agentId":"proteus"},"recipient":{"agentId":"songbird"},"content":"test"}'
   # Should return 200, not 403
   ```

### 4.3 Migration Order

1. Lexicon (token issuer for all existing tokens — migrate last to avoid breaking everyone)
2. Songbird
3. Proteus
4. Mnemosyne
5. Hermes-Prime
6. Stormtrooper
7. Sentinel
8. All worker agents
9. Lexicon (last — after everyone has their own tokens)

Lexicon goes last because all existing tokens are Lexicon-issued. If Lexicon migrates first and removes the legacy fallback, everyone else's tokens stop working.

### 4.4 Grace Period Removal

After all agents have migrated and verified:
1. Remove `_check_dm_policy_legacy()` from `maestro_transport.py`
2. Remove old flat token files from `~/.maestro/dm_tokens/`
3. This is a separate commit, not part of the initial migration

---

## 5. Code Changes — Exact

### 5.1 File: `~/Projects/Maestro/code/runtime/maestro_transport.py`

#### Change 1: `__init__()` — lines 830-836

**Remove:**
```python
self._dm_policy_enabled = bool(dm_policy.get("enabled", False))
self._dm_issuer_pubkey = dm_policy.get("lexicon_public_key", "") or dm_policy.get("sentinel_public_key", "")
```

**Replace with:**
```python
# DM enforcement is always-on when the agent has issued tokens.
# No boolean toggle. No hardcoded issuer public key.
```

#### Change 2: `_check_dm_policy()` — lines 892-935

Full rewrite. See §3.4 above for the target implementation.

#### Change 3: DM policy gate — lines 1012-1022

**Remove:**
```python
if self._dm_policy_enabled and msg_type in ("direct", "directive"):
```

**Replace with:**
```python
if msg_type in ("direct", "directive"):
```

And add the migration fallback inside the block. See §3.5 above.

#### Change 4: New method `_check_dm_policy_legacy()`

Add after `_check_dm_policy()`. See §4.1 above.

### 5.2 File: `~/Projects/Maestro/code/runtime/maestro/tokens.py`

No changes. `issue_token()` and `validate_token()` are already issuer-agnostic.

### 5.3 Config Files: `~/.maestro/configs/*.json`

For each agent config, remove:
```json
"dm_policy": {
    "enabled": true,
    "lexicon_public_key": "...",
    "token_dir": "~/.maestro/dm_tokens",
    "venue": "org.dm"
}
```

Replace with (keep only what's still needed):
```json
"dm_policy": {
    "token_dir": "~/.maestro/dm_tokens",
    "venue": "org.dm"
}
```

---

## 6. Testing Plan

### 6.1 Unit Tests

File: `~/Projects/Maestro/code/tests/test_dm_policy.py` (new)

| Test | Description |
|------|-------------|
| `test_own_token_accepted` | Recipient issued token for sender → 200 |
| `test_wrong_issuer_rejected` | Token issued by someone else → 403 |
| `test_wrong_bearer_rejected` | Token issued for different bearer → 403 |
| `test_no_token_rejected` | No token file → 403 |
| `test_expired_token_rejected` | Token past expiry → 403 |
| `test_invalid_signature_rejected` | Tampered signature → 403 |
| `test_legacy_lexicon_token_accepted` | Old flat Lexicon token → 200 (grace period) |
| `test_legacy_wrong_tgt_rejected` | Old flat token, recipient not in tgt → 403 |
| `test_no_tokens_dir_no_enforcement` | No issued/ directory → no DM check |
| `test_empty_issued_dir_no_enforcement` | Empty issued/ directory → no DM check |

### 6.2 Integration Tests

| Test | Description |
|------|-------------|
| `test_end_to_end_dm` | Proteus issues token for Songbird → Songbird accepts Proteus's DM |
| `test_cross_agent_rejection` | Proteus issues token for Songbird → Songbird rejects Lexicon's DM (no token) |
| `test_migration_dual_accept` | Both new token AND old Lexicon token work during migration |
| `test_token_issuance_flow` | `issue_token()` with any issuer → `validate_token()` passes |

### 6.3 Migration Test

1. Set up test agent with old flat Lexicon-issued token
2. Run migration steps
3. Verify old token still works (grace period)
4. Issue new self-token to a peer
5. Verify new token works
6. Verify peer without token is rejected

---

## 7. Rollback Plan

### 7.1 Per-Agent Rollback

If an agent's migration fails:
1. Restore old config (with `dm_policy.enabled: true` and `dm_policy.lexicon_public_key`)
2. Restore old flat token file from `received/lexicon.json` back to `{agent_id}.json`
3. Restart transport
4. Verify with old token

### 7.2 Full Rollback

If the entire migration needs to be reversed:
1. Revert `maestro_transport.py` to pre-migration version
2. Restore all agent configs to include `dm_policy.enabled` and `dm_policy.lexicon_public_key`
3. Restore all flat token files from `received/lexicon.json`
4. Restart all transports
5. Run smoke test

### 7.3 Rollback Triggers

Rollback if:
- More than 2 agents fail migration
- Smoke test fails after migration
- Jesse orders rollback

---

## 8. Pitfalls

1. **Lexicon must migrate last.** All existing tokens are Lexicon-issued. If Lexicon migrates first, the legacy fallback on Lexicon's transport won't help anyone else.

2. **Token directory structure must exist before transport restart.** If `issued/` doesn't exist, the transport treats it as "no tokens issued" and skips DM enforcement entirely. Create the directory structure before restarting.

3. **The `tgt` list is removed from the new check.** The token itself IS the authorization. If Alice issued a token to Bob, Bob is authorized. No separate target list. This is simpler and correct — but it means the migration must ensure every agent issues tokens to every peer they want to accept DMs from.

4. **Bearer check is new.** The current code doesn't verify `bearer_id` matches `sender_id`. The new code does. This prevents token reuse — Bob can't use Alice's token to impersonate Alice.

5. **`dm_policy.enabled` removal is breaking for config validation.** If any config validator checks for this field, it must be updated.

6. **The legacy fallback is temporary.** It must be removed after migration. Leaving it in creates a permanent backdoor where Lexicon-issued tokens bypass the per-agent model.

---

## 9. Files Changed Summary

| File | Change |
|------|--------|
| `maestro_transport.py` | Rewrite `_check_dm_policy()`, add `_check_dm_policy_legacy()`, remove `_dm_policy_enabled` and `_dm_issuer_pubkey`, update DM gate |
| `~/.maestro/configs/*.json` (18 files) | Remove `dm_policy.enabled` and `dm_policy.lexicon_public_key` |
| `~/.maestro/dm_tokens/` | Reorganize to `issued/` and `received/` subdirectories |
| `tests/test_dm_policy.py` (new) | 10 unit tests |
| `tokens.py` | No changes |

---

## 10. Acceptance Criteria

1. Each agent can issue DM tokens via `issue_token()`
2. Transport accepts messages when sender has a token issued by recipient
3. Transport rejects messages when sender has no token from recipient
4. Transport rejects messages when token is expired, has invalid signature, or wrong bearer
5. Legacy Lexicon-issued tokens still work during migration grace period
6. `dm_policy.enabled` boolean is removed from all configs
7. All 10 unit tests pass
8. Integration smoke test passes (two agents, token exchange, DM delivery)
9. No 403s on existing communication paths after migration
