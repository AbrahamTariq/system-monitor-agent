"""System metrics and guarded process management backed by psutil."""

from __future__ import annotations

import os
from typing import Any

import psutil

_PROTECTED_PIDS = {0, 1, 4}
_PROTECTED_PROCESS_NAMES = {
    "csrss",
    "explorer",
    "idle",
    "init",
    "kernel_task",
    "launchd",
    "lsass",
    "registry",
    "smss",
    "svchost",
    "system",
    "system idle process",
    "systemd",
    "wininit",
    "winlogon",
    "services",
}


def _is_protected_process(pid: int, name: str) -> bool:
    """Return whether a PID or normalized process name is protected."""
    normalized_name = name.strip().casefold()
    if normalized_name.endswith(".exe"):
        normalized_name = normalized_name[:-4]
    return (
        pid in _PROTECTED_PIDS
        or pid == os.getpid()
        or normalized_name in _PROTECTED_PROCESS_NAMES
    )


def _read_process_value(process: psutil.Process, attribute: str, *args: Any) -> Any:
    """Read a process attribute, returning None when access is denied or unsupported."""
    try:
        value = getattr(process, attribute)
        return value(*args) if callable(value) else value
    except (psutil.AccessDenied, NotImplementedError):
        return None


def get_system_metrics() -> dict[str, Any]:
    """Return CPU, memory, and the five processes using the most RAM.

    Memory values are measured in megabytes. Each top-process entry contains
    ``pid``, ``name``, ``memory_percent``, and ``cpu_percent``.
    """
    memory = psutil.virtual_memory()
    top_processes: list[dict[str, Any]] = []

    for process in psutil.process_iter(attrs=["pid", "name", "memory_percent"]):
        try:
            info = process.info
            pid = info.get("pid")
            name = info.get("name")
            if pid is None or name is None:
                continue
            top_processes.append(
                {
                    "pid": int(pid),
                    "name": str(name),
                    "memory_percent": float(info.get("memory_percent") or 0.0),
                    "cpu_percent": float(process.cpu_percent(interval=0.0)),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

    top_processes.sort(key=lambda item: item["memory_percent"], reverse=True)
    megabyte = 1024 * 1024
    return {
        "cpu_percent": float(psutil.cpu_percent(interval=0.1)),
        "per_core_cpu_percent": [
            float(value) for value in psutil.cpu_percent(interval=0.1, percpu=True)
        ],
        "total_ram_mb": round(memory.total / megabyte, 2),
        "available_ram_mb": round(memory.available / megabyte, 2),
        "ram_usage_percent": float(memory.percent),
        "top_processes": top_processes[:5],
    }


def get_process_details(pid: int) -> dict[str, Any]:
    """Return details for a process PID, or an error when it does not exist.

    The result includes name, status, CPU and memory percentages, thread
    count, creation time, and executable path. Unavailable protected fields
    are returned as None.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return {"error": "PID must be a positive integer."}

    try:
        process = psutil.Process(pid)
        return {
            "pid": pid,
            "name": _read_process_value(process, "name"),
            "status": _read_process_value(process, "status"),
            "cpu_percent": _read_process_value(process, "cpu_percent", 0.1),
            "memory_percent": _read_process_value(process, "memory_percent"),
            "threads": _read_process_value(process, "num_threads"),
            "creation_time": _read_process_value(process, "create_time"),
            "executable_path": _read_process_value(process, "exe"),
        }
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ValueError):
        return {"error": f"Process with PID {pid} does not exist."}


def kill_process_by_pid(pid: int) -> str:
    """Terminate a process unless its PID or name is protected.

    Protected OS PIDs and critical system process names are never terminated.
    The process name must be readable to proceed, and termination is not
    escalated to a forced kill if the process does not exit promptly.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return "Error: PID must be a positive integer."

    try:
        process = psutil.Process(pid)
        name = process.name()
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ValueError):
        return f"Error: Process with PID {pid} does not exist."
    except psutil.AccessDenied:
        return f"Error: Cannot safely inspect PID {pid}; process name access was denied."

    if not name:
        return f"Error: Cannot safely inspect PID {pid}; process name is unavailable."
    if _is_protected_process(pid, name):
        return f"Refused: PID {pid} ({name}) is a protected system process."

    try:
        process.terminate()
        process.wait(timeout=3)
        return f"Process {pid} ({name}) terminated."
    except psutil.TimeoutExpired:
        return f"Termination requested for PID {pid} ({name}), but it did not exit within 3 seconds."
    except psutil.NoSuchProcess:
        return f"Process {pid} ({name}) exited before termination completed."
    except psutil.AccessDenied:
        return f"Error: Access denied while terminating PID {pid} ({name})."