# ADR-004b: Relay Architecture — Tokenized Pipeline Routing

**Status:** Superseded by ADR-006 (Modular Relay Architecture) — the linear relay is an implementation phase of the graph model, not a separate architectural decision
**Date:** 2026-07-04
**Author:** Lexicon (COO)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)

---

## Context

The Local Org's newsletter pipeline was tested on 2026-07-03. The test failed. Agents did not process directives through the mesh. No tokens passed between agents. No gates were evaluated. The pipeline "worked" only because Proteus manually hit REST endpoints to simulate state transitions, and Mnemosyne told agents to read each other's log files.

The relay modules (`gate_engine.py`, `task_lifecycle.py`, `pipeline_orchestrator.py`) exist on disk. They are well-written. Nothing calls them in the transport's message handler. The transport receives a directive, spawns a background LLM task, and returns. There is no code path that evaluates gates, checks task lifecycle state, or routes accumulated payload to the next agent.

This ADR defines the relay architecture that makes the pipeline a pipeline.

---

## Decision

### 1. The Relay Path

A pipeline directive flows through the mesh as follows:

```
Mnemosyne (Editorial Director)
    │
    │  POST /message {type: "pipeline_directive", token: {...}, phase: "research", agent: "lulu"}
    ▼
Lulu's Transport
    │
    │  1. Validate DM token
    │  2. Evaluate in-gates (none — pipeline start)
    │  3. Spawn LLM task with directive
    │  4. LLM produces artifact → task_lifecycle.complete_task()
    │  5. Evaluate out-gates (artifact exists, non-empty)
    │  6. If PASS: accumulate token payload, route to next phase
    ▼
Penny Lane's Transport
    │
    │  1. Validate DM token
    │  2. Evaluate in-gates (research task done + artifact exists)
    │  3. Spawn LLM task with accumulated payload
    │  4. LLM produces artifact → task_lifecycle.complete_task()
    │  5. Evaluate out-gates
    │  6. If PASS: accumulate, route to next phase
    ▼
  ... (audit → build → deliver)
```

### 2. Token Accumulation

Each phase appends its output to the token payload. The token is the work product — not a reference to a file, not a log entry. The accumulated payload is what the next agent receives.

```json
{
  "pipeline": "newsletter",
  "issue_id": "2026-07-04",
  "phases": {
    "research": {
      "agent": "lulu",
      "state": "done",
      "artifact": "research_output.json",
      "summary": "Top 3 AI agent stories this week..."
    },
    "copy": {
      "agent": "penny-lane",
      "state": "done",
      "artifact": "copy_output.md",
      "summary": "Newsletter copy based on research..."
    }
  },
  "current_phase": "audit",
  "current_agent": "mnemosyne"
}
```

The token is passed forward intact. Each agent receives the full accumulated context. No agent reconstructs context from log files. No agent curl-posts completion notices to another agent's REST endpoint.

### 3. Gate Evaluation

Gates are evaluated at two points in the transport's message handler:

**In-gates** — evaluated BEFORE spawning the LLM task:
- Dependency gates: is the previous phase's task in `done` state?
- Artifact gates: does the required artifact exist and pass validation?
- If any gate BLOCKs, the directive is queued (not dropped). The transport re-evaluates on a 30-second poll.

**Out-gates** — evaluated AFTER the LLM task completes:
- Artifact gates: did the agent produce the required output?
- Validator gates: does the output pass validation (non-empty, valid JSON, approved flag)?
- If any gate BLOCKs, the task is marked `blocked` and the pipeline stalls. Mnemosyne is notified.

### 4. Manifold Routing

The `pipeline_orchestrator.py` already defines the phase sequence. The relay uses this to determine the next agent:

```python
PHASES = [
    {"phase": "research", "agent": "lulu", ...},
    {"phase": "copy",     "agent": "penny-lane", ...},
    {"phase": "audit",    "agent": "mnemosyne", ...},
    {"phase": "build",    "agent": "proteus", ...},
    {"phase": "deliver",  "agent": "proteus", ...},
]
```

When a phase completes (out-gates PASS), the relay:
1. Looks up the next phase in the sequence
2. Resolves the next agent's transport endpoint from the registry
3. Constructs a new pipeline directive with the accumulated token
4. POSTs it to the next agent's `/message` endpoint
5. The next agent's transport validates the DM token and evaluates in-gates

The relay does not require a central orchestrator. Each transport evaluates its own gates and routes to the next hop. The pipeline is a chain, not a hub-and-spoke.

### 5. Transport Integration Point

The relay hooks into the transport's `handle_message` method. A new message type — `pipeline_directive` — triggers the relay path:

```
handle_message(message):
    if message.type == "pipeline_directive":
        → validate_dm_token(message)
        → evaluate_in_gates(message)
        → spawn_llm_task(message)
        → on_llm_complete:
            → evaluate_out_gates(message)
            → accumulate_token(message)
            → route_to_next_phase(message)
    else:
        → existing directive/direct handling (unchanged)
```

The relay modules (`gate_engine`, `task_lifecycle`, `pipeline_orchestrator`) are imported by the transport. They are pure logic — no I/O, no transport dependency. The transport is the I/O layer.

### 6. Filesystem-Backed Task Lifecycle

The `task_lifecycle.py` module stores task state at `~/.maestro/tasks/{task_id}.json`. This is already implemented. Every transport can read and write task state. No agent owns the task lifecycle — it's shared infrastructure.

For the relay to work, every agent's transport must have access to the same `~/.maestro/tasks/` directory. On a single machine, this is trivial — it's the same filesystem. For multi-machine deployments, this becomes a shared volume requirement (out of scope for this ADR).

### 7. What Changes

| Component | Current State | Target State |
|-----------|--------------|--------------|
| Transport message handler | No relay path | `pipeline_directive` type triggers relay |
| Gate evaluation | Modules exist, uncalled | Called at in-gate and out-gate points |
| Task lifecycle | Modules exist, uncalled | `create_task()` on pipeline start, `complete_task()` on phase done |
| Token accumulation | Not implemented | Payload accumulates at each phase, passed forward |
| Manifold routing | Not implemented | `pipeline_orchestrator` determines next hop |
| Agent-to-agent dispatch | Raw HTTP curl | Transport POSTs to next agent's `/message` with DM token |

### 8. What Does NOT Change

- **Mnemosyne owns the pipeline.** She is the Editorial Director. She starts pipeline runs, monitors progress, and handles escalations. The relay is infrastructure — it does not make editorial decisions.
- **Proteus owns the transport code.** He builds the relay integration. Songbird specs it. Lexicon does not touch transport code.
- **The DM token system.** Tokens already exist on disk. The relay uses them for authentication at each hop. No new token format is needed.
- **The gate engine and task lifecycle modules.** They are correct as written. They need to be called, not rewritten.

---

## Consequences

**Positive:**
- Pipeline tests will actually test the pipeline. Agents will receive directives through the mesh, process them, and hand off accumulated work product to the next agent.
- No agent can "cheat" by curl-posting to REST endpoints. The relay path is the only path.
- Gate evaluation is automatic. A phase cannot start until its dependencies are met. A phase cannot be considered complete until its outputs are validated.
- The pipeline is observable. Task state is filesystem-backed. Any agent can query `~/.maestro/tasks/` to see pipeline status.

**Negative:**
- The relay adds complexity to the transport. The message handler grows a new code path.
- In-gate BLOCKs require a polling mechanism. A blocked phase must retry until its dependencies are met. This is new infrastructure.
- Token accumulation requires a schema. The payload format must be agreed upon by all agents in the pipeline.

**Risks:**
- If the relay is built as a patch job (quick HTTP workaround), it will fail the same way the first test failed. The relay must be built properly — token passing, gate evaluation, manifold routing — or not at all.
- If Proteus builds the relay without an ADR, the architecture will drift. This ADR is the spec. Songbird reviews it. Proteus builds to it.

---

## Pre-Existing Conditions (Audit Findings)

The 7-agent mesh has 12 gaps that must be closed before any pipeline test:

| Agent | Gateway | Transport | personality.md | DM Token | publicKey |
|-------|---------|-----------|----------------|----------|-----------|
| mnemosyne | UP | UP | YES | YES | MISSING |
| lulu | UP | UP | YES | NO | MISSING |
| zulu | UP | DOWN | YES | NO | MISSING |
| penny-lane | UP | UP | NO | NO | MISSING |
| thoth | UP | UP | YES | NO | MISSING |
| uatu | NONE | NONE | YES | NO | MISSING |
| keystone | UP | DOWN | YES | NO | MISSING |

Additionally, 3 agents have port conflicts in their maestro configs (cloned from other agents without changing the port). These are mechanical fixes — not architectural decisions. They are documented here for completeness but do not require ADR-level decisions.

**These gaps are pre-existing. They are not caused by the relay architecture. They must be fixed before any pipeline test, regardless of whether the relay is built.**
