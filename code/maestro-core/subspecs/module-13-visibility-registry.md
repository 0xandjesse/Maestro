# Module 13: Visibility Registry — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/visibility_registry/interface.py
from dataclasses import dataclass

@dataclass
class VisibilityConfig:
    agent_id: str
    display_mode: str               # "long" | "short" | "off"
    surface_inbound: bool = True
    surface_outbound: bool = True
    surface_system: bool = False
    generated_at: int = 0

class VisibilityRegistry:
    def check(self, agent_id: str, direction: str) -> tuple[bool, str]: ...
    def set_mode(self, agent_id: str, mode: str) -> VisibilityConfig: ...
    def generate_for_agent(self, agent_id: str) -> VisibilityConfig: ...
    def list_all(self) -> list[VisibilityConfig]: ...
```

### Key Behavior
- Single file: `nucleus/data/visibility.json`
- `check(agent_id, "inbound")` → (visible, mode)
- `check(agent_id, "outbound")` → (visible, mode)
- Default: all agents "long" mode, inbound+outbound on, system off

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/visibility_registry/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/visibility_registry/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/visibility_registry/registry.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/visibility_registry/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/visibility_registry/test_registry.py`

### Dependencies
None — fully independent.

### Success Criteria
- Default config generated for any agent
- `check()` returns correct visibility for inbound/outbound
- `set_mode()` updates and persists
- Unit tests: default generation, mode switching, direction filtering
