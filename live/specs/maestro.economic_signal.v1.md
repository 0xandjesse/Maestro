# Maestro Extension: `maestro.economic_signal`

**Version:** 1.0.0-draft  
**Status:** Proposed — awaiting CTO (Songbird) review  
**Scope:** Extension to the core Maestro protocol. Maestro certifies identity and message integrity only. Settlement happens off-protocol, wallet-to-wallet.

---

## 1. Purpose

Enable agents in the Maestro mesh to discover, negotiate, and transport **payment intent** metadata for peer-to-peer economic transactions. Maestro does NOT execute, settle, or guarantee any transfer of value. It only carries signed intent.

---

## 2. Extension Header Format

Economic signals travel inside a standard Maestro envelope via a namespaced `extension` block:

```json
{
  "id": "<uuid>",
  "type": "signal",
  "sender": { "agentId": "hermes", "signature": "<agent-sig>" },
  "target": { "agentId": "proteus" },
  "timestamp": "2026-05-14T02:00:00.000Z",
  "nonce": "<uuid-v4-hex>",
  "conversation": "maestro",
  "extension": {
    "namespace": "maestro.economic_signal.v1",
    "action": "TRANSFER_INTENT",
    "body": {
      "schema": "x402",
      "transfer": {
        "amount": "50.00",
        "currency": "USD",
        "asset": "USDC",
        "chain": "base",
        "fromWallet": "0x<sender-wallet>",
        "toWallet": "0x<recipient-wallet>",
        "purpose": "code-review-task-4821"
      },
      "expiresAt": "2026-05-14T03:00:00.000Z",
      "maxGas": "0.05",
      "memo": "Invoice #4821 — payment for review of PR #357"
    }
  }
}
```

---

## 3. Action Types

| Action | Direction | Description |
|--------|-----------|-------------|
| `TRANSFER_INTENT` | A → B | Initiates a payment request or offer. |
| `TRANSFER_ACK` | B → A | Receiver accepts the intent (does NOT execute). |
| `TRANSFER_REJECT` | B → A | Receiver declines. |
| `TRANSFER_RECEIPT` | B → A (optional) | Off-chain settlement hash, posted after wallet execution. |

---

## 4. x402-Compatible Schema

The `transfer` object is a strict subset of [x402](https://docs.x402.org/) `PaymentRequirements` + `PaymentPayload`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | string (decimal) | yes | Human-readable amount. |
| `currency` | string | yes | Fiat unit for display (e.g., `USD`). |
| `asset` | string | yes | On-chain asset symbol (e.g., `USDC`, `ETH`). |
| `chain` | string | yes | Target chain identifier (e.g., `base`, `ethereum`). |
| `fromWallet` | address | yes | Sender wallet address. |
| `toWallet` | address | yes | Recipient wallet address. |
| `purpose` | string | yes | Task / invoice reference. |
| `expiresAt` | ISO-8601 | yes | Intent expiration. |
| `maxGas` | string | no | Maximum allowable gas / fee in `currency`. |
| `memo` | string | no | Human-readable description. |

---

## 5. Signature Coverage

The agent-level `sender.signature` must cover the canonical JSON of the `transfer` object ONLY (not the full envelope). This keeps the scope clean: Maestro signs the envelope; the agent signs the economic payload.

```
signature = sign(
  payload = canonical_json(extension.body.transfer),
  key = sender_agent_wallet_key
)
```

Verification: the receiver reconstructs the canonical JSON and validates against `sender.agentId`'s registered wallet public key.

---

## 6. No-Execution Clause

**Maestro nodes MUST NOT:**
- execute on-chain transactions,
- hold private keys for settlement,
- act as escrow or oracle for balance truth,
- enforce payment upon `TRANSFER_ACK`.

Acknowledgment is social/contractual only. Actual settlement is a wallet-level concern outside Maestro.

---

## 7. Replay Protection

Reuses the envelope-level `nonce` + `timestamp` drift checks provided by `NonceSet` in core transport. No additional nonce required inside the extension.

Requirements:
- `expiresAt` MUST be ≤ `timestamp` + 300 seconds (or whatever the transport `max_drift_sec` is).
- If a `TRANSFER_INTENT` is replayed with a fresh envelope nonce but the same `transfer` payload, the receiver MAY optionally deduplicate on `(fromWallet, toWallet, purpose, amount)`.

---

## 8. Receiver Behavior

On receiving a `signal` with `extension.namespace == "maestro.economic_signal.v1"`:

1. Validate envelope (nonce, timestamp, signature).
2. Validate extension schema (required fields present, types correct).
3. Verify agent-level signature over `transfer` object.
4. Route to agent's internal handler (NOT the LLM chat endpoint).
5. Ack structurally (like directives): return `{"accepted": true, "type": "signal", "agentId": "<self>"}`.

---

## 9. Error Responses

| Scenario | HTTP / Body |
|----------|-------------|
| Invalid extension schema | `400 {"accepted": false, "reason": "invalid economic_signal schema: missing field 'amount'"}` |
| Signature mismatch | `400 {"accepted": false, "reason": "transfer signature verification failed"}` |
| Expired intent (`expiresAt` < now) | `400 {"accepted": false, "reason": "transfer intent expired"}` |
| Unsupported namespace version | `400 {"accepted": false, "reason": "unsupported economic_signal version"}` |

---

## 10. Open Questions

1. **Wallet registry**: Should Maestro host a `/registry/wallets/{agentId}` endpoint, or is that out-of-band?
2. **Receipt standardization**: Is `TRANSFER_RECEIPT` in scope for v1, or deferred to v2?
3. **Multi-hop routing**: Can an economic_signal be forwarded through an intermediary agent (e.g., B → C → D)?
4. **Cancellation**: Should we add `TRANSFER_CANCEL` before the receiver ACKs?

---

## 11. Implementation Notes (for Proteus)

- Add `signal` to the allowed `type` enum in `handle_message` alongside `directive`, `system`, `direct`, etc.
- Create `_handle_economic_signal(message)` method in transport. Structural handler only — no LLM.
- Validate namespace version (`maestro.economic_signal.v1` supported; reject others).
- Optional: add wallet pub-key storage in `~/.maestro/registry/wallets.json`.
- Update `_route_system_reply` or add `_route_signal_reply` for `TRANSFER_ACK` / `TRANSFER_REJECT` responses.

---

*Drafted: 2026-05-14*  
*Author: Proteus (Tech Lead)*  
*Reviewer: Songbird (CTO)*
