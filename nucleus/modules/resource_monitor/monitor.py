"""ResourceMonitor — in-process system resource checks via /proc and statvfs."""

import os
import time
from typing import Optional

from nucleus.modules.resource_monitor.interface import ResourceState, ResourceThreshold


def _parse_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a dict of key -> kB values."""
    result: dict[str, int] = {}
    with open("/proc/meminfo", "r") as f:
        for line in f:
            if ":" in line:
                key, val = line.split(":", 1)
                # Value is like " 123456 kB"
                parts = val.strip().split()
                if parts:
                    result[key.strip()] = int(parts[0])
    return result


def _read_cpu_times() -> list[int]:
    """Read aggregate CPU times from /proc/stat (first line)."""
    with open("/proc/stat", "r") as f:
        line = f.readline()
    # cpu  user nice system idle iowait irq softirq steal guest guest_nice
    parts = line.strip().split()
    return [int(x) for x in parts[1:]]


def _read_loadavg() -> float:
    """Read 1-minute load average from /proc/loadavg."""
    with open("/proc/loadavg", "r") as f:
        return float(f.readline().split()[0])


def _get_disk_free_gb(path: str = "/") -> float:
    """Get free disk space in GB for the given path."""
    stat = os.statvfs(path)
    return (stat.f_frsize * stat.f_bavail) / (1024 ** 3)


class ResourceMonitor:
    """Monitors system resources: memory, CPU, disk, load average.

    Reads from /proc filesystem and os.statvfs. Fully in-process — no cron,
    no blackboard, no staleness concerns.
    """

    def __init__(self, thresholds: ResourceThreshold | None = None) -> None:
        self._thresholds = thresholds or ResourceThreshold()
        self._prev_cpu_times: list[int] | None = None
        self._prev_cpu_ts: float | None = None

    def set_thresholds(self, thresholds: ResourceThreshold) -> None:
        """Replace the current threshold configuration."""
        self._thresholds = thresholds

    def get_current_state(self) -> ResourceState:
        """Read current system metrics and return a ResourceState snapshot."""
        mem = _parse_meminfo()
        memory_total_kb = mem.get("MemTotal", 0)
        memory_available_kb = mem.get("MemAvailable", 0)

        memory_total_mb = memory_total_kb // 1024
        memory_available_mb = memory_available_kb // 1024
        memory_percent = (
            ((memory_total_kb - memory_available_kb) / memory_total_kb) * 100.0
            if memory_total_kb > 0
            else 0.0
        )

        cpu_percent = self._compute_cpu_percent()
        disk_free_gb = _get_disk_free_gb()
        load_average_1m = _read_loadavg()

        return ResourceState(
            memory_total_mb=memory_total_mb,
            memory_available_mb=memory_available_mb,
            memory_percent=round(memory_percent, 2),
            cpu_percent=round(cpu_percent, 2),
            disk_free_gb=round(disk_free_gb, 2),
            load_average_1m=round(load_average_1m, 2),
            timestamp=int(time.time()),
        )

    def check_resources(
        self, thresholds: ResourceThreshold | None = None
    ) -> tuple[bool, ResourceState]:
        """Check resources against thresholds. Returns (ok, state).

        ok is True when all metrics are within their thresholds.
        """
        t = thresholds or self._thresholds
        state = self.get_current_state()

        ok = (
            state.memory_available_mb >= t.min_memory_available_mb
            and state.cpu_percent <= t.max_cpu_percent
            and state.disk_free_gb >= t.min_disk_free_gb
            and state.load_average_1m <= t.max_load_average
        )
        return ok, state

    def _compute_cpu_percent(self) -> float:
        """Compute CPU usage percentage between two /proc/stat snapshots.

        On first call, returns 0.0 (no prior snapshot to diff against).
        """
        now = time.time()
        current_times = _read_cpu_times()

        if self._prev_cpu_times is None or self._prev_cpu_ts is None:
            self._prev_cpu_times = current_times
            self._prev_cpu_ts = now
            return 0.0

        prev_total = sum(self._prev_cpu_times)
        curr_total = sum(current_times)
        total_delta = curr_total - prev_total

        if total_delta <= 0:
            self._prev_cpu_times = current_times
            self._prev_cpu_ts = now
            return 0.0

        prev_idle = self._prev_cpu_times[3] + self._prev_cpu_times[4]  # idle + iowait
        curr_idle = current_times[3] + current_times[4]
        idle_delta = curr_idle - prev_idle

        self._prev_cpu_times = current_times
        self._prev_cpu_ts = now

        return ((total_delta - idle_delta) / total_delta) * 100.0
