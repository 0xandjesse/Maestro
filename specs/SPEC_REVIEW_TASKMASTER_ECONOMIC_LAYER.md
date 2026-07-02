# TaskMaster Economic Layer — Spec Review
**Reviewer:** Proteus
**Date:** 2026-05-27
**Spec version:** Draft v2 (Lex's four gaps addressed)
**Verdict:** Solid. No architectural objections. 5 flags — 1 critical, 1 medium, 3 low/informational.

---

## FLAG 1 — CRITICAL: Ed25519 keys do not exist yet

Spec §2.11 claims "The keys already exist." Spec §4 Phase 0 dependencies lists Zero Trust provenance as "SPEC WRITTEN — not implemented."

Live verification confirms:
- Zero agents have `MAESTRO_PRIVATE_KEY` in their `.env` files
- Only mnemosyne has a `publicKey` field in `~/.maestro/registry.json`
- No `maestro_crypto.py` exists anywhere on disk

Phase 0 needs an explicit key-generation step before the transport fix ships. Token signatures (Phase 2) and signature verification both depend on this. Without it, Phase 2 is dead on arrival.

**Suggested addition to Phase 0:**
> Generate Ed25519 keypairs for all 9 agents and register public keys in `registry.json`

---

## FLAG 2 — MEDIUM: Registry schema mismatch with validation code

Appendix B pseudocode calls `registry.get_public_key(token["delegator_id"])` — an object method that doesn't exist. The live registry (`~/.maestro/registry.json`) is a flat JSON array. The validation code needs either:
- A `Registry` wrapper class that provides `get_public_key()` 
- Or a simple array search inline

Implementation detail, but the pseudocode implies an interface that hasn't been built.

---

## FLAG 3 — LOW: Scorched-earth sweep timing risk

§1.2.1: One-time sweep deletes all BB entries older than 24h. Any agent with pending work older than 24h (e.g., blocked tasks) loses those entries silently.

**Operational note (not a spec change):** Before executing the sweep, notify all agents so they can re-register active long-running tasks.

---

## FLAG 4 — LOW: Cross-venue heartbeat undefined

§2.7 heartbeat liveness assumes local P2P messaging. No mechanism defined for heartbeat messages crossing venue boundaries. Probably a Phase 4 concern, but the heartbeat protocol shouldn't bake in assumptions that break later. Consider abstracting the heartbeat channel so it can be swapped for cross-venue transport in Phase 4 without changing the token schema.

---

## FLAG 5 — INFORMATIONAL: Key deployment is the riskiest single operation

Hard boundary #1 allows `.env` modification "on first boot" — but we're doing it on ALL agents simultaneously. Risks:
- One mangled key → token validation silently fails for that agent
- Scorecard system can't distinguish "agent didn't sign" from "agent's key is corrupt"
- No rollback mechanism exists

Mitigation: verify each keypair after deployment (sign a test message, verify it with the public key in registry) before moving to Phase 1.

---

## What's Correct

- Verification failure type classification (verification_failure vs race_condition vs timeout vs config_conflict) is well designed
- Confused deputy prevention via scope intersection is mathematically sound
- Heartbeat → auto-revoke for orphan prevention is elegant
- BB auto-cleanup on checklist completion closes a real gap
- Scorecard writable only by checklist tool (guarded at bb_write level) prevents self-repair
- Transport notification on verification failure ensures failures propagate instead of being silently swallowed
- Human-authorized token bypass for Jesse's key preserves human sovereignty correctly

No architectural objections. Ship it.
