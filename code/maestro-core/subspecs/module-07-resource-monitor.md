# Module 7: Resource Monitor — Sub-spec
## Assigned to: Cee-Lo

### Interface Contract
```python
# nucleus/modules/resource_monitor/interface.py
from dataclasses import dataclass

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

class ResourceMonitor:
    def check_resources(self, thresholds: ResourceThreshold | None = None) -> tuple[bool, ResourceState]: ...
    def get_current_state(self) -> ResourceState: ...
    def set_thresholds(self, thresholds: ResourceThreshold) -> None: ...
```

### Key Behavior
- Reads `/proc/meminfo` for memory
- Reads `/proc/stat` for CPU
- Uses `os.statvfs` for disk
- Reads `/proc/loadavg` for load
- In-process — no cron, no BB, no staleness

### Files to Create (absolute paths)
- `/home/andjesse/Projects/Maestro/nucleus/modules/resource_monitor/__init__.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/resource_monitor/interface.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/resource_monitor/monitor.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/resource_monitor/schema.py`
- `/home/andjesse/Projects/Maestro/nucleus/modules/resource_monitor/test_monitor.py`

### Dependencies
None — fully independent. Linux-only (reads /proc).

### Success Criteria
- Reads real system metrics from /proc
- `check_resources()` returns (ok, state) tuple
- Thresholds are configurable
- Unit tests with mock /proc data
