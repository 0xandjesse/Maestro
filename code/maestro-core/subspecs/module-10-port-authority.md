# Module 10: Port Authority — Sub-spec
## Assigned to: Proteus (self)

### Interface Contract
```python
# nucleus/modules/port_authority/interface.py
from dataclasses import dataclass

@dataclass
class PortAssignment:
    agent_id: str
    transport_port: int
    gateway_port: int

class PortAuthority:
    def __init__(self, port_map_path: str = "/home/andjesse/Projects/Maestro/nucleus/data/port_map.json"): ...
    def resolve(self, agent_id: str) -> PortAssignment: ...
    def assign(self, agent_id: str, transport_port: int, gateway_port: int) -> PortAssignment: ...
    def verify(self) -> tuple[bool, list[str]]: ...
    def list_all(self) -> list[PortAssignment]: ...
    def is_port_available(self, port: int) -> bool: ...
```

### Key Behavior
- `verify()` checks `ss -tlnp` against port_map — mismatch = error
- Enforced at startup: config port != port_map → refuse to boot
- Single source of truth: `nucleus/data/port_map.json`
- Seed from existing `~/.maestro/port_map.json`

### Files to Create
- `nucleus/modules/port_authority/__init__.py`
- `nucleus/modules/port_authority/interface.py`
- `nucleus/modules/port_authority/authority.py`
- `nucleus/modules/port_authority/schema.py`
- `nucleus/modules/port_authority/test_authority.py`

### Dependencies
None — fully independent.

### Success Criteria
- Reads existing `~/.maestro/port_map.json`
- `verify()` checks actual port usage via `ss`
- `is_port_available()` correctly identifies free/busy ports
- Unit tests with mock port map data
