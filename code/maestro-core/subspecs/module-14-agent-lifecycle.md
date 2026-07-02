# Module 14: Agent Lifecycle — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/agent_lifecycle/interface.py
from dataclasses import dataclass, field

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

class AgentLifecycle:
    def create(self, spec: AgentSpec) -> AgentCreateResult: ...
    def destroy(self, agent_id: str) -> bool: ...
    def list_agents(self) -> list[AgentSpec]: ...
    def health_check(self, agent_id: str) -> tuple[bool, str]: ...  # (healthy, detail)
    def restart(self, agent_id: str) -> bool: ...
```

### Key Behavior
- **create:** Full agent creation pipeline:
  1. Assign ports from Port Authority (if not specified)
  2. Generate config from Config Generator
  3. Register in Registry Manager
  4. Generate systemd unit name
  5. Return AgentCreateResult
- **destroy:** Remove agent from registry, delete config, release ports. Returns True if agent existed.
- **list_agents:** Return all registered agents as AgentSpec list.
- **health_check:** Check if agent is registered and recently seen. Returns (healthy, detail).
- **restart:** Mark agent for restart. Returns True if agent exists.
- **In-memory store** — no file I/O needed for this module (delegates to other modules)

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/agent_lifecycle/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/agent_lifecycle/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/agent_lifecycle/lifecycle.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/agent_lifecycle/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/agent_lifecycle/test_lifecycle.py`

### Dependencies
- Config Generator (M9) — in-flight, being built by Cactus Jack. Use the interface contract from `/home/andjesse/Projects/Maestro/nucleus/subspecs/module-09-config-generator.md` as reference.
- Port Authority (M10) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/port_authority/`. Import for port assignment.
- Registry Manager (M4) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/registry_manager/`. Import for agent registration.

### Success Criteria
- create() returns AgentCreateResult with all fields populated
- create() auto-assigns ports when not specified
- destroy() removes agent and returns True
- destroy() returns False for unknown agent
- list_agents() returns all registered agents
- health_check() returns (True, "healthy") for active agents
- health_check() returns (False, reason) for stale/unknown agents
- Unit tests: create, destroy, list, health_check, restart, edge cases
