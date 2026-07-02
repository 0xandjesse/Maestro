# Module 4: Registry Manager — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/registry_manager/interface.py
from dataclasses import dataclass, field

@dataclass
class AgentRecord:
    agentId: str
    webhookEndpoint: str
    capabilities: list[str] = field(default_factory=list)
    registeredAt: int = 0
    lastSeen: int = 0
    status: str = "active"
    publicKey: str | None = None

class RegistryManager:
    def __init__(self, registry_path: str = "nucleus/data/registry.json"): ...
    def lookup(self, agent_id: str) -> AgentRecord | None: ...
    def register(self, agent_id: str, webhook_endpoint: str, capabilities: list[str] | None = None) -> AgentRecord: ...
    def unregister(self, agent_id: str) -> bool: ...
    def list_all(self) -> list[AgentRecord]: ...
    def update_last_seen(self, agent_id: str) -> bool: ...
    def set_status(self, agent_id: str, status: str) -> bool: ...
```

### Critical Fix: Single-Writer Enforcement
1. File locking via `fcntl.flock` (exclusive lock on write)
2. Write-ahead log for crash recovery
3. Schema validation on every write — reject malformed entries
4. Atomic replace: write to temp file, `os.rename()` to target

### Current Code to Extract From
`runtime/maestro_transport/maestro_transport.py` — `LocalRegistry` class (lines 36-104)

### Files to Create
- `nucleus/modules/registry_manager/__init__.py`
- `nucleus/modules/registry_manager/interface.py`
- `nucleus/modules/registry_manager/manager.py`
- `nucleus/modules/registry_manager/schema.py`
- `nucleus/modules/registry_manager/test_manager.py`

### Dependencies
None — fully independent.

### Success Criteria
- Single-writer lock prevents concurrent writes
- Schema validation rejects malformed entries
- Atomic replace (no partial writes)
- Read existing `~/.maestro/registry.json` correctly
- Unit tests: concurrent write test, schema validation test, crash recovery test
