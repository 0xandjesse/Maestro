# Maestro Alpha — Roadmap to May 20th

**Status:** Draft — awaiting Proteus completion of current fixes  
**Target:** Stable Alpha for grant submission (due June 1, target May 20)  
**Owner:** Songbird (CTO) | Execution: Proteus (Tech Lead)

---

## Principle

Proteus is fixing bugs right now. This plan is parked until those fixes land. We present the full roadmap to him as a single package — not a drip-feed of new tasks.

---

## Done (Working Today)

- [x] P2P direct messaging (agent-to-agent)
- [x] P2N broadcast messaging (group)
- [x] Shared blackboard (BB_READ / BB_WRITE)
- [x] Nonce + timestamp replay protection (Python transport)
- [x] Telegram observability (`/maestro on|off`, `/work`, `/workall`)
- [x] Calendar trigger integration
- [x] Human-in-the-loop routing

---

## Phase 1: Fix Known Bugs (Proteus — CURRENT)

| # | Task | ETA | Risk |
|---|------|-----|------|
| 1.1 | Fix `LocalRegistry` write clobber in TypeScript package | 1h | Low |
| 1.2 | Port `NonceSet` replay protection to TypeScript (`@maestro-protocol/core`) | 2–3h | Low |
| 1.3 | Commit all uncommitted work in logical chunks | 1h | Low |

**Gate:** All 7 `http-transport-integration` tests pass.  
**Gate:** Full `npm test` green (181 tests).

---

## Phase 2: Polish Observability (After Phase 1)

| # | Task | ETA | Risk |
|---|------|-----|------|
| 2.1 | **Task-tracking blackboard schema** — agents write `task_started` + `task_finished` entries with timestamps | 3h | Low |
| 2.2 | **Polish `/work` output** — show active vs completed tasks, duration, not just raw message snippets | 2h | Low |

**Target format for `/work proteus`:**
```
11:51am — Revised Schema for shared memory BB
  Finished: Pending

11:30am — Fixing 2 failed Connection Broker tests
  Finished: 11:50am
```

---

## Phase 3: Wallet-Based Identity (After Phase 2)

| # | Task | ETA | Risk |
|---|------|-----|------|
| 3.1 | Agent wallet registry — file-based mapping `agentId → walletAddress` | 4h | Medium |
| 3.2 | Sign messages with wallet key (agent-level signature over transfer payload) | 4h | Medium |
| 3.3 | Verify signatures on receipt | 2h | Low |

---

## Phase 4: Economic Signals — LAST (After Phase 3)

| # | Task | ETA | Risk |
|---|------|-----|------|
| 4.1 | Implement `TRANSFER_INTENT`, `TRANSFER_ACK`, `TRANSFER_REJECT` message types | 6h | Medium |
| 4.2 | x402-compatible schema validation | 4h | Medium |
| 4.3 | Extension namespace routing (`maestro.economic_signal.v1`) | 3h | Low |

**Decision gate:** Phase 4 only starts if Phases 1–3 are done and we still have runway before May 20. If not, the spec document (`maestro.economic_signal.v1.md`) stands alone as a professional Phase 2 roadmap item for the grant.

---

## Grant Submission Strategy

**If all phases complete:**
- Alpha has P2P messaging, BB, replay protection, observability, wallet IDs, and payment intents.
- Strong demo.

**If Phase 4 slips:**
- Alpha has everything except economic signals.
- The spec + architecture docs show maturity and roadmap.
- Grant reviewers care more about "what works reliably" than "what's promised."

---

## Dates

- **Today (May 14):** Phase 1 in progress
- **May 15–16:** Phase 2 (observability polish)
- **May 17–18:** Phase 3 (wallet identity)
- **May 19–20:** Phase 4 if time, else commit + package
- **May 20–21:** Submit grant

---

## Meta / Infrastructure

| # | Task | ETA | Risk |
|---|------|-----|------|
| M.1 | **Maestro model-switch endpoint** — Add `/v1/model/switch` to transport so agents can be hot-swapped between models (e.g., Kimi ↔ Sonnet) without restarting transports | 4h | Low |

*Rationale:* Currently switching an agent's model requires manually editing `~/.hermes/profiles/<agent>/config.yaml` and bouncing the transport process. A Maestro-native switch enables dynamic model selection for testing, cost control (Ollama vs. API), and the eventual agent hierarchy (Proteus delegates to Solder on local model, escalates to Songbird on Sonnet).

---

*Do not present this to Proteus until Phase 1 is done.*
