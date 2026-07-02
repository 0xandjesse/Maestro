# Module 16: Transport State Refresh — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/transport_state_refresh/interface.py
from dataclasses import dataclass, field

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

class TransportStateRefresh:
    def refresh(self, agent_id: str) -> RefreshResult: ...
    def signal(self, agent_id: str, signal_type: str) -> bool: ...
    def get_last_refresh(self, agent_id: str) -> int | None: ...  # epoch ms
    def is_stale(self, agent_id: str, max_age_seconds: int = 300) -> bool: ...
```

### Key Behavior
- **refresh:** Simulate a config reload for an agent. Track which configs and tokens were reloaded. Return RefreshResult.
- **signal:** Record a refresh signal for an agent. Returns True if signal was accepted.
- **get_last_refresh:** Return epoch ms of last refresh for agent, or None if never refreshed.
- **is_stale:** Return True if agent hasn't been refreshed within max_age_seconds.
- **In-memory store** — no file I/O needed for this module
- **Signal types:** SIGHUP (reload all), REFRESH (soft reload), CONFIG_CHANGE (config files changed), TOKEN_UPDATE (DM tokens updated)

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/transport_state_refresh/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/transport_state_refresh/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/transport_state_refresh/refresh.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/transport_state_refresh/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/transport_state_refresh/test_refresh.py`

### Dependencies
- Message Router (M1) — conceptually depends on it for signal routing, but for this standalone module, no actual import needed. Build independently.

### Success Criteria
- refresh() returns RefreshResult with correct agent_id
- signal() records signal and returns True
- get_last_refresh() returns timestamp or None
- is_stale() correctly identifies stale agents
- Multiple signal types supported
- Unit tests: refresh, signal, get_last_refresh, is_stale, multiple agents, edge cases
