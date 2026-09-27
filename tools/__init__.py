"""Local system telemetry and process management tools."""

from .telemetry import get_process_details, get_system_metrics, kill_process_by_pid

__all__ = [
    "get_process_details",
    "get_system_metrics",
    "kill_process_by_pid",
]