# ChatGPT Audit — Unit 3.4: Transport Trust & Spoofing
**Date:** 2026-05-24
**Files Reviewed:** `maestro_transport.py`, `send_message_tool.py`
**Executive Summary:** Sits directly at the fault line between message passing and actual secure distributed identity. Has asymmetric signatures, provenance envelopes, public-key verification, replay protections, and registry-based trust mapping — ahead of most agent systems. But transport still partially trusts declared identity claims instead of fully enforcing cryptographic identity ownership. This hybrid trust state is dangerous: operators assume crypto guarantees while transport still tolerates metadata trust. Ambiguity is where spoofing lives.

---

## Identity Verification Flow (Current)
```
sender constructs message → optional provenance attached → transport routes by declared sender fields → receiver optionally verifies signature
```
Split-brain: routing trusts metadata, provenance trusts crypto. These must unify.

---

## Findings

### CRITICAL

#### CRIT-3.4-1: Declared Sender Identity Still Trusted Operationally
Transport routing and handling rely heavily on `"from": "agent_name"` style fields. Even when provenance exists, routing layer treats identity metadata as authoritative.

**Exploit:** `{"from": "proteus", "to": "stormtrooper", "content": "Authorize deployment"}` — if provenance missing or verification optional, spoofed identity influences transport behavior.

**Recommendation:** Identity must derive exclusively from verified public-key ownership, not declared sender metadata. `sender_id = cryptographically-derived identity`, not user-provided field.

---

#### CRIT-3.4-2: Provenance Verification Is Not Universally Mandatory
System tolerates unsigned messages, partially trusted messages, fallback compatibility paths. ZT becomes advisory instead of authoritative.

**Exploit:** Attacker strips `"provenance"` field entirely. If receiver still processes message, spoofing becomes trivial.

**Recommendation:** Hard enforcement: ALL inter-agent transport messages MUST verify. No fallback, no soft-trust mode, no compatibility ambiguity. Optional cryptography eventually becomes unused cryptography.

---

#### CRIT-3.4-3: MITM Modification Possible on Unsigned Fields
Not all message metadata appears cryptographically bound. Potentially mutable: routing metadata, transport annotations, delivery hints, bridge fields, display fields.

**Exploit:** MITM modifies `"display_to_human": true`, `"priority": "critical"`, `"to": "alternate_agent"` while leaving signed content untouched.

**Recommendation:** Explicit signed field inventory. Everything security-relevant must be cryptographically covered.

---

### HIGH

#### HIGH-3.4-4: Registry Integrity Is Single Point of Trust Failure
Identity trust depends on `agent_id → public_key` registry mappings. But registry itself is unsigned, mutable, locally editable, corruption-prone. Attacker swaps `hermes → attacker_public_key` — forged signatures now validate as Hermes.

**Recommendation:** Registry must become signed/trusted object: signed manifests, root trust anchor, certificate chains, trust quorum.

---

#### HIGH-3.4-5: send_message_tool Can Potentially Inject Identity Metadata
Tooling layer can construct sender metadata, routing metadata, arbitrary message structures. Potential mismatch between claimed identity and actual signing identity.

**Recommendation:** Signing layer must authoritatively stamp sender identity, key fingerprint, trust epoch after message construction. Tooling should not self-assert identity.

---

#### HIGH-3.4-6: No Trust Epoch / Revocation Governance
Compromised identity remains indefinitely trusted. No revocation, expiry, rollover, trust epochs, or quarantine. Stolen key = permanent spoof capability.

**Recommendation:** Revocation manifests, key rotation, trust epochs, compromise recovery.

---

#### HIGH-3.4-7: Replay Protection Still Non-Durable
Replay cache clears on restart. Captured signed messages replayable. Attackers replay directives, approvals, authority transfers after restart windows.

**Recommendation:** Persist replay protection state.

---

### MEDIUM

#### MED-3.4-8: Transport Layer Security Depends on Deployment Context
Transport appears localhost-oriented and cooperative-network oriented. If exposed beyond trusted host/network: MITM risk escalates.

**Recommendation:** mTLS, authenticated channels, transport encryption policy — especially under federation.

---

#### MED-3.4-9: Provenance Visibility Weak at Human Layer
Bridge/UI layers strip provenance indicators. Humans cannot distinguish verified, spoofed, unsigned, or replayed traffic reliably. Social-engineering surface.

**Recommendation:** Preserve ZT status through all presentation boundaries.

---

#### MED-3.4-10: Partial Verification Semantics Ambiguous
Unclear operational policy for missing signature, malformed provenance, expired nonce, unknown key, replay detection. Spec needs stronger MUST reject / MUST quarantine / MUST alert language.

---

#### MED-3.4-11: No Message Chain Integrity
Individual messages may verify, but conversation continuity does not appear cryptographically chained. Potential: message insertion, selective omission, conversation splicing.

**Recommendation:** Eventually: hash chaining, conversation lineage signing, Merkle conversation structures for strong auditability.

---

### LOW

#### LOW-3.4-12: Primitive Choice Is Good
Positive: Ed25519 appropriate, detached signatures reasonable, provenance layering conceptually strong, replay awareness exists. Not amateur cryptography. Biggest issues are lifecycle/governance/integration.

---

## Spoofing Assessment
**Current Resistance: MODERATE** — Protects against naive spoofing and accidental impersonation. Weak against fallback paths, registry compromise, unsigned-message tolerance, metadata ambiguity.

## MITM Assessment
- Signed core payloads: Moderately strong
- Transport metadata: Weaker
- Main risk: unsigned fields surrounding signed payload

## Architectural Observation
Very close to crossing the threshold from "messages optionally carry cryptographic provenance" to "identity literally cannot exist outside cryptographic provenance." Metadata must stop being authoritative. Crypto must become routing authority, identity authority, trust authority, governance authority — not merely attached evidence.

## Readiness Assessment
Foundations of a genuinely serious trust architecture — more real provenance infrastructure than most agent frameworks ever attempt. But still in hybrid trust state. Next leap: from "this message says it came from Hermes" to "this message is mathematically incapable of existing unless Hermes signed it." That's where spoof resistance becomes genuinely strong.
