# Module 9: Config Generator — Sub-spec
## Assigned to: Cactus Jack

### Interface Contract
```python
# nucleus/modules/config_generator/interface.py
from dataclasses import dataclass, field

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

class ConfigGenerator:
    def generate(self, agent_id: str, overrides: dict | None = None) -> AgentConfig: ...
    def validate(self, config: AgentConfig) -> list[str]: ...  # returns list of issues
    def write(self, agent_id: str, config: AgentConfig) -> str: ...  # returns path
    def regenerate_all(self) -> dict[str, AgentConfig]: ...
```

### Key Behavior
- **generate:** Create AgentConfig from template + overrides. Auto-assign port from Port Authority. Auto-populate knownPeers from Registry Manager.
- **validate:** Check config for required fields, valid port range, valid URLs. Return list of issues (empty = valid).
- **write:** Write config to `nucleus/data/configs/{agent_id}.json`. Atomic write (temp file + rename).
- **regenerate_all:** Regenerate configs for all known agents. Returns dict of agent_id → AgentConfig.
- **Template + overrides model:** Start with ConfigTemplate defaults, apply agent-specific overrides.
- **Port assignment:** Query Port Authority for agent's transport port.
- **Known peers:** Query Registry Manager for all registered agents, build knownPeers dict.

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/config_generator/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/config_generator/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/config_generator/generator.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/config_generator/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/config_generator/test_generator.py`

### Dependencies
- Port Authority (M10) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/port_authority/`. Import for port assignment.

### Success Criteria
- generate() creates valid AgentConfig with correct defaults
- generate() applies overrides correctly
- validate() catches missing required fields
- validate() catches invalid port numbers
- write() creates config file with atomic write
- regenerate_all() produces configs for all agents
- Template defaults are applied when no overrides
- Unit tests: generate, validate, write, regenerate, overrides, edge cases
