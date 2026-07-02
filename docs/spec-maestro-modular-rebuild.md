# Maestro Modular Rebuild — Technical Specification
## Phase 1: Module Boundaries, Interface Contracts, Extraction Plan

**Author:** Songbird (CTO, Swarm Corp)
**Date:** 2026-06-30
**Status:** Draft — for Jesse review
**Based on:** ADR-003 (2026-06-24)
**Repository:** `~/Projects/Maestro/` (canonical — NOT `~/maestro-sdk/`)

---

## 0. Ground Truth — Current Codebase State

### 0.1 Repository Location

**CANONICAL:** `/home/andjesse/Projects/Maestro/`
**SHADOW (DO NOT USE):** `/home/andjesse/maestro-sdk/` — 7 files, 299-line stripped transport. Botched migration artifact.

### 0.2 Scale

| Metric | Value |
|--------|-------|
| Python files (runtime/) | 466 |
| Total lines (runtime/) | ~368,000 |
| TypeScript files (src/) | ~50 |
| Notebooks | 0 (already purged) |
| Duplicate forks | `maestro-protocol-backup-v0.2.0/` (stale), `live/maestro_transports/` (stale copies) |

### 0.3 Monoliths — Extraction Targets

| File | Lines | What It Contains |
|------|-------|-----------------|
| `runtime/gateway/run.py` | 17,516 | Gateway server, platform adapters, hook system, message dispatch, tool registration |
| `runtime/run_agent.py` | 16,395 | Agent lifecycle, session management, tool execution loop, context assembly |
| `runtime/cli.py` | 14,164 | CLI commands, config management, setup wizard, agent spin-up |
| `runtime/hermes_cli/main.py` | 12,300 | Hermes CLI entry, subcommand routing, arg parsing |
| `runtime/maestro_transport/maestro_transport.py` | 1,842 | Transport daemon, message routing, registry, circuit breaker, ACK filter |

### 0.4 Existing Modular Pieces (Already Extracted)

| File | Lines | Module |
|------|-------|--------|
| `runtime/maestro_transport/supervisor.py` | 394 | Health-check daemon (partial — needs kill authority hardening) |
| `runtime/maestro_transport/checklist_manager.py` | 159 | Checklist CRUD |
| `runtime/maestro_transport/audit_log.py` | 156 | JSONL audit logger |
| `runtime/maestro_transport/log_writer.py` | 96 | Structured transport logging |
| `runtime/maestro_transport/agent_logger.py` | 59 | Agent action logger |
| `~/.maestro/port_map_loader.py` | 61 | Port map reader |
| `~/.maestro/verify_ports.py` | 42 | Port verification script |

### 0.5 Supporting Infrastructure (Outside Runtime)

| Path | Purpose |
|------|---------|
| `~/.maestro/registry.json` | Agent identity registry (multi-writer, corruption-prone) |
| `~/.maestro/port_map.json` | Port assignments (already has hermes-prime) |
| `~/.maestro/contacts.json` | Agent contact cards |
| `~/.maestro/configs/<agent>.json` | Per-agent transport configs (16 files, drift-prone) |
| `~/.maestro/dm_tokens/` | DM delegation tokens |
| `~/.maestro/maestro_visibility.json` | Per-agent display config |
| `~/.maestro/blackboards/` | Agent blackboards (~45 files) |
| `~/.maestro/checklists/` | Checklist JSON files |
| `~/.maestro/maestro_transport.json` | Transport daemon config |
| `~/.maestro/vault.json` | Encrypted secrets |
| `~/.maestro/revoked_tokens/` | Token revocation lists |

---

## 1. Architecture Overview

### 1.1 The Nucleus Model

```
┌─────────────────────────────────────────────────────────┐
│                    MAESTRO NUCLEUS                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ Message  │ │ Registry │ │   Gate   │ │  Resource  │ │
│  │ Router   │ │ Manager  │ │  Engine  │ │  Monitor   │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │   DM     │ │  Bridge  │ │  Intent  │ │    Task    │ │
│  │ Enforcer │ │ Surface  │ │Classifier│ │ Lifecycle  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │  Config  │ │   Port   │ │Dead Letter│ │  Session   │ │
│  │Generator │ │Authority │ │   Queue   │ │ Checkpoint │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │Visibility│ │  Agent   │ │   Key     │ │ Transport  │ │
│  │ Registry │ │Lifecycle │ │Authority  │ │State Refresh│ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│                                                         │
│              Module Registry + Message Bus              │
└─────────────────────────────────────────────────────────┘
```

Each module is a self-contained Python package with:
- `__init__.py` — exports the public interface
- `module.py` — implementation
- `schema.py` — data models (dataclasses or TypedDicts)
- `test_module.py` — unit tests

### 1.2 Module Registration Protocol

```python
# nucleus/registry.py
def register_module(name: str, interface: type, implementation: object, namespace: str = "core") -> ModuleHandle:
    """
    Register a module with the nucleus.
    
    Validates that implementation satisfies the interface contract.
    Returns a handle for routing.
    """
```

Modules register at startup. The nucleus validates interface compliance — does the implementation expose the methods declared in the interface? — and adds it to the routing table. No human approval. No gatekeeping.

### 1.3 Visibility

```python
@dataclass
class ModuleMetadata:
    name: str
    interface_version: str
    visibility: Literal["public", "private"]  # public = any venue can use; private = namespace-scoped
    namespace: str  # "core", "taskmaster", "locr", etc.
```

---

## 2. Module Interface Contracts

### Module 1: Message Router

**Priority:** HIGH (blocks 5 other modules)
**Extract from:** `runtime/maestro_transport/maestro_transport.py` (lines 159-260)
**Dependencies:** None (independent)

```python
# nucleus/modules/message_router/interface.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

class DeliveryResult(Enum):
    DELIVERED = "delivered"
    FAILED = "failed"
    QUEUED = "queued"        # dead letter queue
    REJECTED = "rejected"    # policy block
    DUPLICATE = "duplicate"  # seen-set hit

@dataclass
class MessageEnvelope:
    id: str                          # UUID
    type: str                        # "direct", "broadcast", "proxy", "system"
    sender: dict                     # {agentId, endpoint?}
    recipient: dict                  # {agentId, endpoint?}
    content: str
    timestamp: int                   # epoch ms
    version: str                     # protocol version
    intent: str | None = None        # "work" | "ack" | "query" | "status" — NEW
    inReplyTo: str | None = None
    stageId: str | None = None
    venueId: str | None = None      # venue-scoped routing
    ttl: int | None = None           # seconds until expiry

@dataclass
class RouteResult:
    result: DeliveryResult
    message_id: str
    detail: str | None = None
    delivered_to: str | None = None

@runtime_checkable
class MessageRouter(Protocol):
    def route(self, message: MessageEnvelope) -> RouteResult: ...
    def validate(self, message: MessageEnvelope) -> bool: ...
    def get_seen_count(self) -> int: ...
```

**Current code location:** `MaestroTransport.handle_message()` (lines 185-216) + `_process_message()` (lines 220-260) in `runtime/maestro_transport/maestro_transport.py`

**Extraction notes:**
- `SeenSet` class (lines 140-157) → `message_router/dedup.py`
- `_ack_pattern` (lines 169-172) → replaced by `intent` field — ACK suppression moves to Intent Classifier
- Circuit breaker logic (lines 226-244) → stays in router as `_check_rate_limit()`
- Reply construction (lines 247-251) → `message_router/reply.py`

---

### Module 2: DM Enforcer

**Priority:** HIGH (security boundary)
**Extract from:** `runtime/maestro_transport/maestro_transport.py` + `~/.maestro/dm_tokens/`
**Dependencies:** Key Authority (15), Registry Manager (4)

```python
# nucleus/modules/dm_enforcer/interface.py
from enum import Enum

class DMPolicyResult(Enum):
    ALLOWED = "allowed"
    DENIED_NO_TOKEN = "denied_no_token"
    DENIED_EXPIRED = "denied_expired"
    DENIED_REVOKED = "denied_revoked"
    DENIED_SCOPE = "denied_scope"
    DENIED_KEY_MISMATCH = "denied_key_mismatch"

@dataclass
class DMToken:
    token_id: str
    issuer: str                     # agentId of issuer
    subject: str                    # agentId of bearer
    scope: list[str]                # ["dm:send", "dm:receive"]
    issued_at: int                  # epoch ms
    expires_at: int                 # epoch ms
    signature: str                  # Ed25519 signature
    public_key: str                 # issuer's public key

@runtime_checkable
class DMEnforcer(Protocol):
    def check_policy(self, sender_id: str, recipient_id: str, token: DMToken | None = None) -> DMPolicyResult: ...
    def issue_token(self, issuer_id: str, subject_id: str, scope: list[str], ttl_hours: int = 24) -> DMToken: ...
    def revoke_token(self, token_id: str) -> bool: ...
    def verify_token(self, token: DMToken) -> tuple[bool, str]: ...  # (valid, reason)
```

**Current code location:** `dm_policy` config block in per-agent configs + `~/.maestro/dm_tokens/*.json`

**Extraction notes:**
- Token issuance currently manual — this module makes it programmatic
- Post-issuance verification (Key Authority integration) is the critical fix for the 2026-06-24 Lexicon key mismatch bug
- Token storage: `~/.maestro/dm_tokens/{agent_id}.json` → `nucleus/data/dm_tokens/{token_id}.json`

---

### Module 3: Gate Engine

**Priority:** MEDIUM
**Extract from:** New module (no current implementation — extends existing `valid_after` concept)
**Dependencies:** Registry Manager (4)

```python
# nucleus/modules/gate_engine/interface.py
from enum import Enum

class GateType(Enum):
    TIME = "time"           # valid_after / valid_until
    DEPENDENCY = "dependency"  # requires_token completion
    RESOURCE = "resource"   # memory/cpu threshold
    RATE = "rate"           # tokens per minute

class GateResult(Enum):
    PASS = "pass"
    BLOCK_NOT_YET = "block_not_yet"       # time gate
    BLOCK_EXPIRED = "block_expired"       # past valid_until
    BLOCK_DEPENDENCY = "block_dependency" # upstream token incomplete
    BLOCK_RESOURCE = "block_resource"     # system resources low
    BLOCK_RATE = "block_rate"             # rate limit

@dataclass
class Gate:
    gate_id: str
    gate_type: GateType
    config: dict                      # type-specific params
    token_id: str | None = None       # for dependency gates

@dataclass
class TokenLifecycle:
    token_id: str
    state: str                        # created → scheduled → released → claimed → completed | expired
    valid_after: int | None = None    # epoch ms
    valid_until: int | None = None
    depends_on: list[str] = field(default_factory=list)  # token IDs
    audit_trail: list[dict] = field(default_factory=list)

@runtime_checkable
class GateEngine(Protocol):
    def check_gates(self, token: TokenLifecycle) -> GateResult: ...
    def schedule_token(self, token_id: str, valid_after: int, valid_until: int | None = None) -> TokenLifecycle: ...
    def add_dependency(self, token_id: str, depends_on: str) -> TokenLifecycle: ...
    def release_token(self, token_id: str) -> TokenLifecycle: ...
    def get_pending_tokens(self) -> list[TokenLifecycle]: ...
```

**Current code location:** No existing implementation. The `valid_after` field exists in some token schemas but is not enforced programmatically.

---

### Module 4: Registry Manager

**Priority:** HIGH (single-writer fix is critical)
**Extract from:** `runtime/maestro_transport/maestro_transport.py` `LocalRegistry` class (lines 36-104)
**Dependencies:** None (independent)

```python
# nucleus/modules/registry_manager/interface.py

@dataclass
class AgentRecord:
    agentId: str
    webhookEndpoint: str
    capabilities: list[str] = field(default_factory=list)
    registeredAt: int = 0            # epoch ms
    lastSeen: int = 0                # epoch ms
    status: str = "active"           # active | stale | offline
    publicKey: str | None = None

@runtime_checkable
class RegistryManager(Protocol):
    def lookup(self, agent_id: str) -> AgentRecord | None: ...
    def register(self, agent_id: str, webhook_endpoint: str, capabilities: list[str] | None = None) -> AgentRecord: ...
    def unregister(self, agent_id: str) -> bool: ...
    def list_all(self) -> list[AgentRecord]: ...
    def update_last_seen(self, agent_id: str) -> bool: ...
    def set_status(self, agent_id: str, status: str) -> bool: ...
```

**Current code location:** `LocalRegistry` class in `runtime/maestro_transport/maestro_transport.py` (lines 36-104)

**Critical fix:** Single-writer enforcement. Currently 16 agents can concurrently write to `registry.json`. The new module uses file locking (already partially implemented with `fcntl.flock`) but adds:
1. Write-ahead log for crash recovery
2. Schema validation on every write
3. Reject writes that don't match schema
4. Atomic replace (write to temp file, rename)

**Data file:** `~/.maestro/registry.json` → `nucleus/data/registry.json` (same format, single-writer enforced)

---

### Module 5: Bridge Surface

**Priority:** MEDIUM
**Extract from:** `runtime/maestro_transport/maestro_gateway_bridge.py` (in `~/maestro-sdk/runtime/` — needs porting to real repo)
**Dependencies:** Message Router (1), Visibility Registry (13)

```python
# nucleus/modules/bridge_surface/interface.py

@dataclass
class SurfaceMessage:
    agent_id: str
    from_agent: str
    content: str
    summary: str
    msg_type: str                    # "direct", "broadcast", "system"
    platform: str = "telegram"       # "telegram", "discord", "p2n"

@dataclass
class SurfaceResult:
    ok: bool
    displayed: bool
    platform: str
    message_id: str | None = None
    detail: str | None = None

@runtime_checkable
class BridgeSurface(Protocol):
    def surface(self, message: SurfaceMessage) -> SurfaceResult: ...
    def get_display_mode(self, agent_id: str) -> str: ...  # "long" | "short" | "off"
    def set_display_mode(self, agent_id: str, mode: str) -> bool: ...
```

**Current code location:** `maestro_gateway_bridge.py` (368 lines, in `~/maestro-sdk/runtime/` — needs porting to `~/Projects/Maestro/bridge/`)

**Extraction notes:**
- Per-transport bundling: each agent gets its own bridge instance. One agent's bridge dies → only that agent loses visibility. No shared process SPOF.
- Platform adapters (Telegram, Discord, P2N fallback) are pluggable
- Visibility check happens in bridge, not transport

---

### Module 6: Intent Classifier

**Priority:** HIGH (eliminates 5 loop guards)
**Extract from:** New module (replaces ACK pattern matching)
**Dependencies:** None (independent — can be first extraction)

```python
# nucleus/modules/intent_classifier/interface.py
from enum import Enum

class Intent(Enum):
    WORK = "work"           # directive, task, spec — requires processing
    ACK = "ack"             # acknowledgment — suppress reply
    QUERY = "query"         # question — requires answer
    STATUS = "status"       # status report — log, don't process
    SYSTEM = "system"       # health check, heartbeat, registry update
    UNKNOWN = "unknown"     # fallback

@dataclass
class IntentResult:
    intent: Intent
    confidence: float           # 0.0 - 1.0
    should_reply: bool
    should_surface: bool
    matched_rule: str           # which rule fired

@runtime_checkable
class IntentClassifier(Protocol):
    def classify(self, message: MessageEnvelope) -> IntentResult: ...
    def add_rule(self, pattern: str, intent: Intent, should_reply: bool, should_surface: bool) -> str: ...  # returns rule_id
    def remove_rule(self, rule_id: str) -> bool: ...
```

**Current code location:** `_ack_pattern` regex (lines 169-172 in `maestro_transport.py`) + scattered `if "ack" in content.lower()` checks across the codebase

**Extraction notes:**
- Replaces 5 separate loop guards with one classification step
- `intent` field added to `MessageEnvelope` — sender declares, transport enforces
- Classification rules are declarative, not hardcoded regexes
- Default rules:
  - Content < 80 chars + matches ACK patterns → `ACK`, no reply
  - Content starts with "Subject:" + contains task language → `WORK`, reply
  - Content is JSON with `status` field → `STATUS`, no reply
  - Content is health check → `SYSTEM`, no reply

---

### Module 7: Resource Monitor

**Priority:** MEDIUM
**Extract from:** New module (replaces cron-based resource checking)
**Dependencies:** None (independent)

```python
# nucleus/modules/resource_monitor/interface.py

@dataclass
class ResourceState:
    memory_total_mb: int
    memory_available_mb: int
    memory_percent: float
    cpu_percent: float
    disk_free_gb: float
    load_average_1m: float
    timestamp: int

@dataclass
class ResourceThreshold:
    min_memory_available_mb: int = 512
    max_cpu_percent: float = 90.0
    min_disk_free_gb: float = 1.0
    max_load_average: float = 10.0

@runtime_checkable
class ResourceMonitor(Protocol):
    def check_resources(self, thresholds: ResourceThreshold | None = None) -> tuple[bool, ResourceState]: ...
    def get_current_state(self) -> ResourceState: ...
    def set_thresholds(self, thresholds: ResourceThreshold) -> None: ...
```

**Current code location:** `~/.maestro/scripts/resource_state_writer.py` (cron-based, writes to BB) + `~/.maestro/blackboards/resource_state.json`

**Extraction notes:**
- In-process `/proc/meminfo` read — no cron, no BB, no staleness
- Called before processing any message
- If resources below threshold, reject with `BLOCK_RESOURCE` gate result
- Replaces the cron-based `resource_state_writer.py` entirely

---

### Module 8: Task Lifecycle

**Priority:** MEDIUM
**Extract from:** `runtime/maestro_transport/checklist_manager.py` + scattered task state logic
**Dependencies:** None (independent)

```python
# nucleus/modules/task_lifecycle/interface.py
from enum import Enum

class TaskState(Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"

# Valid transitions
TRANSITIONS = {
    TaskState.PENDING:     [TaskState.CLAIMED, TaskState.CANCELLED],
    TaskState.CLAIMED:     [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.IN_PROGRESS: [TaskState.DONE, TaskState.BLOCKED, TaskState.CANCELLED],
    TaskState.BLOCKED:     [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.DONE:        [],  # terminal
    TaskState.CANCELLED:   [],  # terminal
}

@dataclass
class Task:
    task_id: str
    agent_id: str
    description: str
    state: TaskState
    created_at: int
    started_at: int | None = None
    completed_at: int | None = None
    result: str | None = None
    artifacts: list[str] = field(default_factory=list)
    parent_task_id: str | None = None

@runtime_checkable
class TaskLifecycle(Protocol):
    def create_task(self, agent_id: str, description: str, parent_task_id: str | None = None) -> Task: ...
    def transition(self, task_id: str, new_state: TaskState) -> Task: ...  # validates transition
    def cancel_all(self, agent_id: str) -> list[Task]: ...
    def get_active_tasks(self, agent_id: str) -> list[Task]: ...
    def get_task(self, task_id: str) -> Task | None: ...
```

**Current code location:** `checklist_manager.py` (159 lines) — has `create_checklist`, `update_item`, `cancel_checklist` but no explicit state machine

**Extraction notes:**
- `CANCEL_ALL` directive: transport receives it → task lifecycle cancels all active tasks for that agent → agent executes clean shutdown of each
- State transitions are validated — can't go from DONE to IN_PROGRESS
- Replaces the implicit "pending/done" model in checklist_manager

---

### Module 9: Config Generator

**Priority:** MEDIUM
**Extract from:** New module (replaces 16 hand-maintained config files)
**Dependencies:** Port Authority (10)

```python
# nucleus/modules/config_generator/interface.py

@dataclass
class AgentConfig:
    agentId: str
    port: int                       # transport port
    hermesApiUrl: str
    hermesApiKey: str
    conversation: str
    registryPath: str
    version: str
    knownPeers: dict[str, str]
    surfaceToGateway: bool
    gatewayBridgeUrl: str
    dm_policy: dict | None = None
    registry_signer_public_key: str | None = None

@dataclass
class ConfigTemplate:
    """Base template with defaults. Overrides are agent-specific."""
    version: str = "3.2"
    hermesApiKey: str = "maestro-local-dev"
    registryPath: str = "~/.maestro/registry.json"
    surfaceToGateway: bool = True
    gatewayBridgeUrl: str = "http://127.0.0.1:8644/maestro/notify"

@runtime_checkable
class ConfigGenerator(Protocol):
    def generate(self, agent_id: str, overrides: dict | None = None) -> AgentConfig: ...
    def validate(self, config: AgentConfig) -> list[str]: ...  # returns list of issues
    def write(self, agent_id: str, config: AgentConfig) -> str: ...  # returns path
    def regenerate_all(self) -> dict[str, AgentConfig]: ...
```

**Current code location:** 16 hand-maintained files at `~/.maestro/configs/<agent>.json`

**Extraction notes:**
- Template + overrides model: add a field to the template → all agents get it on next restart
- Port assignment comes from Port Authority — no manual port entry
- `knownPeers` auto-populated from Registry Manager
- Eliminates the 16-file config drift problem

---

### Module 10: Port Authority

**Priority:** HIGH (enforced at startup)
**Extract from:** `~/.maestro/port_map_loader.py` + `~/.maestro/verify_ports.py`
**Dependencies:** None (independent)

```python
# nucleus/modules/port_authority/interface.py

@dataclass
class PortAssignment:
    agent_id: str
    transport_port: int
    gateway_port: int

@runtime_checkable
class PortAuthority(Protocol):
    def resolve(self, agent_id: str) -> PortAssignment: ...
    def assign(self, agent_id: str, transport_port: int, gateway_port: int) -> PortAssignment: ...
    def verify(self) -> tuple[bool, list[str]]: ...  # (all_ok, [error_messages])
    def list_all(self) -> list[PortAssignment]: ...
    def is_port_available(self, port: int) -> bool: ...
```

**Current code location:** `~/.maestro/port_map_loader.py` (61 lines) + `~/.maestro/verify_ports.py` (42 lines)

**Extraction notes:**
- Single source of truth: `~/.maestro/port_map.json` → `nucleus/data/port_map.json`
- Enforced at startup: mismatch between config and port_map → refuse to boot
- `verify_ports.py` logic integrated: checks `ss -tlnp` against port_map
- Eliminates "wrong port → silent failure" class of bugs

---

### Module 11: Dead Letter Queue

**Priority:** LOW (quality of life)
**Extract from:** New module
**Dependencies:** Message Router (1)

```python
# nucleus/modules/dead_letter_queue/interface.py

@dataclass
class DeadLetter:
    letter_id: str
    original_message: MessageEnvelope
    failure_reason: str
    enqueued_at: int
    ttl: int = 3600                 # 1 hour default
    retry_count: int = 0
    max_retries: int = 3
    sender_notified: bool = False

@runtime_checkable
class DeadLetterQueue(Protocol):
    def enqueue(self, message: MessageEnvelope, reason: str, ttl: int = 3600) -> DeadLetter: ...
    def dequeue(self, letter_id: str) -> DeadLetter | None: ...
    def retry(self, letter_id: str) -> DeliveryResult: ...
    def purge_expired(self) -> int: ...  # returns count purged
    def get_queue_size(self) -> int: ...
    def notify_sender(self, letter: DeadLetter) -> bool: ...
```

**Current code location:** `~/.maestro/scripts/dead_letter_watchdog.py` (cron-based, passive)

**Extraction notes:**
- Active queue — messages that fail delivery are enqueued, not silently dropped
- Sender notified on enqueue: "Your message to X failed — will retry for 1 hour"
- 1-hour TTL, 3 retries with exponential backoff
- Replaces the passive watchdog script

---

### Module 12: Session Checkpoint

**Priority:** MEDIUM
**Extract from:** New module (no current implementation)
**Dependencies:** Task Lifecycle (8)

```python
# nucleus/modules/session_checkpoint/interface.py

@dataclass
class SessionState:
    agent_id: str
    session_id: str
    active_tasks: list[str]         # task IDs
    context_summary: str            # compressed context
    last_message_id: str | None
    checkpointed_at: int
    version: int

@runtime_checkable
class SessionCheckpoint(Protocol):
    def save(self, agent_id: str, state: SessionState) -> str: ...  # returns checkpoint_id
    def restore(self, agent_id: str) -> SessionState | None: ...
    def list_checkpoints(self, agent_id: str) -> list[SessionState]: ...
    def prune(self, agent_id: str, keep: int = 5) -> int: ...  # keep last N
```

**Current code location:** None. Agents currently lose all context on restart.

**Extraction notes:**
- Called on transport shutdown (SIGTERM handler) and startup
- Agent knows what it was doing when it comes back
- Checkpoints stored at `nucleus/data/checkpoints/{agent_id}/{timestamp}.json`
- Pruning keeps last 5 checkpoints per agent

---

### Module 13: Visibility Registry

**Priority:** LOW
**Extract from:** `~/.maestro/maestro_visibility.json` + bridge display logic
**Dependencies:** None (independent)

```python
# nucleus/modules/visibility_registry/interface.py

@dataclass
class VisibilityConfig:
    agent_id: str
    display_mode: str               # "long" | "short" | "off"
    surface_inbound: bool = True
    surface_outbound: bool = True
    surface_system: bool = False     # health checks, heartbeats
    generated_at: int = 0

@runtime_checkable
class VisibilityRegistry(Protocol):
    def check(self, agent_id: str, direction: str) -> tuple[bool, str]: ...  # (visible, mode)
    def set_mode(self, agent_id: str, mode: str) -> VisibilityConfig: ...
    def generate_for_agent(self, agent_id: str) -> VisibilityConfig: ...
    def list_all(self) -> list[VisibilityConfig]: ...
```

**Current code location:** `~/.maestro/maestro_visibility.json` + `_load_visibility()` in bridge

**Extraction notes:**
- Single file, generated per-agent
- Replaces the two-file visibility system (old `maestro_visibility.json` + per-agent config)
- Generated from template on agent creation

---

### Module 14: Agent Lifecycle

**Priority:** MEDIUM
**Extract from:** `runtime/cli.py` (agent spin-up commands) + `runtime/run_agent.py` (agent process)
**Dependencies:** Config Generator (9), Port Authority (10), Registry Manager (4)

```python
# nucleus/modules/agent_lifecycle/interface.py

@dataclass
class AgentSpec:
    agent_id: str
    display_name: str
    role: str
    model: str
    provider: str
    transport_port: int | None = None   # auto-assigned if None
    gateway_port: int | None = None

@dataclass
class AgentCreateResult:
    agent_id: str
    config_path: str
    transport_port: int
    gateway_port: int
    systemd_unit: str
    warnings: list[str]

@runtime_checkable
class AgentLifecycle(Protocol):
    def create(self, spec: AgentSpec) -> AgentCreateResult: ...
    def destroy(self, agent_id: str) -> bool: ...
    def list_agents(self) -> list[AgentSpec]: ...
    def health_check(self, agent_id: str) -> tuple[bool, str]: ...  # (healthy, detail)
    def restart(self, agent_id: str) -> bool: ...
```

**Current code location:** 14-step manual process scattered across `cli.py`, `run_agent.py`, and shell scripts

**Extraction notes:**
- `maestro agent create songbird --model deepseek-v4-pro --role cto` → one command
- Auto-assigns ports from Port Authority
- Generates config from Config Generator
- Registers in Registry Manager
- Creates systemd unit
- The 14 manual steps collapse into one command

---

### Module 15: Key Authority

**Priority:** HIGH (security — blocks DM Enforcer)
**Extract from:** New module (no current implementation)
**Dependencies:** None (independent — can be extracted early)

```python
# nucleus/modules/key_authority/interface.py

@dataclass
class KeyPair:
    agent_id: str
    public_key: str                 # Ed25519 hex
    private_key_encrypted: str      # AES-256-GCM encrypted
    created_at: int
    key_id: str                     # unique key identifier

@dataclass
class SignedToken:
    token_id: str
    payload: dict
    signature: str                  # Ed25519 signature
    signer_agent_id: str
    signer_public_key: str
    issued_at: int
    expires_at: int | None

@dataclass
class VerificationResult:
    valid: bool
    reason: str                     # "ok" | "expired" | "key_mismatch" | "bad_signature" | "revoked"
    signer_agent_id: str | None

@runtime_checkable
class KeyAuthority(Protocol):
    # Key management
    def generate_keypair(self, agent_id: str) -> KeyPair: ...
    def get_public_key(self, agent_id: str) -> str | None: ...
    def rotate_keypair(self, agent_id: str) -> KeyPair: ...  # new key, old revoked
    
    # Signing (two-factor: encrypted key + bearer token)
    def sign(self, agent_id: str, payload: dict, bearer_token: str) -> SignedToken: ...
    def verify(self, token: SignedToken) -> VerificationResult: ...
    
    # Token issuance
    def issue_token(self, issuer_id: str, subject_id: str, scope: list[str], ttl_hours: int) -> SignedToken: ...
    def verify_issued_token(self, token_id: str) -> VerificationResult: ...  # post-issuance check
    
    # Revocation
    def revoke_key(self, agent_id: str, key_id: str) -> bool: ...
    def is_revoked(self, key_id: str) -> bool: ...
```

**Current code location:** None. Keys are manually managed. DM tokens are manually signed.

**Critical security design:**
- **Two-factor signing:** Encrypted private key (AES-256-GCM, key derived from agent-specific secret) + non-transferable bearer-bound token. Neither half alone is useful.
- **Signing flow:** Decrypt private key → sign payload → wipe key from memory. Private key is never stored in plaintext on disk.
- **Post-issuance verification:** Every issued token is validated before distribution. Eliminates "wrong private key" class of bugs (2026-06-24: Lexicon issued 11/12 DM tokens with mismatched key).
- **Key storage:** `nucleus/data/keys/{agent_id}.enc` — encrypted at rest
- **Revocation list:** `nucleus/data/revoked_keys.json`

---

### Module 16: Transport State Refresh

**Priority:** MEDIUM
**Extract from:** New module (no current implementation)
**Dependencies:** Message Router (1) — needs signal routing path

```python
# nucleus/modules/transport_state_refresh/interface.py

@dataclass
class RefreshSignal:
    agent_id: str
    signal_type: str                # "SIGHUP" | "REFRESH" | "CONFIG_CHANGE" | "TOKEN_UPDATE"
    timestamp: int
    payload: dict | None = None

@dataclass
class RefreshResult:
    agent_id: str
    ok: bool
    configs_reloaded: list[str]
    tokens_reloaded: list[str]
    errors: list[str]

@runtime_checkable
class TransportStateRefresh(Protocol):
    def refresh(self, agent_id: str) -> RefreshResult: ...
    def signal(self, agent_id: str, signal_type: str) -> bool: ...
    def get_last_refresh(self, agent_id: str) -> int | None: ...  # epoch ms
    def is_stale(self, agent_id: str, max_age_seconds: int = 300) -> bool: ...
```

**Current code location:** None. Transports load configs at startup and never refresh.

**Extraction notes:**
- Transport reloads tokens and configs on signal (SIGHUP or REFRESH directive)
- No restart required
- Eliminates stale in-memory state class of bugs (2026-06-24: Lexicon transport started before token update, rejected all messages for hours)
- Signal routing: Message Router receives REFRESH directive → routes to Transport State Refresh module → module signals the target transport

---

## 3. Data Schemas

### 3.1 Message Envelope (Canonical)

```json
{
  "id": "uuid-string",
  "type": "direct | broadcast | proxy | system",
  "sender": {"agentId": "string", "endpoint": "string?"},
  "recipient": {"agentId": "string", "endpoint": "string?"},
  "content": "string",
  "timestamp": 1719000000000,
  "version": "3.2",
  "intent": "work | ack | query | status | system | null",
  "inReplyTo": "uuid-string?",
  "stageId": "string?",
  "venueId": "string?",
  "ttl": 3600
}
```

### 3.2 Registry Entry

```json
{
  "agentId": "songbird",
  "webhookEndpoint": "http://127.0.0.1:3842/message",
  "capabilities": ["text-generation", "code-review"],
  "registeredAt": 1719000000000,
  "lastSeen": 1719000000000,
  "status": "active",
  "publicKey": "hex-string?"
}
```

### 3.3 Port Map

```json
{
  "version": "1.0.0",
  "last_updated": "2026-06-30T00:00:00Z",
  "agents": {
    "songbird": {"transport_port": 3842, "gateway_port": 8649},
    "proteus": {"transport_port": 3846, "gateway_port": 8645}
  },
  "bridge": {"port": 8644}
}
```

### 3.4 Agent Config (Generated)

```json
{
  "agentId": "songbird",
  "port": 3842,
  "hermesApiUrl": "http://127.0.0.1:8649",
  "hermesApiKey": "maestro-local-dev",
  "conversation": "maestro-songbird",
  "registryPath": "~/.maestro/registry.json",
  "version": "3.2",
  "knownPeers": {},
  "surfaceToGateway": true,
  "gatewayBridgeUrl": "http://127.0.0.1:8644/maestro/notify",
  "dm_policy": {
    "enabled": true,
    "token_dir": "~/.maestro/dm_tokens"
  }
}
```

---

## 4. Extraction Order & Dependency Graph

```
Phase 2a — Independent (can parallelize):
  ├── Module 6:  Intent Classifier        ← NO dependencies
  ├── Module 4:  Registry Manager         ← NO dependencies
  ├── Module 7:  Resource Monitor         ← NO dependencies
  ├── Module 8:  Task Lifecycle            ← NO dependencies
  ├── Module 10: Port Authority            ← NO dependencies
  ├── Module 13: Visibility Registry      ← NO dependencies
  └── Module 15: Key Authority             ← NO dependencies

Phase 2b — Single dependency:
  ├── Module 1:  Message Router            ← depends on: Intent Classifier (6)
  ├── Module 11: Dead Letter Queue        ← depends on: Message Router (1)
  ├── Module 12: Session Checkpoint       ← depends on: Task Lifecycle (8)
  └── Module 16: Transport State Refresh ← depends on: Message Router (1)

Phase 2c — Multi dependency:
  ├── Module 2:  DM Enforcer              ← depends on: Key Authority (15), Registry Manager (4)
  ├── Module 3:  Gate Engine              ← depends on: Registry Manager (4)
  ├── Module 5:  Bridge Surface           ← depends on: Message Router (1), Visibility Registry (13)
  ├── Module 9:  Config Generator         ← depends on: Port Authority (10)
  └── Module 14: Agent Lifecycle          ← depends on: Config Generator (9), Port Authority (10), Registry Manager (4)
```

### Recommended Extraction Sequence

1. **Intent Classifier** — smallest, no deps, eliminates 5 loop guards immediately
2. **Registry Manager** — single-writer fix, no deps, prevents corruption
3. **Port Authority** — no deps, enforced at startup
4. **Key Authority** — no deps, blocks DM Enforcer
5. **Resource Monitor** — no deps, in-process check
6. **Task Lifecycle** — no deps, explicit state machine
7. **Visibility Registry** — no deps, single file
8. **Message Router** — depends on Intent Classifier
9. **Dead Letter Queue** — depends on Message Router
10. **Session Checkpoint** — depends on Task Lifecycle
11. **Transport State Refresh** — depends on Message Router
12. **DM Enforcer** — depends on Key Authority + Registry Manager
13. **Gate Engine** — depends on Registry Manager
14. **Bridge Surface** — depends on Message Router + Visibility Registry
15. **Config Generator** — depends on Port Authority
16. **Agent Lifecycle** — depends on Config Generator + Port Authority + Registry Manager

---

## 5. File Layout — Target Structure

```
~/Projects/Maestro/
├── nucleus/
│   ├── __init__.py
│   ├── registry.py              # Module registry + message bus
│   ├── data/                    # Runtime data (single-writer enforced)
│   │   ├── registry.json
│   │   ├── port_map.json
│   │   ├── visibility.json
│   │   ├── dm_tokens/
│   │   ├── keys/
│   │   ├── revoked_keys.json
│   │   ├── dead_letters/
│   │   └── checkpoints/
│   └── modules/
│       ├── message_router/
│       │   ├── __init__.py
│       │   ├── interface.py
│       │   ├── router.py
│       │   ├── dedup.py
│       │   ├── reply.py
│       │   ├── schema.py
│       │   └── test_router.py
│       ├── dm_enforcer/
│       │   ├── __init__.py
│       │   ├── interface.py
│       │   ├── enforcer.py
│       │   ├── token_store.py
│       │   ├── schema.py
│       │   └── test_enforcer.py
│       ├── gate_engine/
│       │   └── ...
│       ├── registry_manager/
│       │   └── ...
│       ├── bridge_surface/
│       │   ├── __init__.py
│       │   ├── interface.py
│       │   ├── bridge.py
│       │   ├── platforms/
│       │   │   ├── telegram.py
│       │   │   ├── discord.py
│       │   │   └── p2n.py
│       │   ├── schema.py
│       │   └── test_bridge.py
│       ├── intent_classifier/
│       │   └── ...
│       ├── resource_monitor/
│       │   └── ...
│       ├── task_lifecycle/
│       │   └── ...
│       ├── config_generator/
│       │   └── ...
│       ├── port_authority/
│       │   └── ...
│       ├── dead_letter_queue/
│       │   └── ...
│       ├── session_checkpoint/
│       │   └── ...
│       ├── visibility_registry/
│       │   └── ...
│       ├── agent_lifecycle/
│       │   └── ...
│       ├── key_authority/
│       │   └── ...
│       └── transport_state_refresh/
│           └── ...
├── runtime/                    # Existing — shrinks as modules extract
├── src/                        # TypeScript SDK (unchanged)
├── bridge/                     # Bridge daemon (extracted from runtime)
├── cli/                        # CLI (extracted from runtime/cli.py)
└── live/                       # Production runtime files
```

---

## 6. Migration Compatibility Protocol

Every module extraction follows this protocol:

### Pre-extraction
1. Snapshot all running transport configs: `cp -r ~/.maestro/configs ~/.maestro/configs.bak-$(date +%Y%m%d)`
2. Verify all agent health endpoints: `python nucleus/modules/port_authority/verify.py`
3. Confirm all agents can message: send test ping to each agent

### Extraction Window
1. Disable DM policy on target transport (set `dm_policy.enabled = false`)
2. Extract module code from monolith → nucleus module
3. Deploy: restart affected transport with new module path
4. Verify: health check + test message

### Post-extraction
1. Re-enable DM policy
2. Run full token validation sweep: `python nucleus/modules/key_authority/verify_all.py`
3. Confirm all agents can message
4. Commit with message: `extract(nucleus): <module_name> from <source_file>`

### Rollback
If any agent fails health check or message delivery:
1. Revert to snapshot configs
2. Restart transport from pre-extraction binary
3. Window is per-module — a failed extraction doesn't block others

---

## 7. Phase Plan

| Phase | What | Who | Duration |
|-------|------|-----|----------|
| **0. Purge** | Remove stale forks (`maestro-protocol-backup-v0.2.0/`, `live/maestro_transports/` stale copies). Archive dead configs. Verify no notebooks remain. | Stormtrooper | 1 day |
| **1. Spec** | THIS DOCUMENT. Songbird finalizes module boundaries, interface contracts, extraction order. Proteus reviews for feasibility. | Songbird + Proteus | Done |
| **2a. Extract (Independent)** | Modules 6, 4, 10, 15, 7, 8, 13 — all independent, can parallelize. 3 workers × 2-3 modules each. | Proteus orchestrating, Stormtrooper + generalists executing | 3-5 days |
| **2b. Extract (Single-dep)** | Modules 1, 11, 12, 16 — each depends on one Phase 2a module. | Proteus + workers | 2-3 days |
| **2c. Extract (Multi-dep)** | Modules 2, 3, 5, 9, 14 — complex dependencies. | Proteus + Songbird review | 3-5 days |
| **3. Integrate** | Wire modules together. Kill monoliths (`cli.py` split, `maestro_transport.py` → router). Single canonical source. | Proteus + Songbird | 2-3 days |
| **4. Harden** | Schema validation on all data files. Systemd units for everything. Resource monitoring in-process. Key Authority encrypted storage. Transport state refresh signal handling. 72-hour stability test. | Proteus + Songbird | 3-5 days |

**Total estimated:** 14-22 days (2-3 weeks with parallelization)

---

## 8. Success Criteria

1. **All 16 modules extracted** with passing unit tests
2. **Zero monoliths over 2,000 lines** — `cli.py`, `run_agent.py`, `gateway/run.py` all split
3. **Single-writer registry** — no corruption on concurrent writes
4. **Port enforcement at startup** — mismatch = refuse to boot
5. **Config generation** — add field to template → all agents get it
6. **Agent create/destroy** — one command, not 14 manual steps
7. **72-hour stability** — no intervention required, no silent failures
8. **All existing functionality preserved** — agents message, bridge surfaces, checklists work
9. **Migration compatibility protocol followed** — no mesh-wide downtime

---

## 9. Open Questions

1. **Nucleus process model:** Does the nucleus run as a separate daemon, or is it embedded in each transport? Recommendation: embedded — each transport loads the nucleus as a library. No new daemon to manage. Trade-off: module state is per-transport, not shared. For modules that need shared state (Registry Manager), use file-backed storage with locking.

2. **Python version:** Current runtime uses Python 3.11. Target 3.11+ for `dataclasses`, `Protocol`, `Literal` support.

3. **TypeScript SDK impact:** The `src/` TypeScript SDK is unaffected by this extraction — it talks to transports via HTTP POST. The API doesn't change. Only the Python runtime internals change.

4. **Backward compatibility:** Existing `~/.maestro/` data files (registry.json, port_map.json, configs/) must be readable by the new modules. Format migration scripts needed for any schema changes.

5. **Testing strategy:** Each module gets unit tests. Integration tests verify module-to-module communication. End-to-end test: create agent → send message → verify delivery → destroy agent.

---

*End of Phase 1 Technical Specification. For Proteus review and extraction planning.*
