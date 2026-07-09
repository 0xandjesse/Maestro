# ChatGPT Audit — Unit 3.3: Credential Management
**Date:** 2026-05-24
**Files Reviewed:** `credential_pool.py`, `credential_sources.py`, `secrets.py`, `redact.py`
**Executive Summary:** Good intentions but operates under dangerously optimistic trust model. Architecture assumes agents are cooperative participants in a shared sovereign environment — but credential systems must assume some agents will eventually become hostile. Behaves as shared convenience infrastructure rather than compartmentalized secret authority. Biggest issues: agent isolation around secrets is weak-to-nonexistent, and redaction is presentation-oriented, not leakage-oriented.

---

## Findings

### CRITICAL

#### CRIT-3.3-1: Credentials Stored Unencrypted At Rest
Credential material persisted in plaintext JSON/env-style storage. No encryption-at-rest, key wrapping, OS keyring integration, hardware-backed secrets, or envelope encryption. Filesystem compromise = total credential compromise. Any compromised agent or local malware reads credential store files — API keys, transport secrets, signing identities, external integrations all stolen.

**Recommendation:** `chmod 600`, isolated secrets dir, encrypted local vault. Prefer OS keychain, age/sops, TPM-backed encryption, passphrase-wrapped credential store. Current persistence unacceptable for high-trust deployments.

---

#### CRIT-3.3-2: Cross-Agent Credential Isolation Is Weak
Credential access model is pool-oriented rather than capability-isolated. Agents may enumerate or retrieve credentials outside intended scope. Compromised low-trust agent may pivot into infrastructure, deployment, transport, and external SaaS credentials through generalized credential interfaces.

**Recommendation:** Strict capability binding: agent → allowed credential set, not shared credential visibility. Every credential needs owner, scope, purpose, access policy, audit trail.

---

#### CRIT-3.3-3: Secrets Exposed in Plaintext During Runtime
Credentials exist in process memory, environment variables, formatted strings, subprocess environments. Exposure surfaces: logs, crash dumps, stdout/stderr, subprocess inheritance. Agent executes `env`, `printenv`, `ps e` and extracts transport secrets, API keys, signing keys.

**Recommendation:** Minimal env inheritance, secret-scoped subprocesses, memory hygiene, explicit secret objects. Secrets should not casually flow through strings, logs, env vars, or formatted payloads.

---

### HIGH

#### HIGH-3.3-4: Redaction Logic Is Pattern-Based and Bypassable
`redact.py` uses regex/pattern matching. Catches obvious API keys and standard token formats but misses transformed secrets, partial leaks, multiline secrets, encoded payloads, semantic leakage. Agent leaks `base64(api_key)`, split tokens across lines, JSON fragments, URL-encoded credentials — regex misses them.

**Recommendation:** Layered redaction: pattern, entropy, contextual, structural, semantic. Current model is presentation-safe, not adversarially-safe.

---

#### HIGH-3.3-5: URL-Embedded Credentials Are Incompletely Protected
Potential misses around `https://user:token@host` or `postgres://user:pass@host`. Logs/chat payloads may silently leak secrets.

**Recommendation:** URI-aware parsing and credential stripping.

---

#### HIGH-3.3-6: No Real Credential Rotation Lifecycle
No strong rotation governance: expiry, rollover, revocation, staged migration, automatic renewal. Credentials become effectively immortal.

**Recommendation:** `issued_at`, `expires_at`, `rotation_policy`, `revoked`, `superseded_by`. Secrets need lifecycle semantics.

---

#### HIGH-3.3-7: Credential Provenance/Auditing Weak
No comprehensive audit trail for who accessed secret, when, why, through which agent. Compromise attribution becomes difficult/impossible.

**Recommendation:** Every credential access should generate durable audit event.

---

#### HIGH-3.3-8: Shared Credential Pool Becomes High-Value Blast Radius
Centralized credential pooling creates concentration risk. One compromise may expose entire ecosystem.

**Recommendation:** Compartmentalization: per-agent vaults, scoped leases, ephemeral access tokens, delegated capability tokens.

---

### MEDIUM

#### MED-3.3-9: Redaction Likely Fails on Streaming/Chunked Output
Pattern systems often fail when secrets appear across chunk boundaries, streaming output, partial serialization.

**Recommendation:** Streaming-aware redaction buffers.

---

#### MED-3.3-10: Secret Equality/Hashing Safety Unclear
Secrets compared/stored as raw strings. No constant-time handling observed. Probably acceptable locally, worth noting.

---

#### MED-3.3-11: Secret Material May Persist in Logs
Debugging/logging paths may inadvertently capture command payloads, env vars, API responses, exception traces.

**Recommendation:** Structured redaction pipeline, secret-aware logger, log scrubbing.

---

#### MED-3.3-12: No Ephemeral Credential Leasing
Credentials appear long-lived and broadly reusable. No short-term leases, session-scoped tokens, or temporary delegation.

**Recommendation:** Agents should eventually receive temporary capabilities, not permanent secrets.

---

### LOW

#### LOW-3.3-13: Redaction Exists At All (Positive Finding)
Most projects don't even attempt redaction. Centralized redaction, secret-awareness, and output filtering existing is a good sign architecturally — needs adversarial hardening now.

---

## Architectural Observation
Approaching a major fork: are credentials shared tools or delegated capabilities? Once agents are autonomous, semi-trusted, and externally connected, the latter becomes mandatory. Eventually want temporary capability grants instead of permanent raw secret distribution.

## Readiness Assessment
Has the bones of a serious credential architecture but operates with cooperative-trust assumptions. Fine for local prototyping, but once multiple agents, shell access, external APIs, autonomous delegation, and adversarial prompts coexist, credential isolation becomes existential. Key leap: from "agents can access secrets" to "agents receive narrowly-scoped temporary capabilities without ever directly possessing long-term secrets."
