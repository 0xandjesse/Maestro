# ChatGPT Audit — Unit 3.1: Zero-Trust Provenance
**Date:** 2026-05-24
**Files Reviewed:** `maestro_crypto.py`, `maestro_transport.py` (ZT sections), `SPEC_ZEROTRUST_PROVENANCE.md`
**Executive Summary:** Strongest subsystem reviewed so far. Actually implemented asymmetric signing, provenance envelopes, replay windows, nonce validation, detached verification flow, and canonicalized payload construction — real security thinking, not "trust me bro + UUIDs." But missing durable replay resistance, trust revocation, downgrade resistance, canonical serialization guarantees, and identity continuity governance. The provenance model is cryptographically sound locally but not yet operationally sovereign.

---

## Cryptographic Primitives

| Layer | Implementation | Assessment |
|---|---|---|
| Signing | `nacl.signing.SigningKey` / `VerifyKey` | Ed25519 — modern, strong, appropriate |
| Encoding | Base64 + JSON serialization | Standard and acceptable |
| Nonce/Replay | Nonce tracking + timestamp drift windows | Good direction |

## Provenance Flow
```
message → canonical payload assembly → sign(payload, private_key) → attach provenance envelope → recipient verifies against public key
```
Fundamentally correct architecture.

---

## Findings

### CRITICAL

#### CRIT-3.1-1: Replay Protection Is Non-Durable
Replay state exists only in memory. Restart clears nonce history, seen message cache, replay windows. Previously valid signed messages become replayable after restart.

**Exploit:** Attacker captures valid signed directive, waits for transport restart, replays — replay cache no longer remembers nonce. Directive executes again. Catastrophic once agents can execute shell commands, delegate authority, modify credentials, or trigger automation.

**Recommendation:** Durable nonce ledger, sequence numbers, rolling replay journal, signed monotonic counters. For sovereign systems: non-durable replay protection is not sufficient.

---

#### CRIT-3.1-2: No Key Revocation Mechanism
No revocation list, trust epoch, key invalidation, compromised-key quarantine, or trust rollover. Compromised key remains permanently trusted.

**Exploit:** Attacker steals MAESTRO_PRIVATE_KEY — can forge provenance forever, impersonate agents indefinitely, replay authority permanently. Nothing in protocol can revoke trust.

**Recommendation:** Key IDs, trust epochs, signed revocation manifests, revocation propagation, dual-sign rollover windows. Biggest missing governance piece in the ZT model.

---

### HIGH

#### HIGH-3.1-3: Canonical Serialization Is Not Strongly Defined
Signing correctness depends on deterministic payload serialization, but spec leaves ambiguity around field ordering, whitespace normalization, optional fields, Unicode normalization, nested structure canonicalization. Different implementations may sign different byte streams — classic canonicalization failure class.

**Recommendation:** Spec must explicitly define canonical JSON encoding, UTF-8 normalization, sorted keys, exact field inclusion rules, newline handling.

---

#### HIGH-3.1-4: Downgrade Resistance Is Weak
Unsigned or partially signed messages can still exist operationally. No strict enforcement requiring all inter-agent messages MUST verify. Attackers may coerce fallback into unsigned mode. `"provenance": null` — if receiver tolerates, ZT becomes optional. Optional security eventually becomes unused security.

**Recommendation:** Explicit STRICT_ZT_REQUIRED policy with hard rejection, audit events, no insecure fallback.

---

#### HIGH-3.1-5: Provenance Can Be Stripped at Presentation Boundaries
Bridge layer strips provenance visibility entirely (from Unit 1.3). Human operators cannot visually distinguish verified, unsigned, tampered, or replayed messages. Human trust layer becomes spoofable.

**Recommendation:** ZT status must survive all presentation boundaries.

---

#### HIGH-3.1-6: Identity Binding Is Registry-Trust-Based
Verification depends on registry mapping `agent_id → public_key`. Registry integrity becomes critical trust anchor — but registry is unsigned, mutable, corruption-prone, locally editable. Attacker swaps public key mapping — forged signatures now validate under hijacked identity.

**Recommendation:** Registry itself must become signed/trusted object — signed identity manifests, certificate chains, trust anchors.

---

### MEDIUM

#### MED-3.1-7: Timestamp Drift Window Operationally Fragile
`max_drift_sec=30` potentially brittle under VM pause, suspend/resume, overloaded queues, clock skew.

**Recommendation:** Configurable skew policy, monotonic sequence support, NTP health awareness.

---

#### MED-3.1-8: Spec Does Not Fully Define Failure Semantics
Spec explains signing and verification but not failed verification behavior, partial trust behavior, quarantine policy, revocation propagation, or replay incident handling.

**Recommendation:** Explicit MUST reject, MUST quarantine, MUST alert behavior definitions.

---

#### MED-3.1-9: No Forward Secrecy
Current signatures are static-key based. Compromised long-term key enables retrospective verification forgery and future impersonation. May be acceptable depending on threat model.

**Recommendation:** Eventually consider session keys, rotating delegation keys, ephemeral signing contexts.

---

#### MED-3.1-10: Nonce Scope Appears Local Rather Than Global
Potential replay edge: if nonce uniqueness scoped narrowly, distributed systems may allow partial replay collisions. Spec needs explicit nonce namespace definition.

---

### LOW

#### LOW-3.1-11: Primitive Selection Is Good
Positive findings: Ed25519 appropriate, PyNaCl appropriate, detached signing model reasonable, timestamp+nonce replay strategy sensible. No obvious catastrophic crypto misuse found — genuinely uncommon in early systems.

---

## Spec Completeness Assessment
Strong prototype spec but not yet implementation-complete sovereign protocol spec. Missing: canonicalization, revocation, governance semantics, failure semantics, trust lifecycle, interoperability guarantees.

## Readiness Assessment
Much more serious than most early agent security implementations. Thought clearly about provenance, replay, detached verification, trust boundaries, and signing semantics — ahead of a huge percentage of AI orchestration projects. But treats cryptography as proof of origin, not yet a fully-governed trust lifecycle. Next leap: from "this message was signed" to "this identity remains trustworthy over time, across compromise, rotation, federation, and adversarial recovery events."
