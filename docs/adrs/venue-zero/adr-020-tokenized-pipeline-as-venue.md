# ADR-020 — Tokenized Pipeline as Venue

**Status:** Proposed
**Date:** 2026-07-07
**Author:** Proteus (with Jesse)
**Depends on:** ADR-017 (Authority), ADR-018 (Policy Contexts), ADR-004 (Venue Zero)

---

## 1. Observation

We have all the pieces for tokenized pipelines: relay evaluator, gate engine, task lifecycle, token primitives. The question is: where does the pipeline runner live?

The instinct is to embed it in the transport — `message_router.py` imports `pipeline_runner.py`, the transport walks the graph, the transport dispatches phases. This is what `_maybe_advance_pipeline()` does today.

But the transport is Maestro. It's the Plaza — agent-to-agent DMs, the base coordination layer. The pipeline is a Venue. It's TaskMaster Light — a workflow orchestrator that operates *on top of* Maestro, not inside it.

---

## 2. The Core Insight

> **The pipeline runner is a Venue service. It uses the transport's API. The transport does not import the pipeline runner.**

This is the same pattern as the renderer. The renderer is not inside the transport. It tails the event bus and delivers to Telegram. The transport doesn't know the renderer exists.

The pipeline runner should follow the same pattern: it's a standalone service that listens for directive completions and dispatches next phases. The transport provides a hook. The Venue consumes it.

### 2.1 The Invariant

> **A Venue is a client of Maestro, never an extension of Maestro.**

No Venue should ever require `from maestro.transport import ...`. If it needs an import from the transport package, that's a smell. It should be speaking protocol — HTTP, JSON, the hook interface. The transport exposes stable interfaces. Everything else composes on top.

This is the same invariant that governs the renderer (ADR-019), the event bus, and every other component that sits outside the transport. The transport doesn't know about Telegram renderers, Concerto panels, or pipeline venues. It just delivers messages and emits events.

### 2.2 The Recursive Property

The Pipeline Venue is itself an actor using Maestro to coordinate actors through Maestro. It doesn't get special privileges. It participates in the ecosystem exactly like everyone else — it sends directives, receives completions, and respects DM policy. The Venue is not above the system. It's in the system.

---

## 3. Architecture

### 3.1 Boundary

```
┌─────────────────────────────────────────┐
│ Maestro (Transport)                     │
│                                         │
│  Agent DMs    Registry    Event Bus     │
│  DM Policy    Surface     Health        │
│                                         │
│  pipeline_hook_url: "http://..."  (opt) │
│       │                                 │
│       │ POST /hook/directive-complete   │
│       ▼                                 │
└─────────────────────────────────────────┘
        │
        │ (Venue boundary — separate process)
        ▼
┌─────────────────────────────────────────┐
│ Pipeline Venue (TaskMaster Light)       │
│                                         │
│  Pipeline Runner                        │
│  Relay Evaluator    Gate Engine         │
│  Task Lifecycle     Graph Definitions   │
│                                         │
│  Uses transport API to:                 │
│    - Receive directive completions      │
│    - Dispatch next phases               │
│    - Query task state                   │
└─────────────────────────────────────────┘
```

### 3.2 Three Communication Models

Not every interaction in the ecosystem is agent-to-agent. Maestro supports three distinct communication models:

```
1. Peer communication (Plaza)
   Agent ↔ Agent
   Uses: DM transport, recipient-issued tokens (ADR-017)

2. Infrastructure interaction (Venue)
   Agent ↔ Venue API
   Uses: HTTP/API, auth chosen by the Venue
   This is not a DM. It's a client talking to a service.

3. Observation
   Transport → Event Bus → Renderer
   Not a DM. Not an agent. Infrastructure.
```

The Venue is not an agent. It doesn't participate in the DM token system because it doesn't use the DM system at all. Trying to force Venue communication through DMs weakens the architecture — it conflates peer relationships with infrastructure relationships.

The Venue owns its own API. Whether that API is HTTP, WebSocket, filesystem, queue, or gRPC is an implementation choice. The architectural decision is simply: the Venue defines its own interaction model. Agents connect to it voluntarily. They opted into the Venue's rules when they joined.

### 3.3 The Hook (Transport → Venue)

The one place the transport and Venue touch: when a directive completes, if `pipeline_hook_url` is configured, the transport POSTs the completion event to that URL. Fire-and-forget. The transport doesn't wait for a response.

This is the only interface between them. The transport doesn't know it's being used by a pipeline. It just emits events. The Venue consumes them.

### 3.4 What the Transport Owns

- Agent registry
- DM policy enforcement
- Message routing (P2P delivery)
- Event bus surfacing
- The `pipeline_hook_url` config field (a single URL, no logic)

### 3.4 What the Venue Owns

- Pipeline graph definitions (`~/.maestro/pipelines/{name}/graph.json`)
- Token state (`~/.maestro/pipelines/{name}/{issue_id}/token.json`)
- Task lifecycle (filesystem-backed, shared with transport)
- Gate evaluation
- Relay graph walking
- Phase dispatch decisions

---

## 4. The Hook Protocol

### 4.1 Transport → Venue: Directive Complete

```
POST {pipeline_hook_url}/hook/directive-complete
{
    "event": "directive_complete",
    "message": { ... full directive message ... },
    "agent_id": "proteus",
    "timestamp": "2026-07-07T..."
}
```

The Venue responds `200 OK`. The transport doesn't care about the response body.

### 4.2 Venue → Agent: Work Dispatch

The Venue owns its own API. How agents receive work is a Venue implementation choice — HTTP endpoint, WebSocket, filesystem poll, message queue, gRPC. The architectural decision is that the Venue defines its own interaction model. Agents connect to it voluntarily. They opted into the Venue's rules when they joined.

This is not a DM. The Venue is not an agent. It doesn't use the transport's `/message` endpoint for dispatch. It has its own surface.

---

## 5. Deployment

### 5.1 Transport Config

```json
{
    "agentId": "proteus",
    "pipeline_hook_url": "http://127.0.0.1:3870"
}
```

One hook URL per transport. If unset, no hook is called. The transport operates normally without any pipeline awareness.

### 5.2 Venue Service

A standalone Python process:
```
/usr/bin/python3 pipeline_venue.py --port 3870 --graph adr_implementation
```

Listens on its own port. Loads graph definitions from `~/.maestro/pipelines/`. Uses the transport's `/message` endpoint for dispatch.

### 5.3 Systemd

```
[Unit]
Description=Maestro Pipeline Venue (TaskMaster Light)
After=maestro-transport@proteus.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/andjesse/.maestro/pipeline_venue.py --port 3870
Restart=always
```

---

## 6. Relationship to Existing ADRs

### ADR-004 (Venue Zero)
ADR-004 defined the Local Org as Venue Zero — the first Venue. The pipeline Venue is the first *implemented* Venue. It inherits the Venue contract: constraints, incentives, pipelines, and (per ADR-018) normative context.

### ADR-017 (Authority)
The pipeline Venue is an actor. It issues DM tokens to agents it dispatches to. It presents those tokens when dispatching. DM policy applies to the Venue exactly as it applies to any agent.

### ADR-018 (Policy Contexts)
The pipeline Venue defines a policy context. When an agent receives a pipeline directive, the token declares the context. The agent activates its pipeline policy profile.

### ADR-019 (Renderer)
Same pattern: the renderer is a standalone service that consumes transport events. The pipeline Venue is a standalone service that consumes directive completions. Neither is inside the transport.

---

## 7. What This Enables

1. **Multiple Venues.** Different pipeline graphs for different workflows. ADR implementation, newsletter, code review — each is a separate Venue with its own graph.

2. **Venue competition.** Once orchestration logic lives outside the transport, anyone can compete on pipeline quality without forking Maestro itself. Decomposition strategies, graph design, scheduling policies, recovery behavior — all become competitive dimensions. The transport doesn't care which Venue dispatched the directive. The ecosystem evolves independently of the substrate.

3. **Independent evolution.** The transport and Venue evolve independently. The hook protocol is the only interface. Change the relay evaluator without touching the transport.

4. **Dogfooding from day one.** The ADR implementation pipeline runs on the Venue. We prove the architecture by using it.

### 7.1 The Four-Layer Model

This ADR completes a pattern that has been emerging across the last five ADRs:

```
Maestro     → Communication substrate
Venue       → Coordination strategy
Agent       → Reasoning
Renderer    → Observation
```

Every layer has one job. No layer imports the layer above it. The transport doesn't know about Venues. Venues don't know about renderers. Agents don't know about pipelines. Each layer composes on the stable interfaces of the layer below.

This is the same discipline that deleted four mechanisms from the renderer (ADR-019) and collapsed "DM Enforcer" into actor-owned policy (ADR-017). When a module knows exactly what it is, it stops needing to infer its role from surrounding context.

---

## 8. Implementation Plan

### Phase 1: Hook in Transport
- Add `pipeline_hook_url` config field
- Add `_notify_pipeline_hook()` — POSTs directive completions
- No other transport changes

### Phase 2: Venue Service
- `pipeline_venue.py` — standalone HTTP server
- `/hook/directive-complete` endpoint
- Imports `pipeline_runner.py` (relay evaluator + gate engine + task lifecycle)
- Dispatches via transport's `/message` endpoint

### Phase 3: First Pipeline
- `adr_implementation/graph.json` — spec → decompose → code → recompose → coherence → qa → push
- Start the Venue, start a pipeline, watch it run

---

## 9. Open Questions

1. **Venue identity:** Does the Venue have its own agent ID in the registry? Or is it anonymous?
2. **Token issuance:** How does the Venue get DM tokens for all agents it might dispatch to? Pre-issued? Green Room?
3. **Fan-in waiting:** The relay evaluator returns WAIT for fan-in nodes. How does the Venue know when all branches have completed? Polling? Event-driven?
4. **Error recovery:** What happens when a phase fails? Retry? Skip? Escalate to human?
5. **Multiple transports:** Can one Venue service hook into multiple transports? Or one Venue per transport?
