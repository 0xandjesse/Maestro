# SPEC_MAESTRO_DELEGATION_TOKENS.md — Archived 2026-06-03

**Superseded by:** `SPEC_MAESTRO_TOKEN_PRIMITIVE.md`

**Archived by:** Songbird (Lexicon directive CL-lexicon-6212bf10, Workstream A)

**Reason:** This spec embedded `scope`, `actions`, `resources`, `venues`, `allow_delegation`, `heartbeat_required`, and `revocation_endpoint` into the token schema — violating the ADR principle that these are payload-level concerns. The ADR (Jesse, 2026-05-29) established that the Maestro protocol provides primitives, Venues provide semantics, and agents provide interpretation.

**Migration path for any implementation based on this spec:**
1. Move `scope` → `payload.scope` (Venue-defined convention)
2. Drop `heartbeat_required` and `revocation_endpoint` from protocol fields
3. Drop `delegation_chain` from protocol fields (chain tracking is a payload-level convention)
4. Rename `delegator_id` → `issuer_id`, `delegate_id` → `bearer_id` (generalized naming)

**New canonical location:** `specs/SPEC_MAESTRO_TOKEN_PRIMITIVE.md`
**Implementation:** `runtime/maestro/tokens.py`
**Tests:** `tests/test_token_primitive.py`
