"""Memory and usability signals for the model manager (CONTRACT_B §2).

macOS: phys_footprint via `proc_pid_rusage(RUSAGE_INFO_V4)` (RSS misses Metal/GPU memory), available memory from
`vm_stat` (free + inactive + purgeable + speculative pages), pressure from `sysctl kern.memorystatus_vm_pressure_level`,
user activity from IOHIDSystem's HIDIdleTime, and battery from `pmset -g batt`. Elsewhere (Linux CI) it falls back
to psutil so the policy code and tests still run.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import platform
import re
import subprocess
from dataclasses import asdict, dataclass

import psutil

IS_MAC = platform.system() == "Darwin"
RUSAGE_INFO_V4 = 4
GB = 1024 ** 3


class _RusageInfoV4(ctypes.Structure):
    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16), ("ri_user_time", ctypes.c_uint64), ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64), ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64), ("ri_wired_size", ctypes.c_uint64), ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64), ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64), ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64), ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64), ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64), ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64), ("ri_cpu_time_qos_default", ctypes.c_uint64),
        ("ri_cpu_time_qos_maintenance", ctypes.c_uint64), ("ri_cpu_time_qos_background", ctypes.c_uint64),
        ("ri_cpu_time_qos_utility", ctypes.c_uint64), ("ri_cpu_time_qos_legacy", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_initiated", ctypes.c_uint64), ("ri_cpu_time_qos_user_interactive", ctypes.c_uint64),
        ("ri_billed_system_time", ctypes.c_uint64), ("ri_serviced_system_time", ctypes.c_uint64),
        ("ri_logical_writes", ctypes.c_uint64), ("ri_lifetime_max_phys_footprint", ctypes.c_uint64),
        ("ri_instructions", ctypes.c_uint64), ("ri_cycles", ctypes.c_uint64), ("ri_billed_energy", ctypes.c_uint64),
        ("ri_serviced_energy", ctypes.c_uint64), ("ri_interval_max_phys_footprint", ctypes.c_uint64),
        ("ri_runnable_time", ctypes.c_uint64),
    ]


_libproc = None


def _proc_rusage(pid: int) -> _RusageInfoV4 | None:
    global _libproc
    if not IS_MAC:
        return None
    if _libproc is None:
        _libproc = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib")
    info = _RusageInfoV4()
    if _libproc.proc_pid_rusage(pid, RUSAGE_INFO_V4, ctypes.byref(info)) != 0:
        return None
    return info


def phys_footprint_gb(pid: int) -> tuple[float, float] | None:
    """(current, lifetime peak) physical footprint in GB, or None if the process is gone."""
    info = _proc_rusage(pid)
    if info is not None:
        return info.ri_phys_footprint / GB, info.ri_lifetime_max_phys_footprint / GB
    try:
        p = psutil.Process(pid)
        rss = p.memory_info().rss / GB
        return rss, rss
    except psutil.Error:
        return None


@dataclass
class SystemMemory:
    total_gb: float
    available_gb: float
    pressure: str          # normal | warn | critical

    def as_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def parse_vm_stat(text: str) -> float | None:
    """Available bytes from `vm_stat` output (free + inactive + purgeable + speculative)."""
    m = re.search(r"page size of (\d+) bytes", text)
    if not m:
        return None
    page = int(m.group(1))
    pages = 0
    for key in ("Pages free", "Pages inactive", "Pages purgeable", "Pages speculative"):
        km = re.search(rf"{key}:\s+(\d+)", text)
        if km:
            pages += int(km.group(1))
    return pages * page


def system_memory() -> SystemMemory:
    total = psutil.virtual_memory().total
    if IS_MAC:
        avail = parse_vm_stat(_run(["vm_stat"])) or psutil.virtual_memory().available
        level = _run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip()
        pressure = {"1": "normal", "2": "warn", "4": "critical"}.get(level, "normal")
    else:
        vm = psutil.virtual_memory()
        avail = vm.available
        pressure = "critical" if vm.percent > 95 else "warn" if vm.percent > 88 else "normal"
    return SystemMemory(round(total / GB, 1), round(avail / GB, 1), pressure)


def idle_seconds() -> float | None:
    if not IS_MAC:
        return None
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', _run(["ioreg", "-c", "IOHIDSystem", "-d", "4"]))
    return int(m.group(1)) / 1e9 if m else None


def user_active(threshold_s: float = 300) -> bool:
    idle = idle_seconds()
    return idle is not None and idle < threshold_s


def on_battery() -> bool:
    if IS_MAC:
        return "Battery Power" in _run(["pmset", "-g", "batt"])
    batt = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return bool(batt and not batt.power_plugged)
