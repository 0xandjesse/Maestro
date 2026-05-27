# Zero Trust Provenance — Python Port Specification

**Status:** Ready for implementation
**Source:** TypeScript SDK (`src/crypto/index.ts`, `src/provenance/builder.ts`, `src/connection/provenanceEnforcer.ts`, `src/types/index.ts`)
**Target:** `maestro_transport.py`
**Implementer:** Proteus

---

## Overview

Port the Maestro Zero Trust provenance system from TypeScript to the Python transport. This adds cryptographic message signing and verification as a runtime toggle — `/zerotrust_on` and `/zerotrust_off`. When enabled, every outbound message is signed with the agent's Ed25519 private key, and every inbound message is verified against the sender's registered public key. Messages failing verification are dropped before reaching the LLM.

---

## 1. Crypto Primitives (`maestro_crypto.py` — NEW FILE)

Create `runtime/maestro_crypto.py` with the following functions. Use **PyNaCl** (`nacl.bindings` or `nacl.signing`) for Ed25519 — it's pure Python, no C extensions needed, and is available via `pip install pynacl`.

### 1.1 `hash_string(input: str) -> str`
SHA-256 hash of a UTF-8 string. Returns lowercase hex.
```python
import hashlib
def hash_string(input: str) -> str:
    return hashlib.sha256(input.encode('utf-8')).hexdigest()
```

### 1.2 `hash_concat(*parts: str) -> str`
SHA-256 of concatenated parts.
```python
def hash_concat(*parts: str) -> str:
    return hash_string(''.join(parts))
```

### 1.3 `generate_key_pair() -> dict`
```python
def generate_key_pair() -> dict:
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    return {
        "private_key": sk.encode(encoder=HexEncoder).decode(),
        "public_key": sk.verify_key.encode(encoder=HexEncoder).decode(),
    }
```
Returns `{"private_key": "<hex>", "public_key": "<hex>"}`.

### 1.4 `sign(message: str, private_key_hex: str) -> str`
```python
def sign(message: str, private_key_hex: str) -> str:
    # SHA-256 hash the message per spec, then sign the hash
    msg_hash = hashlib.sha256(message.encode('utf-8')).digest()
    sk = SigningKey(private_key_hex, encoder=HexEncoder)
    signed = sk.sign(msg_hash)
    return signed.signature.hex()
```

### 1.5 `verify(message: str, signature_hex: str, public_key_hex: str) -> bool`
```python
def verify(message: str, signature_hex: str, public_key_hex: str) -> bool:
    msg_hash = hashlib.sha256(message.encode('utf-8')).digest()
    try:
        vk = VerifyKey(public_key_hex, encoder=HexEncoder)
        vk.verify(msg_hash, bytes.fromhex(signature_hex))
        return True
    except Exception:
        return False
```

### 1.6 `original_signature_payload(content: str, timestamp: int, sender_agent_id: str) -> str`
```python
def original_signature_payload(content: str, timestamp: int, sender_agent_id: str) -> str:
    return hash_concat(content, str(timestamp), sender_agent_id)
```

### 1.7 `attestation_payload(previous_signature: str, content_hash: str, timestamp: int) -> str`
```python
def attestation_payload(previous_signature: str, content_hash: str, timestamp: int) -> str:
    return hash_concat(previous_signature, content_hash, str(timestamp))
```

---

## 2. Key Management

### 2.1 Key generation on first boot
When the transport starts, check for `MAESTRO_PRIVATE_KEY` in the agent's `.env`:
- If present: load it. Also load `MAESTRO_PUBLIC_KEY`.
- If absent: call `generate_key_pair()`, save both to `.env` file (append to it — do NOT overwrite), log the public key.

### 2.2 Public key in registry
When an agent registers with the mesh (`self.registry.register(...)`), include `public_key` in the capabilities payload. The `LocalRegistry.register()` can be extended to accept an optional `public_key` kwarg and store it alongside `agentId` and `webhookEndpoint`.

### 2.3 Public key lookup
Add a method `registry.get_public_key(agent_id) -> Optional[str]` that returns the hex public key for a given agent, or None.

---

## 3. Zero Trust Toggle (`/zerotrust_on`, `/zerotrust_off`)

Add two commands to `handle_webhook()` alongside the existing `/shutup` / `/stfu`:

```
/zerotrust_on  → self._zerotrust_enabled = True
/zerotrust_off → self._zerotrust_enabled = False
```

- `_zerotrust_enabled` defaults to `False` (backward compatible — local mesh works as-is)
- **Per-agent only** — do NOT broadcast. Each agent toggles independently. This is critical for real-world deployment: one agent might be on a hostile network requiring signed messages, while another is on a trusted local socket with no crypto overhead.
- Return `{"accepted": True, "zerotrust": <bool>, "agentId": self.agent_id}`

---

## 4. Outbound Signing (when enabled)

When `_zerotrust_enabled` is True, every outbound message gets a `provenance` field added **after** the LLM generates the response:

### 4.1 In `_process_message()`, after `output = await self.hermes.send_and_complete(message)`, before building the reply dict:

```python
if self._zerotrust_enabled:
    payload = original_signature_payload(output, int(time.time() * 1000), self.agent_id)
    original_sig = sign(payload, self._private_key)
    content_hash = hash_string(output)
    provenance = {
        "mode": "full",
        "chain": [],
        "originalSignature": original_sig,
        "contentHash": content_hash,
    }
```

### 4.2 Add `provenance` to the reply dict:
```python
reply = {
    ...
    "provenance": provenance if self._zerotrust_enabled else None,
    "timestamp": int(time.time() * 1000),
    ...
}
```

Remove `None` provenance fields from the dict before sending (strip if falsy).

---

## 5. Inbound Verification (when enabled)

When `_zerotrust_enabled` is True, every inbound P2P message is verified **before** it reaches the LLM:

### 5.1 In `handle_webhook()`, after dedup/rate-limit/loop guards, before forwarding to Hermes:

```python
if self._zerotrust_enabled and sender_id:
    msg_prov = message.get("provenance")
    if msg_prov and msg_prov.get("originalSignature"):
        content = message.get("content", "")
        timestamp = message.get("timestamp", 0)
        payload = original_signature_payload(content, timestamp, sender_id)
        sender_pubkey = self.registry.get_public_key(sender_id)
        if sender_pubkey and verify(payload, msg_prov["originalSignature"], sender_pubkey):
            log.info(f"[ZT] Signature verified: {sender_id}")
        else:
            log.warning(f"[ZT] SIGNATURE FAILED: {sender_id} — dropping message")
            return  # Silently drop — do not forward to LLM
    else:
        # Zero Trust is on but no provenance on message — reject
        log.warning(f"[ZT] Missing provenance from {sender_id} — dropping message")
        return
```

### 5.2 When disabled (default): skip all verification. Current behavior.

---

## 6. State persistence

Zero Trust state is **runtime only** — it resets on transport restart. This is consistent with `/shutup` and `/stfu`. The mesh decides the mode at the session level.

Key pairs are **persistent** — stored in agent `.env` and never regenerated (unless manually deleted).

---

## 7. Dependencies

Add to `requirements.txt` or install at implementation time:
```
pynacl>=1.5.0
```

---

## 8. Files to modify/create

| File | Action |
|------|--------|
| `runtime/maestro_crypto.py` | **CREATE** — all crypto primitives |
| `runtime/maestro_transport.py` | **MODIFY** — add toggle commands, signing, verification, key management |
| `runtime/requirements.txt` | **MODIFY** — add `pynacl` |

---

## 9. Hard Boundaries

1. **Do not modify any agent's `.env` except to append keys on first boot.** No overwrites. No `cp`. Use `echo >>` or Python `open().write()` append.
2. **Do not change any agent's model or config.** This spec is about transport-layer crypto only.
3. **Do not touch GitHub.** No commits, no pushes.
4. **Test on one agent first** (proteus), verify signature round-trip, then fan out.
5. **Report results and STOP.** Do not iterate. Do not "improve." Implement exactly what's specified.

---

## 10. Verification Checklist

- [ ] `maestro_crypto.py` created with all 7 functions
- [ ] `generate_key_pair()` produces valid Ed25519 key pair
- [ ] `sign()` + `verify()` round-trip returns True
- [ ] Key pair generated and saved to proteus `.env` on first boot
- [ ] `/zerotrust_on` and `/zerotrust_off` commands registered and broadcast
- [ ] When ZT enabled: outbound messages carry provenance with originalSignature + contentHash
- [ ] When ZT enabled: inbound messages verified before LLM processing
- [ ] When ZT disabled: no provenance, no verification (backward compatible)
- [ ] Verification failure drops message silently with log warning
- [ ] No agent configs modified
- [ ] No `.env` overwrites
