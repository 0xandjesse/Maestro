# ChatGPT Audit — Unit 1.2: Transport Initialization & Key Lifecycle
**Date:** 2026-05-24
**Files Reviewed:** `maestro_transport.py` (init, key generation, ZT lifecycle, registry persistence, replay caches)
**Executive Summary:** Zero Trust lifecycle is functional but immature. Has asymmetric crypto, clean bootstrap, replay protection — but lacks identity governance, continuity guarantees, compromise recovery, durable anti-replay, and hardened persistence. Currently "developer-local cryptographic identity" rather than "production-grade sovereign trust infrastructure." Biggest issue: identity continuity is fragile — damaged .env can permanently alter node identity without coordinated recovery.

---

## Findings

### CRITICAL

#### CRIT-1.2-1: Private Keys Stored in Plaintext .env
Private keys persisted to `~/.hermes/.env` via append. No encryption, file permission hardening, OS keychain integration, or passphrase protection. Any local malware, compromised agent, backup leak, or shell history exposure compromises identity permanently.

**Recommendation:** `chmod 600` minimum. Dedicated secrets directory with encrypted-at-rest storage. Prefer OS keyring, age/sops, TPM/HSM, passphrase-derived key wrapping. Never store raw signing keys in append-only dotenv files.

---

#### CRIT-1.2-2: No Key Rotation Mechanism
No mechanism for rotation, expiry, revocation, rollover, or migration. Keys are effectively eternal. Compromised identity remains valid forever with no trust graph recovery path.

**Recommendation:** Implement key IDs, trust epochs, rotation schedule, revocation lists, dual-sign rollover window, signed identity manifests. Identity should equal active keyset under a trust epoch, not a single immortal keypair.

---

### HIGH

#### HIGH-1.2-3: Silent Identity Regeneration After State Damage
If keys absent from .env, transport silently generates new identity with no operator confirmation. Filesystem corruption = identity mutation. Existing trust relationships and provenance chain broken.

**Recommendation:** Differentiate first boot vs identity loss. Missing keys after prior initialization should trigger startup failure, quarantine mode, and explicit recovery workflow.

---

#### HIGH-1.2-4: .env Append Semantics Are Corruptible
Keys appended to .env with `'a'` mode. Repeated generations create duplicate/stale keys and malformed state. Parser walks lines sequentially — last matching line wins implicitly.

**Recommendation:** Atomic rewrite, canonical config serialization, integrity checks, explicit versioned identity file. Never append cryptographic identity material.

---

#### HIGH-1.2-5: Replay Protection State Is Non-Durable
`SeenSet` and `NonceSet` are entirely in-memory. Transport restart clears replay history. Attacker can capture valid signed messages, wait for restart, and replay.

**Recommendation:** Persist replay windows via durable nonce ledger, rolling replay journal, monotonic sequence tracking. Critical for directives, authority delegation, financial/tool operations.

---

### MEDIUM

#### MED-1.2-6: Startup Bootstrap Is Operationally Fragile
Bootstrap assumes `~/.hermes/.env` exists and writable. No validation for directory ownership, symlink attacks, readonly FS, or concurrent writes.

**Recommendation:** Atomic temp-file writes, fsync, symlink rejection, permission validation, bootstrap diagnostics.

---

#### MED-1.2-7: Replay Drift Window May Be Operationally Brittle
Nonce drift window fixed at `max_drift_sec=30`. VM pause, clock skew, suspend/resume, overloaded queues can exceed this naturally.

**Recommendation:** Monotonic clocks where possible, NTP health checks, configurable trust windows, adaptive skew tolerance.

---

#### MED-1.2-8: Registry Persistence Has Weak Corruption Handling
Registry load failures caught with `except Exception: data = []`. Corruption silently resets registry state — agent registry, public key mappings, routing continuity lost with transport continuing to operate.

**Recommendation:** Corrupt registry should fail closed, quarantine file, preserve backup snapshot, emit high-severity alert.

---

### LOW

#### LOW-1.2-9: Key Availability Depends on Runtime Environment Mutation
Keys injected into `os.environ`, increasing accidental exposure surface via subprocess inheritance, debug dumps, crash reporters.

**Recommendation:** In-memory secret manager objects instead of environment mutation.

---

## Key Rotation Assessment
Effectively unsupported — one static keypair, no rollover, no revocation, no trust epochs.

## Bootstrap Assessment
Clean bootstrap works but too permissive. First boot vs identity loss are indistinguishable.

## Corruptibility
High — .env and registry JSON especially vulnerable: append-based persistence, permissive exception handling, no integrity checks/signatures/backups.

## Readiness Assessment
Zero Trust direction is promising, but lifecycle model is prototype cryptography. Missing a durable trust lifecycle.
