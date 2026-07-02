"""Tests for ResourceMonitor — uses mock /proc data, no real system reads."""

import time
import unittest
from unittest.mock import patch, MagicMock

from nucleus.modules.resource_monitor.interface import ResourceState, ResourceThreshold
from nucleus.modules.resource_monitor.monitor import (
    ResourceMonitor,
    _parse_meminfo,
    _read_cpu_times,
    _read_loadavg,
    _get_disk_free_gb,
)


SAMPLE_MEMINFO = """MemTotal:       16384000 kB
MemFree:          800000 kB
MemAvailable:   12000000 kB
Buffers:          200000 kB
Cached:          4000000 kB
SwapCached:            0 kB
"""

SAMPLE_STAT_CPU = "cpu  100000 20000 30000 500000 10000 0 5000 0 0 0\n"
SAMPLE_LOADAVG = "0.50 0.40 0.30 1/256 9999\n"


def _make_mock_open(meminfo=SAMPLE_MEMINFO, stat_cpu=SAMPLE_STAT_CPU,
                    loadavg=SAMPLE_LOADAVG):
    """Return a mock_open that dispatches by filename."""
    def _side_effect(filename, *args, **kwargs):
        fname = str(filename)
        if "meminfo" in fname:
            return unittest.mock.mock_open(read_data=meminfo).return_value
        if "stat" in fname:
            return unittest.mock.mock_open(read_data=stat_cpu).return_value
        if "loadavg" in fname:
            return unittest.mock.mock_open(read_data=loadavg).return_value
        raise FileNotFoundError(f"Unexpected file: {fname}")
    return unittest.mock.MagicMock(side_effect=_side_effect)


def _make_mock_statvfs(disk_free_gb=10.0):
    """Return a mock statvfs with the given free disk space in GB."""
    mock_s = MagicMock()
    mock_s.f_frsize = 4096
    mock_s.f_bavail = int(disk_free_gb * (1024 ** 3) / 4096)
    return mock_s


class TestParseMeminfo(unittest.TestCase):
    def test_parses_meminfo(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data=SAMPLE_MEMINFO)):
            result = _parse_meminfo()
        self.assertEqual(result["MemTotal"], 16384000)
        self.assertEqual(result["MemFree"], 800000)
        self.assertEqual(result["MemAvailable"], 12000000)

    def test_handles_empty_file(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data="")):
            result = _parse_meminfo()
        self.assertEqual(result, {})


class TestReadCpuTimes(unittest.TestCase):
    def test_parses_cpu_line(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data=SAMPLE_STAT_CPU)):
            times = _read_cpu_times()
        self.assertEqual(len(times), 10)
        self.assertEqual(times[0], 100000)  # user
        self.assertEqual(times[3], 500000)  # idle


class TestReadLoadavg(unittest.TestCase):
    def test_parses_loadavg(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data="2.45 1.80 1.20 4/512 12345\n")):
            result = _read_loadavg()
        self.assertEqual(result, 2.45)


class TestGetDiskFreeGb(unittest.TestCase):
    def test_computes_free_gb(self):
        mock_stat = MagicMock()
        mock_stat.f_frsize = 4096
        mock_stat.f_bavail = 262144  # 1 GB worth of blocks at 4K
        with patch("os.statvfs", return_value=mock_stat):
            result = _get_disk_free_gb("/")
        self.assertAlmostEqual(result, 1.0, places=2)


class TestResourceMonitor(unittest.TestCase):
    def setUp(self):
        self.monitor = ResourceMonitor()

    def test_get_current_state_returns_resource_state(self):
        """get_current_state returns a ResourceState with expected fields."""
        # Prime CPU baseline with first call
        with patch("builtins.open", _make_mock_open()), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            self.monitor.get_current_state()

        # Second call with different CPU times to get non-zero percent
        cpu2 = "cpu  200000 30000 40000 500000 10000 0 5000 0 0 0\n"
        with patch("builtins.open", _make_mock_open(stat_cpu=cpu2)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            state = self.monitor.get_current_state()

        self.assertIsInstance(state, ResourceState)
        self.assertGreater(state.memory_total_mb, 0)
        self.assertGreater(state.memory_available_mb, 0)
        self.assertGreaterEqual(state.memory_percent, 0.0)
        self.assertGreaterEqual(state.cpu_percent, 0.0)
        self.assertGreater(state.disk_free_gb, 0)
        self.assertGreater(state.timestamp, 0)

    def test_check_resources_all_ok(self):
        """When all metrics are within thresholds, returns (True, state)."""
        # Prime CPU
        with patch("builtins.open", _make_mock_open()), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            self.monitor.get_current_state()

        # Second call — same CPU times = 0% CPU
        with patch("builtins.open", _make_mock_open()), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            ok, state = self.monitor.check_resources()

        self.assertTrue(ok)
        self.assertIsInstance(state, ResourceState)

    def test_check_resources_low_memory(self):
        """Returns False when available memory is below threshold."""
        meminfo = "MemTotal: 16384000 kB\nMemAvailable: 200000 kB\n"  # ~195 MB
        # Prime CPU
        with patch("builtins.open", _make_mock_open(meminfo=meminfo)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            self.monitor.get_current_state()

        with patch("builtins.open", _make_mock_open(meminfo=meminfo)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            ok, state = self.monitor.check_resources()

        self.assertFalse(ok)
        self.assertLess(state.memory_available_mb, 512)

    def test_check_resources_low_disk(self):
        """Returns False when free disk is below threshold."""
        # Prime CPU
        with patch("builtins.open", _make_mock_open()), \
             patch("os.statvfs", return_value=_make_mock_statvfs(0.5)):
            self.monitor.get_current_state()

        with patch("builtins.open", _make_mock_open()), \
             patch("os.statvfs", return_value=_make_mock_statvfs(0.5)):
            ok, state = self.monitor.check_resources()

        self.assertFalse(ok)
        self.assertLess(state.disk_free_gb, 1.0)

    def test_check_resources_high_load(self):
        """Returns False when load average exceeds threshold."""
        loadavg = "15.00 12.00 10.00 8/512 99999\n"
        # Prime CPU
        with patch("builtins.open", _make_mock_open(loadavg=loadavg)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            self.monitor.get_current_state()

        with patch("builtins.open", _make_mock_open(loadavg=loadavg)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            ok, state = self.monitor.check_resources()

        self.assertFalse(ok)
        self.assertGreater(state.load_average_1m, 10.0)

    def test_set_thresholds(self):
        """set_thresholds replaces the threshold configuration."""
        new_t = ResourceThreshold(min_memory_available_mb=1024)
        self.monitor.set_thresholds(new_t)
        self.assertEqual(self.monitor._thresholds.min_memory_available_mb, 1024)

    def test_check_resources_custom_thresholds(self):
        """check_resources accepts per-call threshold override."""
        meminfo = "MemTotal: 16384000 kB\nMemAvailable: 800000 kB\n"  # ~781 MB
        # Prime CPU
        with patch("builtins.open", _make_mock_open(meminfo=meminfo)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            self.monitor.get_current_state()

        with patch("builtins.open", _make_mock_open(meminfo=meminfo)), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            # Default threshold is 512 MB — 781 MB passes
            ok_default, _ = self.monitor.check_resources()
            # Custom threshold of 1024 MB — 781 MB fails
            strict = ResourceThreshold(min_memory_available_mb=1024)
            ok_strict, _ = self.monitor.check_resources(thresholds=strict)

        self.assertTrue(ok_default)
        self.assertFalse(ok_strict)

    def test_cpu_percent_first_call_zero(self):
        """First call to get_current_state returns cpu_percent=0.0 (no baseline)."""
        m = ResourceMonitor()  # fresh monitor, no prior state
        with patch("builtins.open", _make_mock_open()), \
             patch("os.statvfs", return_value=_make_mock_statvfs(10.0)):
            state = m.get_current_state()
        self.assertEqual(state.cpu_percent, 0.0)


class TestResourceThreshold(unittest.TestCase):
    def test_default_values(self):
        t = ResourceThreshold()
        self.assertEqual(t.min_memory_available_mb, 512)
        self.assertEqual(t.max_cpu_percent, 90.0)
        self.assertEqual(t.min_disk_free_gb, 1.0)
        self.assertEqual(t.max_load_average, 10.0)

    def test_validate_raises_on_negative_memory(self):
        t = ResourceThreshold(min_memory_available_mb=-1)
        with self.assertRaises(ValueError):
            t.validate()

    def test_validate_raises_on_cpu_out_of_range(self):
        t = ResourceThreshold(max_cpu_percent=150.0)
        with self.assertRaises(ValueError):
            t.validate()

    def test_validate_raises_on_negative_disk(self):
        t = ResourceThreshold(min_disk_free_gb=-0.5)
        with self.assertRaises(ValueError):
            t.validate()

    def test_validate_raises_on_negative_load(self):
        t = ResourceThreshold(max_load_average=-1.0)
        with self.assertRaises(ValueError):
            t.validate()

    def test_validate_passes_on_valid(self):
        t = ResourceThreshold()
        t.validate()  # should not raise


if __name__ == "__main__":
    unittest.main()
