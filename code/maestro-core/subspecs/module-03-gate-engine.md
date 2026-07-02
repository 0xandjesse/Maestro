# Module 3: Gate Engine — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/gate_engine/interface.py
from enum import Enum
from dataclasses import dataclass, field

class GateType(Enum):
    TIME = "time"
    DEPENDENCY = "dependency"
    RESOURCE = "resource"
    RATE = "rate"

class GateResult(Enum):
    PASS = "pass"
    BLOCK_NOT_YET = "block_not_yet"
    BLOCK_EXPIRED = "block_expired"
    BLOCK_DEPENDENCY = "block_dependency"
    BLOCK_RESOURCE = "block_resource"
    BLOCK_RATE = "block_rate"

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

class GateEngine:
    def check_gates(self, token: TokenLifecycle) -> GateResult: ...
    def schedule_token(self, token_id: str, valid_after: int, valid_until: int | None = None) -> TokenLifecycle: ...
    def add_dependency(self, token_id: str, depends_on: str) -> TokenLifecycle: ...
    def release_token(self, token_id: str) -> TokenLifecycle: ...
    def get_pending_tokens(self) -> list[TokenLifecycle]: ...
```

### Key Behavior
- **check_gates:** Evaluate all gates on a token. Returns first blocking result or PASS.
  - TIME gate: check valid_after/valid_until against current time
  - DEPENDENCY gate: check all depends_on tokens are in "completed" state
  - RESOURCE gate: check config thresholds (min_memory_mb, max_cpu_pct)
  - RATE gate: check tokens per minute limit
- **schedule_token:** Create a token with time gates. State = "scheduled".
- **add_dependency:** Add a dependency to a token. State = "scheduled" if dependencies exist.
- **release_token:** Mark token as "released" (ready for claiming).
- **get_pending_tokens:** Return all tokens not in terminal state (completed/expired).
- **In-memory store** — no file I/O needed for this module
- **State machine:** created → scheduled → released → claimed → completed | expired

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/gate_engine/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/gate_engine/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/gate_engine/engine.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/gate_engine/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/gate_engine/test_engine.py`

### Dependencies
- Registry Manager (M4) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/registry_manager/`. Import for agent lookup if needed.

### Success Criteria
- TIME gate: blocks before valid_after, passes after
- TIME gate: blocks after valid_until (expired)
- DEPENDENCY gate: blocks when dependency not completed
- DEPENDENCY gate: passes when all dependencies completed
- RESOURCE gate: blocks when resources below threshold
- RATE gate: blocks when rate limit exceeded
- Token lifecycle states transition correctly
- Unit tests: all gate types, state transitions, edge cases
