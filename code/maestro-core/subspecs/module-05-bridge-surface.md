# Module 5: Bridge Surface — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/bridge_surface/interface.py
from dataclasses import dataclass, field

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

class BridgeSurface:
    def surface(self, message: SurfaceMessage) -> SurfaceResult: ...
    def get_display_mode(self, agent_id: str) -> str: ...  # "long" | "short" | "off"
    def set_display_mode(self, agent_id: str, mode: str) -> bool: ...
```

### Key Behavior
- **surface:** Route a message to the appropriate platform for display. Check visibility before surfacing.
- **get_display_mode:** Query visibility registry for agent's display mode.
- **set_display_mode:** Update agent's display mode in visibility registry.
- **Platform routing:** Based on `platform` field, route to correct adapter (telegram, discord, p2n).
- **Visibility check:** Before surfacing, check if agent's visibility allows this message type.
- **In-memory store** — no file I/O needed for this module (delegates to Visibility Registry for persistence)
- **Platform adapters:** Stub implementations that return SurfaceResult with ok=True (no actual platform calls)

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/bridge_surface/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/bridge_surface/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/bridge_surface/bridge.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/bridge_surface/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/bridge_surface/test_bridge.py`

### Dependencies
- Message Router (M1) — in-flight, being built by Cee-Lo at `/home/andjesse/Projects/Maestro/nucleus/modules/message_router/`. Use the interface contract from `/home/andjesse/Projects/Maestro/nucleus/subspecs/module-01-message-router.md` as reference.
- Visibility Registry (M13) — built at `/home/andjesse/Projects/Maestro/nucleus/modules/visibility_registry/`. Import for display mode checks.

### Success Criteria
- surface() returns SurfaceResult with correct platform
- get_display_mode() returns mode from visibility registry
- set_display_mode() updates visibility registry
- Platform routing works for all three platforms
- Visibility check prevents surfacing when mode is "off"
- Unit tests: surface, display modes, platform routing, visibility gating
