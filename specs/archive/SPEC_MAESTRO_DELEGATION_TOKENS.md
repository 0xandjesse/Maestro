# Spec: Maestro Delegation Token Primitive

**ARCHIVED:** 2026-06-03 — Superseded by SPEC_MAESTRO_TOKEN_PRIMITIVE.md
**Migration:** The old spec embedded `scope`, `actions`, `resources`, `venues`, `allow_delegation`, `heartbeat_required`, and `delegation_chain` into the token schema — violating the ADR principle that these are payload-level concerns. The new spec is a pure protocol primitive: no type/scope/actions at protocol level. All downstream systems use the same primitive. See SPEC_MAESTRO_TOKEN_PRIMITIVE.md for the replacement and §11 for migration guidance.

**Status:** Draft v1 — extracted from SPEC_TASKMASTER_ECONOMIC_LAYER.md Part 2
**Author:** Songbird
**Date:** 2026-05-29
**Purpose:** Standalone specification for the delegation token primitive extracted as a Maestro transport-layer module (`maestro/tokens.py`). This is a protocol primitive, not an application feature. TaskMaster, Venues, Plaza, and LOCR all inherit the same token via import.
**Parent:** Extracted from SPEC_TASKMASTER_ECONOMIC_LAYER.md Part 2 (Capability-Based Delegation Tokens)

---

## 1. Why This Is a Protocol Primitive

Capability-based access control is a transport concern, not an application concern. The enforcement points — `bb_read` and `send_message` — live in the transport layer. Validating delegation tokens at those points prevents confused deputy attacks before any application code runs.

If delegation tokens remain in TaskMaster, Venues, Plaza, and LOCR each build their own credential layer within six months, and the swarm spends the next year reconciling three incompatible auth systems. That cost dwarfs any perceived "scope creep" from extracting the primitive now.

| Concern | Protocol Primitive | Application Feature |
|---------|-------------------|-------------------|
| Token schema | Defined once, enforced everywhere | Each subsystem defines its own |
| Enforcement points | At bb_read/send_message in transport | Wherever the app code remembers to check |
| Cross-subsystem auth | One token works across Venues, Plaza, LOCR | Each subsystem issues its own, none interoperate |
| Confused deputy prevention | Transport rejects before app code runs | App-level check can be bypassed |
| Migration burden | One module to test, one to migrate | N modules to test, N migrations |
| Documentation | One spec, one reference | N specs, N divergences |

---

## 2. Module Location and Structure

```
maestro-sdk/runtime/
├── maestro/
│   ├── __init__.py          # Package init (exists)
│   ├── __main__.py           # CLI entry point (exists)
│   ├── secrets.py            # Env-based key loading (exists)
│   └── tokens.py             # NEW: delegation token primitives
├── maestro_crypto.py         # Ed25519 sign/verify/hash (exists)
└── maestro_transport.py      # Transport layer (token enforcement added here)
```

`tokens.py` imports from `maestro_crypto.py` for signing and verification. It has zero dependencies on TaskMaster, Venues, Plaza, or any application code. TaskMaster, Venues, etc. import from `maestro.tokens`.

---

## 3. Token Schema

```json
{
  "token_id": "<uuid>",
  "version": 1,

  "delegator_id": "proteus",
  "delegate_id": "stormtrooper",
  "delegator_public_key": "<hex>",

  "scope": {
    "actions": ["bb_read", "bb_write", "file_write", "send_message"],
    "resources": ["board:proteus_work_queue", "board:swarm_health_bb"],
    "venues": ["local"],
    "max_file_size_bytes": 1048576,
    "allow_terminal": false,
    "allow_delegation": false
  },

  "delegation_chain": {
    "depth": 1,
    "max_depth": 2,
    "lineage_root": "proteus",
    "ancestry": [
      {
        "delegator": "proteus",
        "delegate": "stormtrooper",
        "signature": "<hex>",
        "timestamp": 1716854400
      }
    ]
  },

  "expiry": 1716940800,
  "issued_at": 1716854400,
  "nonce": "<random 32 bytes hex>",

  "revocation_endpoint": "maestro://proteus/revoke",
  "heartbeat_required": true,
  "heartbeat_interval_seconds": 300,

  "human_authorized": false,

  "signature": "<Ed25519 signature over all fields above>"
}
```

### 3.1 Scope Actions Reference

| Action | What it gates | Enforced at |
|--------|--------------|-------------|
| `bb_read` | Reading any blackboard key | Transport `_process_bb_read` |
| `bb_write` | Writing to any blackboard | Transport `_process_bb_write` |
| `bb_delete` | Deleting from any blackboard | Transport `_process_bb_delete` |
| `bb_search` | Searching a blackboard | Transport `_process_bb_search` |
| `send_message` | Sending P2P messages (maestro:agent targets) | Transport `handle_message` (outbound) |
| `file_write` | Writing files via terminal/file tools | Tool-layer enforcement |
| `checklist_execute` | Executing checklist items | Tool-layer enforcement |

### 3.2 Resource Specifiers

Resources use a hierarchical naming convention:

- `board:*` — all boards
- `board:proteus_work_queue` — specific board
- `board:swarm_*` — all swarm-scoped boards
- `file:/home/andjesse/maestro-sdk/runtime/*` — glob-based file paths
- `target:maestro:*` — all maestro P2P targets
- `target:maestro:proteus` — specific P2P target

---

## 4. Token Lifecycle

```
Issue → Present → Validate → Execute → Verify → Complete/Revoke
  │        │         │          │         │           │
  │        │         │          │         │           └─ Token invalidated
  │        │         │          │         └─ Verification hook runs
  │        │         └─ Recipient verifies chain + scope + expiry
  │        └─ Delegate presents token to execute action
  └─ Delegator signs token with MAESTRO_PRIVATE_KEY
```

---

## 5. Token Validation Algorithm

When any agent receives a delegation token (presented alongside an action), it validates:

1. **Signature check**: Verify `signature` against `delegator_public_key` over the full token body (minus signature field). Uses `maestro_crypto.verify()`.

2. **Public key resolution**: Look up `delegator_public_key` in the registry (`~/.maestro/registry.json`), confirm it matches the claimed `delegator_id`. Registry is a flat JSON array with `agentId` and `publicKey` fields.

3. **Chain ancestry**: For `depth > 1`, walk the ancestry chain, verifying each hop's signature. Each hop record: `{delegator, delegate, signature, timestamp}`.

4. **Depth ceiling**: `depth <= max_depth` — hard-fail if exceeded.

5. **Lineage integrity**: `lineage_root` matches the original issuer (depth-0 delegator). First ancestry entry's `delegator` must equal `lineage_root`.

6. **Expiry check**: `expiry > now()` — hard-fail if expired (UTC epoch seconds).

7. **Scope enforcement**: Delegate's attempted action must be within `scope.actions`, target resource within `scope.resources`, and venue within `scope.venues`.

8. **Heartbeat liveness**: If `heartbeat_required`, delegator must have issued a heartbeat (`delegation_heartbeat` P2P message) within `heartbeat_interval_seconds` of `now()`. Missing heartbeat for 2× interval → token considered revoked.

---

## 6. Delegation Chain Rules

1. **Authority never increases through delegation.** A delegate's effective authority is the intersection of all ancestors' scopes.

2. **Depth is bounded.** `max_depth` is set by the root delegator. Any hop exceeding it is rejected.

3. **Delegation cannot be re-delegated unless `scope.allow_delegation` is true.**

4. **Expiry is monotonically decreasing.** Each hop's expiry must be ≤ its parent's expiry.

5. **Revocation propagates:**
   - **Heartbeat expiry (crash/absence):** Recursive. Each delegate checks heartbeat from its immediate delegator. When a delegator goes silent, its direct delegates auto-revoke, cascading through the chain within 2× `heartbeat_interval_seconds` per hop.
   - **Explicit revocation:** The revoking delegator sends `revoke_delegation` to its direct delegate AND walks the issuance log to broadcast to every node in the subtree.

---

## 7. Enforcement Points

### 7.1 bb_read Enforcement

When a transport receives `type: "BB_READ"`, before executing `_process_bb_read`, it checks:

1. If the message carries a `delegation_token` field, validate the token
2. Confirm `scope.actions` includes `"bb_read"`
3. Confirm the requested `boardId` matches a resource in `scope.resources`
4. If validation fails, return `{"accepted": false, "reason": "delegation_token_invalid", "detail": "..."}` without processing

### 7.2 send_message Enforcement

When the `send_message` tool resolves a `maestro:<agent>` target, before dispatching via the transport:

1. If a delegation token is provided in the tool call, validate it
2. Confirm `scope.actions` includes `"send_message"`
3. Confirm the target agent matches a resource in `scope.resources`
4. If validation fails, return an error to the caller without dispatching the message

### 7.3 Outbound P2P (Transport-Level)

When the transport routes a P2P message, if Zero Trust is enabled and the message carries a delegation token:

1. Validate the token chain
2. Confirm the token authorizes the sending agent to act as the delegator
3. Attach the original delegation provenance to the outgoing message envelope

---

## 8. Heartbeat Protocol

When `heartbeat_required: true`:

1. The delegator sends a P2P heartbeat message every `heartbeat_interval_seconds`:
   ```json
   {
     "type": "delegation_heartbeat",
     "token_id": "<uuid>",
     "delegator_id": "proteus",
     "timestamp": 1716854700
   }
   ```

2. The delegate tracks `last_heartbeat` per token_id. If `now() - last_heartbeat > 2 * heartbeat_interval_seconds`, the token is considered revoked.

3. Heartbeat messages are structural (`type: "delegation_heartbeat"`) — processed without LLM invocation.

4. **Heartbeat channel abstraction:** The heartbeat protocol defines a `heartbeat_channel` abstract interface that currently resolves to P2P messaging (local transport). When cross-venue support ships in Phase 4, the channel can be swapped to a venue-specific transport without changing the token schema or heartbeat protocol.

---

## 9. Revocation

Two mechanisms:

1. **Explicit revocation**: Delegator sends `revoke_delegation` to delegate + walks issuance log for full subtree broadcast.

2. **Heartbeat expiry**: Covered in §8.

Revocation is final. A revoked token cannot be re-presented. The revocation is recorded on the delegator's BB for audit.

---

## 10. Human-Agent Authority Distinction

Human-originated tokens carry a `human_authorized: true` flag and are signed with Jesse's personal key (separate from any agent key):

- Human-authorized tokens cannot be re-delegated (even with `allow_delegation: true`)
- Human-authorized tokens bypass the three-strikes verification rule
- Human-authorized tokens appear with a `[HUMAN_AUTHORIZED]` marker in all audit logs

---

## 11. Crypto Primitives (from maestro_crypto.py)

```python
from maestro_crypto import (
    sign,         # sign(message: str, private_key_hex: str) -> str (hex signature)
    verify,       # verify(message: str, signature_hex: str, public_key_hex: str) -> bool
    hash_string,  # hash_string(input_str: str) -> str (SHA-256 hex)
    hash_concat,  # hash_concat(*parts: str) -> str
)
```

Token signing uses `canonical_json(token_fields)` → SHA-256 hash → Ed25519 sign.

---

## 12. Migration Path

### Phase 0: Key Hygiene (immediate)
- All 9 agents need `MAESTRO_PRIVATE_KEY` / `MAESTRO_PUBLIC_KEY` in `.env`
- All 9 agents need `publicKey` in `registry.json`
- Currently: 2 of 9 have registry entries (lexicon, proteus). 2 of 9 have private keys (songbird, proteus). This is a blocker.

### Phase 1: Module + Spec (this PR)
- `maestro/tokens.py` implemented
- Integration tests at enforcement points
- Spec merged

### Phase 2: Transport Integration
- `maestro_transport.py` gains token validation at `BB_READ` and outbound P2P
- `send_message_tool.py` gains token parameter + validation
- Feature-gated behind Zero Trust toggle (`/zerotrust_on`)

### Phase 3: TaskMaster Inherits
- TaskMaster imports `from maestro.tokens import issue_token, validate_token, revoke_token`
- Economic layer wires token lifecycle into task lifecycle
- No code duplication

---

## 13. API Reference

```python
# maestro/tokens.py

def issue_token(
    delegator_id: str,
    delegate_id: str,
    delegator_private_key_hex: str,
    scope: dict,
    max_depth: int = 2,
    expiry_seconds: int = 3600,
    heartbeat_required: bool = True,
    heartbeat_interval_seconds: int = 300,
    human_authorized: bool = False,
    parent_token: dict | None = None,  # for re-delegation
) -> dict:
    """Issue a new delegation token. Signs with delegator's private key.
    If parent_token is provided, builds on the existing delegation chain."""
    ...

def validate_token(
    token: dict,
    action: str,
    resource: str,
    venue: str = "local",
    registry: list | None = None,
    heartbeat_tracker: dict | None = None,
) -> tuple[bool, str]:
    """Validate a delegation token for the given action/resource/venue.
    Returns (valid, reason). Registry defaults to loading from ~/.maestro/registry.json."""
    ...

def revoke_token(
    token_id: str,
    delegator_id: str,
    delegator_private_key_hex: str,
    issuance_log: dict | None = None,
) -> dict:
    """Revoke a delegation token and broadcast to all downstream delegates.
    Returns revoke message envelope for P2P dispatch."""
    ...

def send_heartbeat(
    token_id: str,
    delegator_id: str,
    delegate_id: str,
    transport_port: int,
) -> bool:
    """Send a delegation heartbeat P2P message to the delegate.
    Returns True if the heartbeat was accepted."""
    ...

def canonical_json(token: dict) -> str:
    """Serialize a token for signing: sorted keys, no whitespace."""
    ...

def verify_chain(token: dict, registry: list) -> tuple[bool, str]:
    """Verify the full delegation chain ancestry.
    Returns (valid, reason)."""
    ...
```

---

## 14. Integration Test Suite

### Test 1: Basic Issue/Validate Round-Trip
- Issue token (proteus → stormtrooper, scope: bb_read on proteus_work_queue)
- Validate for action=bb_read, resource=board:proteus_work_queue → passes
- Validate for action=bb_write, same resource → fails (action not in scope)

### Test 2: Signature Verification
- Issue token with valid signature
- Tamper with token content → validation fails

### Test 3: Expiry Enforcement
- Issue token with expiry_seconds=1
- Sleep 2 seconds
- Validation fails with "expired"

### Test 4: Chain Depth Enforcement
- Issue token with max_depth=1
- Re-delegate (depth 2) → rejected at issue time

### Test 5: Resource Scope Enforcement
- Token scoped to board:proteus_work_queue
- bb_read on board:oversight_bb → rejected (resource mismatch)

### Test 6: bb_read Transport Enforcement
- Send BB_READ message with valid token → processed
- Send BB_READ message with invalid token → rejected with reason

### Test 7: send_message Enforcement
- send_message with valid token scoped to target:maestro:stormtrooper → dispatched
- send_message with token scoped to target:maestro:proteus only → rejected for target:maestro:stormtrooper

### Test 8: Heartbeat Auto-Revocation
- Issue token with heartbeat_required=True, heartbeat_interval_seconds=1
- Validate passes while heartbeat is fresh
- Wait 3 seconds without heartbeat
- Validation fails with "heartbeat_missing"

### Test 9: Revocation Propagation
- Issue token (depth 1, max_depth=2)
- Re-delegate (depth 2)
- Revoke root token
- Both tokens fail validation

---

## 15. Key Files

| File | Action | Phase |
|------|--------|-------|
| `maestro-sdk/runtime/maestro/tokens.py` | **CREATE** — issue, validate, revoke, heartbeat, chain verification | 1 |
| `maestro-sdk/runtime/maestro_crypto.py` | Existing — Ed25519 primitives (no changes) | — |
| `maestro-sdk/runtime/maestro_transport.py` | MODIFY — token validation at BB_READ and outbound P2P | 2 |
| `maestro-sdk/runtime/tools/send_message_tool.py` | MODIFY — token parameter + validation | 2 |
| `maestro-sdk/specs/SPEC_MAESTRO_DELEGATION_TOKENS.md` | **CREATE** — this document | 1 |
| `maestro-sdk/tests/test_delegation_tokens.py` | **CREATE** — integration tests | 1 |
| `~/.maestro/registry.json` | MODIFY — add publicKey for all 9 agents | 0 |
| `~/.hermes/profiles/*/ .env` | MODIFY — add MAESTRO_PRIVATE_KEY/MAESTRO_PUBLIC_KEY for all agents | 0 |

---

## 16. Success Criteria

1. `maestro/tokens.py` can issue, validate, and revoke delegation tokens using Ed25519 signatures
2. Token validation rejects: bad signatures, expired tokens, scope violations, depth exceed, missing heartbeats
3. Integration tests pass at both bb_read and send_message enforcement points
4. TaskMaster can `from maestro.tokens import validate_token` with zero code changes to the tokens module
5. A scope-violating action at bb_read returns `{"accepted": false, "reason": "delegation_token_invalid"}` before any data is accessed
