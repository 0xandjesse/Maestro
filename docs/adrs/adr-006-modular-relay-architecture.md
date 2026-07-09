# ADR-006: Modular Relay Architecture — Composable Primitives for Conditional Routing, Loops, and Parallelism

**Status:** Draft
**Date:** 2026-07-04
**Author:** Lexicon (COO)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)
**Supersedes:** ADR-004 (Relay Architecture — Tokenized Pipeline Routing)

---

## Context

ADR-004 defined a linear pipeline relay: a hardcoded phase list with single-next-hop routing. It was a conveyor belt — `research → copy → audit → build → deliver`. One path, no branches, no loops, no parallelism.

Jesse's directive (2026-07-04): the relay must support conditional routing ("if audit passes → build, else → back to copy"), improvement loops ("audit routes back to writers room for rewrites"), and parallelism ("approved draft → Marketing + A/V simultaneously"). These are not edge cases — they are the core workflow patterns the Local Org uses today and that TaskMaster will productize.

The relay primitives must be simple enough to define a workflow in a few sentences, and robust enough to encode complex rulesets through composition. The same primitives must work identically on a local mesh and on a distributed P2N network — only the transport layer differs.

### Architectural Intent

The Local Org is not merely consuming this relay architecture — it is evolving it. Every workflow pattern developed locally serves as experimental input for the proprietary relay engine that will eventually power TaskMaster. The relay primitives therefore have two simultaneous design goals:

1. They must remain sufficiently small and composable that complex workflows emerge through composition rather than specialized orchestration logic.
2. They must be expressive enough that real-world organizational workflows can be represented without requiring custom code.

This ADR replaces ADR-004's linear pipeline with a modular relay graph architecture. It defines not just a better routing mechanism, but TaskMaster's coordination language — the shared vocabulary through which agents and organizations express work.

---

## Decision

### 1. The Relay Graph Model

A workflow is a directed graph of relay nodes. Each node is a single primitive. Edges carry tokens between nodes. The graph is defined declaratively — no code, no YAML DAGs, no state machines.

```
brief (mnemosyne)
    │
    ▼
fan_out → [lulu: research, thoth: research]
    │
    ▼
fan_in → copy (penny-lane)
    │
    ▼
loop (max=3):
    audit (mnemosyne)
        ├── PASS → fan_out → [marketing, a/v]
        └── FAIL → back to copy
```

The relay evaluator walks the graph. Each node receives a token, executes its logic, and routes the token to the next node(s) based on the result. The token is the work product — it accumulates state at every hop.

### 2. The Five Relay Primitives

Every relay primitive has the same interface:

```
receive(token) → evaluate(token) → route(token, target_nodes)
```

The primitives differ only in their evaluate() and route() logic.

---

#### 2.1 Sequence

**Logic:** A → B → C. Linear handoff. No branching.

**Token behavior:** Token passes through unchanged. Each node appends its phase result to `token.payload.phases`.

**Definition:**
```json
{
  "type": "sequence",
  "nodes": ["research", "copy", "audit", "build", "deliver"]
}
```

**Route rule:** On phase complete → route to next node in sequence. On last node → terminal (pipeline complete).

**Edge cases:** If a node fails (non-retryable error), the sequence halts. The token is marked `blocked` and the pipeline owner is notified.

---

#### 2.2 Branch

**Logic:** Evaluate a condition on the token. Route to one of two (or more) target nodes based on the result.

**Token behavior:** Token passes through unchanged. The branch itself does not modify the token — it only routes.

**Definition:**
```json
{
  "type": "branch",
  "condition": {
    "field": "token.payload.phases.audit.result",
    "operator": "equals",
    "value": "PASS"
  },
  "on_match": "build",
  "on_mismatch": "copy"
}
```

**Supported operators:** `equals`, `not_equals`, `contains`, `exists`, `greater_than`, `less_than`.

**Multi-way branch (switch):**
```json
{
  "type": "branch",
  "condition": {
    "field": "token.payload.phases.audit.score",
    "operator": "greater_than"
  },
  "routes": [
    {"value": 90, "target": "publish"},
    {"value": 70, "target": "revise"},
    {"value": 0,  "target": "rewrite"}
  ]
}
```

**Edge cases:** If no route matches, the token is routed to a default fallback node. If no fallback is defined, the pipeline halts with `unmatched_branch`.

---

#### 2.3 Fan-Out

**Logic:** Send the token to multiple target nodes simultaneously. Each target receives a copy of the token with its own `fan_out_id`.

**Token behavior:** The original token is cloned N times. Each clone gets `token.meta.fan_out_id` set to the target node's ID. Each clone accumulates its own phase results independently.

**Definition:**
```json
{
  "type": "fan_out",
  "targets": [
    {"node": "marketing_tweets", "agent": "lulu"},
    {"node": "av_images", "agent": "penny-lane"},
    {"node": "social_clips", "agent": "thoth"}
  ]
}
```

**Edge cases:**
- A fan-out target can itself be a sub-graph (nested relay chain). The fan-out doesn't care what's downstream — it just routes.
- If a target is unreachable (transport down), the fan-out marks that branch as `blocked` and continues with the others. The pipeline owner is notified.
- Fan-out is fire-and-forget. It does not wait for results. That's fan-in's job.

---

#### 2.4 Fan-In

**Logic:** Wait for all specified branches to complete, then merge results and route to the next node.

**Token behavior:** The fan-in node collects tokens from all inbound branches. When all have arrived (or timeout), it merges their `payload.phases` entries into a single token and routes forward.

**Definition:**
```json
{
  "type": "fan_in",
  "sources": ["marketing_tweets", "av_images", "social_clips"],
  "merge_strategy": "append",
  "timeout_seconds": 3600,
  "on_timeout": "route_partial"
}
```

**Merge strategies:**
- `append` — concatenate all phase results into the token. Default.
- `merge` — deep-merge phase results by key. Conflicts: last-write-wins.
- `first` — use the first branch to complete, discard others.

**Timeout behavior:**
- `route_partial` — route with whatever has arrived. Mark missing branches as `timeout`.
- `fail` — mark the entire pipeline as `blocked`. Notify owner.
- `ignore` — drop missing branches silently, route with completed ones.

**Edge cases:**
- If a source branch was never started (fan-out target was unreachable), it's treated as already `blocked` — fan-in doesn't wait for it.
- Fan-in is the convergence primitive. It pairs with fan-out. They are not required to be used together — fan-out can route to terminal nodes, and fan-in can collect from independently started branches.

---

#### 2.5 Loop

**Logic:** Execute a sub-graph repeatedly until a condition is met or max iterations is reached.

**Token behavior:** The token accumulates state across iterations. Each iteration appends to `token.payload.phases` with an `iteration` index. The loop condition evaluates against the token after each iteration.

**Definition:**
```json
{
  "type": "loop",
  "max_iterations": 3,
  "condition": {
    "field": "token.payload.phases.audit.result",
    "operator": "equals",
    "value": "PASS"
  },
  "body": ["copy", "audit"],
  "on_max": "route_with_warning"
}
```

**Loop body:** A sub-graph (sequence of nodes). The body executes, then the condition is evaluated. If condition matches → exit loop, route to `after`. If condition doesn't match and iterations remain → re-enter body. If max iterations reached → execute `on_max` behavior.

**On-max behaviors:**
- `route_with_warning` — route forward with `token.meta.loop_exhausted: true`. The downstream node decides what to do.
- `fail` — mark pipeline `blocked`. Notify owner.
- `route_to_fallback` — route to a specified fallback node (e.g., human review).

**Edge cases:**
- The loop body can contain any primitives — including nested loops, fan-outs, and branches. A loop is just a sub-graph.
- Loop iteration state is tracked in the token, not in the relay. The relay is stateless — it reads `token.meta.loop_iteration` to know where it is.
- Infinite loop prevention: `max_iterations` is mandatory. No default. The workflow author must set it.

---

### 3. Token Accumulation Across Primitives

The token is the single source of truth. Every primitive reads from it and writes to it. The schema:

```json
{
  "token_id": "uuid",
  "pipeline": "newsletter",
  "meta": {
    "loop_iteration": 0,
    "fan_out_id": "marketing_tweets",
    "loop_exhausted": false
  },
  "payload": {
    "issue_id": "2026-07-04",
    "phases": {
      "research_lulu": {
        "agent": "lulu",
        "state": "done",
        "artifact": "research_lulu.json",
        "summary": "..."
      },
      "research_thoth": {
        "agent": "thoth",
        "state": "done",
        "artifact": "research_thoth.json",
        "summary": "..."
      },
      "copy": {
        "agent": "penny-lane",
        "state": "done",
        "iteration": 2,
        "artifact": "copy_v3.md",
        "summary": "..."
      },
      "audit": {
        "agent": "mnemosyne",
        "state": "done",
        "iteration": 2,
        "result": "PASS",
        "score": 92
      }
    }
  }
}
```

Key properties:
- **Append-only.** Phases are never overwritten — new iterations append with an incremented `iteration` field.
- **Self-describing.** Any agent can read the token and understand the full pipeline state. No external log files, no curl-posted completion notices.
- **Merge-safe.** Fan-in merges tokens by appending phase entries. No conflict resolution needed — each phase has a unique key.

---

### 4. The Relay Evaluator

The relay evaluator is the engine that walks the graph. It replaces ADR-004's `pipeline_orchestrator.py` phase list lookup.

**Core loop:**

```
evaluate(token, graph, current_node):
    node = graph[current_node]
    
    if node.type == "sequence":
        result = execute_phase(node, token)
        next_node = node.next
        if next_node:
            route(token, next_node)
        else:
            terminal(token)
    
    elif node.type == "branch":
        match = evaluate_condition(node.condition, token)
        target = node.routes[match] or node.fallback
        route(token, target)
    
    elif node.type == "fan_out":
        for target in node.targets:
            clone = clone_token(token, fan_out_id=target.node)
            route(clone, target.node)
    
    elif node.type == "fan_in":
        if all_sources_complete(token, node.sources):
            merged = merge_tokens(token, node.sources, node.merge_strategy)
            route(merged, node.next)
        else:
            queue(token, node)  # wait for remaining sources
    
    elif node.type == "loop":
        if evaluate_condition(node.condition, token):
            route(token, node.after)  # exit loop
        elif token.meta.loop_iteration >= node.max_iterations:
            handle_max_iterations(token, node)
        else:
            token.meta.loop_iteration += 1
            route(token, node.body[0])  # re-enter body
```

**The evaluator is stateless.** It reads the token, evaluates the current node, and routes. All state lives in the token and in the filesystem-backed task store (`~/.maestro/tasks/`). The evaluator can be restarted mid-pipeline without losing progress.

**The evaluator is the same everywhere.** Local Org mesh, TaskMaster P2N network, single-machine test — same evaluator code, same primitives, same token format. Only the transport layer changes.

---

### 5. Workflow Definition — The "Few Sentences" Constraint

A workflow is defined as a JSON graph. The goal: a human should be able to read it and understand the flow without documentation.

**Example: Newsletter pipeline with improvement loop and parallel publishing**

```json
{
  "pipeline": "newsletter",
  "graph": {
    "brief": {
      "type": "sequence",
      "nodes": ["research", "copy", "audit_loop"]
    },
    "research": {
      "type": "fan_out",
      "targets": [
        {"node": "research_lulu", "agent": "lulu"},
        {"node": "research_thoth", "agent": "thoth"}
      ]
    },
    "research_lulu": {
      "type": "sequence",
      "nodes": ["research_lulu_work", "research_merge"]
    },
    "research_lulu_work": {
      "type": "phase",
      "agent": "lulu",
      "work_type": "research",
      "next": "research_merge"
    },
    "research_thoth": {
      "type": "sequence",
      "nodes": ["research_thoth_work", "research_merge"]
    },
    "research_thoth_work": {
      "type": "phase",
      "agent": "thoth",
      "work_type": "research",
      "next": "research_merge"
    },
    "research_merge": {
      "type": "fan_in",
      "sources": ["research_lulu_work", "research_thoth_work"],
      "merge_strategy": "append",
      "next": "copy"
    },
    "copy": {
      "type": "phase",
      "agent": "penny-lane",
      "work_type": "copy",
      "next": "audit_loop"
    },
    "audit_loop": {
      "type": "loop",
      "max_iterations": 3,
      "condition": {
        "field": "token.payload.phases.audit.result",
        "operator": "equals",
        "value": "PASS"
      },
      "body": ["audit", "audit_branch"],
      "after": "publish_fanout",
      "on_max": "route_with_warning"
    },
    "audit": {
      "type": "phase",
      "agent": "mnemosyne",
      "work_type": "audit",
      "next": "audit_branch"
    },
    "audit_branch": {
      "type": "branch",
      "condition": {
        "field": "token.payload.phases.audit.result",
        "operator": "equals",
        "value": "PASS"
      },
      "on_match": null,
      "on_mismatch": "copy"
    },
    "publish_fanout": {
      "type": "fan_out",
      "targets": [
        {"node": "marketing", "agent": "lulu"},
        {"node": "av", "agent": "penny-lane"}
      ]
    },
    "marketing": {
      "type": "phase",
      "agent": "lulu",
      "work_type": "social_copy"
    },
    "av": {
      "type": "phase",
      "agent": "penny-lane",
      "work_type": "image_gen"
    }
  }
}
```

**The `phase` type** is a leaf node — it dispatches work to an agent and waits for completion. It's the only node that actually invokes an LLM. All other nodes are routing logic.

**Syntactic sugar (future):** The JSON graph is the canonical format. A shorthand DSL can compile to it:

```
newsletter:
  brief → research{fan_out: lulu, thoth} → copy → audit{loop: max=3, until=PASS} → publish{fan_out: marketing, av}
```

This is not part of ADR-006. It's noted here as the target UX for TaskMaster. The JSON graph is the implementation layer; the DSL is the user layer.

---

### 6. What Changes From ADR-004

| Component | ADR-004 | ADR-006 |
|-----------|---------|---------|
| Phase definition | Hardcoded list in `pipeline_orchestrator.py` | Declarative JSON graph |
| Routing | `next_index += 1` | Relay evaluator walks graph edges |
| Branching | Not supported | Branch primitive with condition evaluation |
| Loops | Not supported | Loop primitive with max iterations + condition |
| Parallelism | Not supported | Fan-out + fan-in primitives |
| Token accumulation | Spec'd but not implemented | Same schema, now carries loop iteration + fan-out ID |
| Gate evaluation | PASS/BLOCK only | Gate results feed into branch/loop conditions |
| Transport integration | `pipeline_directive` message type | Same message type, evaluator replaces phase list lookup |
| TaskMaster compatibility | Local-only design | Same primitives, same evaluator, different transport |

**What does NOT change:**
- The DM token system. Tokens still authenticate at each hop.
- The gate engine (`gate_engine.py`). It still evaluates artifact existence, validation, and dependency gates. Its output now feeds into branch/loop conditions instead of binary PASS/BLOCK.
- The task lifecycle (`task_lifecycle.py`). Tasks are still created, tracked, and completed on the filesystem.
- Mnemosyne owns the pipeline. The relay is infrastructure.
- Proteus owns the transport code. Songbird specs it. Lexicon does not touch it.

---

### 7. Transport Integration

The relay evaluator hooks into the transport's message handler at the same point ADR-004 specified — the `pipeline_directive` message type. The difference: instead of looking up the next phase in a list, the handler calls the relay evaluator with the token and the graph.

```
handle_message(message):
    if message.type == "pipeline_directive":
        token = message.token
        graph = load_graph(token.pipeline)
        current_node = token.meta.current_node or graph.entry_point
        evaluate(token, graph, current_node)
```

The evaluator is a pure function. It imports `gate_engine` and `task_lifecycle`. It does no I/O except through those modules. The transport is the I/O layer — it handles HTTP, DM validation, and agent dispatch.

---

### 8. TaskMaster Implications

The relay evaluator is the product. TaskMaster is a venue where users define workflows by composing relays. The primitives are identical to the Local Org's — the only difference is that TaskMaster routes tokens across a P2N network instead of a local mesh.

**What TaskMaster adds:**
- A workflow builder UI that compiles to the JSON graph format
- A shorthand DSL for quick workflow definition
- A relay marketplace — pre-built relay chains for common workflows (newsletter, content pipeline, code review, grant application)
- Per-workflow pricing (not per-primitive)

**What TaskMaster inherits unchanged:**
- The five relay primitives
- The token accumulation schema
- The relay evaluator
- The gate engine
- The task lifecycle

The Local Org is the testbed. Every workflow pattern we build here is a TaskMaster template. Every edge case we hit is a product requirement.

### 9. The Relay Language — Coordination Literacy as Career Progression

Although the relay graph is represented internally as JSON, the relay primitives collectively form a small coordination language. This language is the shared vocabulary through which work is expressed, routed, and verified across the network.

Most participants will never author relay graphs directly. Workers simply execute phases within relay-defined workflows. As participants accumulate experience through repeated interaction with existing workflows, they naturally develop an understanding of the relay language and eventually become capable of designing workflows of their own.

TaskMaster therefore treats workflow design as an acquired organizational capability rather than a prerequisite for participation.

**Coordination literacy progression:**

| Level | Capability | How Acquired |
|-------|-----------|--------------|
| 1 — Execute | Can execute assigned phases within existing workflows | Default entry point |
| 2 — Decompose | Can break work into phases and hand off to others | Exposure to varied workflows |
| 3 — Design | Can author original relay graphs for new workflow types | Pattern recognition across domains |
| 4 — Optimize | Can refactor workflows for efficiency, parallelism, and fault tolerance | Deep experience with edge cases |
| 5 — Publish | Can produce reusable relay templates for the marketplace | Mastery of the coordination language |

This progression means an agent isn't merely earning reputation — they're acquiring coordination literacy. The relay language is learned through participation, not taught through documentation. By the time an agent reaches the top of the pyramid, they've been exposed to enough different workflows that the relay language is second nature.

**Strategic implication:** TaskMaster isn't selling routing infrastructure. It's selling institutional knowledge. The relay engine is software. The accumulated workflow patterns, debugging experience, templates, and edge-case handling — that's the moat. A competitor can copy five primitives. They cannot instantly copy years of refined workflow templates and learned coordination patterns.

The relay primitives are intentionally small because the long-term objective is not merely to execute workflows, but to establish a shared coordination language that agents learn through participation.

---

## Consequences

**Positive:**
- Workflows can express real-world patterns: improvement loops, parallel execution, conditional routing.
- The relay primitives are simple individually. Complexity emerges from composition — not from a monolithic orchestrator.
- The same primitives work locally and in TaskMaster. No rewrite needed.
- The token is the single source of truth. Any agent can read it and understand the full pipeline state.
- The evaluator is stateless. Restart-safe. Filesystem-backed.

**Negative:**
- The relay evaluator is more complex than a phase list. More code paths, more edge cases.
- Fan-in requires a polling or event-driven wait mechanism. This is new infrastructure.
- Token cloning in fan-out means N copies of the token exist simultaneously. Merge conflicts are possible if two branches modify the same phase key (mitigated by unique phase keys per branch).
- Loop exhaustion (`on_max`) requires downstream agents to handle `loop_exhausted: true` tokens. This is a new edge case for every agent in a loop-capable pipeline.

**Risks:**
- If the relay evaluator is built as a patch on ADR-004's linear model, it will be fragile. The evaluator must be built from the graph model up.
- Fan-in timeouts could mask real failures. A branch that silently dies looks the same as a slow branch. The timeout must be generous by default and configurable per workflow.
- The JSON graph format could become verbose for complex workflows. The DSL is the escape hatch — but it's not in scope for this ADR.

---

## Implementation Phases

### Phase 1: Relay Evaluator Core
- Implement the five primitives as pure functions
- Implement the graph walker (evaluate → route loop)
- Unit tests for each primitive in isolation

### Phase 2: Token Accumulation
- Implement token clone (fan-out)
- Implement token merge (fan-in)
- Implement loop iteration tracking
- Unit tests for merge strategies and edge cases

### Phase 3: Transport Integration
- Wire evaluator into transport message handler
- Replace phase list lookup with graph walk
- Implement fan-in wait mechanism (polling or event-driven)
- Integration test: newsletter pipeline with loop + fan-out

### Phase 4: TaskMaster Compatibility
- Verify evaluator works with P2N transport (not just local mesh)
- Document the JSON graph schema as the TaskMaster workflow format
- Spec the DSL compiler (out of scope for implementation, in scope for documentation)

---

## Pre-Existing Conditions

ADR-005 (Agent Maintenance Audit) must be completed before any pipeline test. The 19 gaps documented there — missing personality.md files, missing publicKeys, downed transports, port conflicts — will cause pipeline failures regardless of relay architecture. The relay evaluator cannot route to an agent whose transport is down or whose DM token is missing.

These are separate concerns. ADR-005 is infrastructure health. ADR-006 is relay architecture. Both must be true for the pipeline to work.
