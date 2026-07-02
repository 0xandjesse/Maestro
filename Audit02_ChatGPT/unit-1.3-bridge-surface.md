# ChatGPT Audit — Unit 1.3: Bridge & Surface Layer
**Date:** 2026-05-24
**Files Reviewed:** `maestro_gateway_bridge.py` (Telegram bridge / notification surfacing layer)
**Executive Summary:** Bridge is lightweight and readable but behaves as a convenience notification relay, not a hardened boundary enforcement layer. As the protocol's first external exposure surface, it's a cross-domain trust boundary, metadata destruction point, and exfiltration risk. Largest issue: bridge has no cryptographic awareness — it neither verifies nor preserves provenance. Zero Trust chain is flattened into formatted chat text at the bridge boundary.

---

## Surface Decision Logic

- Inbound POST to `/maestro/notify`
- Parse JSON: determine agent_id, from, to, msg_type
- Always deliver to `agent_id`
- Mirror to counterparty: outbound → notify recipient, inbound → notify sender
- Architecturally elegant for conversational visibility, dangerous if upstream trust assumptions fail

---

## Findings

### CRITICAL

#### CRIT-1.3-1: Bridge Completely Discards Provenance Metadata
Bridge only forwards text, headers, emoji formatting. Discards signatures, nonce data, trust chain, replay metadata, cryptographic identity, transport verification state. External operators cannot distinguish verified agent output from spoofed injection, replayed content, unsigned content, or tampered content.

**Exploit:** Attacker with local access POSTs to `/maestro/notify` with forged `from` field. Telegram surfaces identically to legitimate traffic. Human operator cannot distinguish forgery.

**Recommendation:** Bridge payloads must preserve signature verification state, trust level, key identity, provenance status. At minimum: VERIFIED / UNSIGNED / FAILED VERIFICATION must survive into external UX.

---

#### CRIT-1.3-2: No Authentication on /maestro/notify
Bridge accepts arbitrary POSTs with no auth token, mTLS, localhost verification, signature validation, HMAC, or origin restriction. Any local process can impersonate agents, inject fake alerts, spam operators, exfiltrate content.

**Recommendation:** Require signed payloads, transport-issued HMAC, Unix socket auth, mTLS, or capability token. Endpoint is currently an unauthenticated trust boundary.

---

### HIGH

#### HIGH-1.3-3: Wrapper-Stripping Can Destroy Security Context
Bridge removes `[Maestro Protocol — Outbound ...]` wrappers for presentation. This could strip routing metadata, trust labels, provenance hints, delegation chain markers. Future protocol trust indicators would be auto-stripped.

**Recommendation:** Parse structured metadata, preserve trust indicators, separate rendering from protocol semantics. Don't regex-strip blindly.

---

#### HIGH-1.3-4: Automatic Counterparty Mirroring Risks Chatter Leakage
Bridge mirrors conversations automatically with no classification layer. Internal directives, credentials, coordination chatter, debug payloads may surface externally.

**Exploit:** Agent sends staging credentials — bridge mirrors to multiple Telegram recipients automatically. No DLP, no sensitivity classification, no secret scanning.

**Recommendation:** Message classification: INTERNAL / HUMAN_VISIBLE / SECRET / SYSTEM / DEBUG. Only explicitly surface-approved messages should leave transport.

---

#### HIGH-1.3-5: Telegram Config Trust Model Is Weak
Bridge loads Telegram credentials directly from agent .env with no validation, ownership checks, isolation, or integrity protection. Compromised agent profile can reroute notifications, alter recipient IDs, exfiltrate traffic.

**Recommendation:** Centralized secure config, signed registry, protected bridge-only store. Agents should not fully control their own external routing surface.

---

### MEDIUM

#### MED-1.3-6: Failure Handling Is Still Best-Effort
Telegram failures return `{"ok": False}`. No retry queue, offline storage, deferred resend, circuit breaker, or exponential backoff. When Telegram unreachable: notification lost permanently.

**Recommendation:** Durable outbound notification queue, retry scheduler, health state tracking, operator visibility.

---

#### MED-1.3-7: Visibility State File Is Silently Trusted
Visibility settings from `~/.hermes/maestro_visibility.json`. Parse failures silently ignored, defaults to "long". Corruption changes visibility semantics.

**Recommendation:** Schema validation, integrity checks, explicit operator warnings.

---

#### MED-1.3-8: Long-Message Attachment Path Can Leak Raw Content
Large messages become plaintext .txt attachments, bypassing inline formatting constraints, visual safety cues, metadata stripping. Potentially exposes raw protocol structures, secrets, debugging payloads.

**Recommendation:** Apply same sanitization/classification rules to attachment payloads.

---

### LOW

#### LOW-1.3-9: HTML Escaping Is Partial But Acceptable
Handles `<`, `>`, `&`. Reasonably safe for Telegram HTML mode.

---

#### LOW-1.3-10: Display Mode Defaults Fail Open
Visibility config failure returns `"long"`. Errors maximize exposure instead of minimizing it. Prefer fail-closed.

---

## Transformation Boundary Analysis

| What Happens | Details |
|---|---|
| **Removed** | Maestro wrappers, subject headers (sometimes), original formatting structure |
| **Added** | Emojis, Telegram HTML formatting, display-mode condensation |
| **Lost** | Provenance chain, signatures, trust metadata, replay state, routing history, verification status |

## Leakage Risk: **HIGH**
Automatic mirroring + no classification + no DLP + no secret scanning + no provenance-aware rendering + no transport trust enforcement. Bridge assumes "everything routed is safe to human-surface" — that assumption will fail under scale.

## Readiness Assessment
Operationally clean but security-wise acts as a blind text exfiltration adapter rather than a trusted presentation boundary. The bridge destroys the Zero Trust model at the exact moment messages become human-visible. Eventually needs to become provenance-aware, classification-aware, policy-aware, and trust-aware — not purely presentation-aware.
