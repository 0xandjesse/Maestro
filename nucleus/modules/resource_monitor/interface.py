"""Interface contract for Resource Monitor module."""

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

    def validate(self) -> None:
        """Raise ValueError if any threshold is nonsensical."""
        if self.min_memory_available_mb < 0:
            raise ValueError("min_memory_available_mb must be >= 0")
        if not 0.0 <= self.max_cpu_percent <= 100.0:
            raise ValueError("max_cpu_percent must be between 0 and 100")
        if self.min_disk_free_gb < 0:
            raise ValueError("min_disk_free_gb must be >= 0")
        if self.max_load_average < 0:
            raise ValueError("max_load_average must be >= 0")
