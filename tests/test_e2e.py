"""End-to-end checks for telemetry, process safety, Gemini, and the Flet UI."""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import flet as ft
import psutil
from google.genai.errors import APIError

from core.agent import DEFAULT_MODEL, UNAVAILABLE_MESSAGE, SystemMonitorAgent
from config import load_api_key, save_api_key
from main import app_target
from tools.telemetry import (
    get_process_details,
    get_system_metrics,
    kill_process_by_pid,
)
from ui.gui import gui_main


class FakePage:
    """Minimal Flet page surface for UI integration tests."""

    def __init__(self) -> None:
        self.window = None
        self.controls: list[ft.Control] = []
        self.background_tasks = []
        self.update_count = 0
        self.dialogs = []

    def add(self, *controls: ft.Control) -> None:
        """Store controls added by the UI builder."""
        self.controls.extend(controls)

    def run_task(self, handler, *args, **kwargs):
        """Capture background tasks without launching an Flet runtime."""
        self.background_tasks.append(handler)
        return None

    def update(self, *controls: ft.Control) -> None:
        """Count page refreshes made by UI event handlers."""
        self.update_count += 1

    def show_dialog(self, dialog: ft.AlertDialog) -> None:
        """Capture dialogs opened by the UI builder."""
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        """Capture requests to dismiss the active dialog."""
        if self.dialogs:
            self.dialogs.pop()


def walk_controls(control: ft.Control):
    """Yield a control and its descendants for UI assertions."""
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from walk_controls(content)


class TelemetryTests(unittest.TestCase):
    """Exercise local telemetry using the host's standard process APIs."""

    def test_system_metrics_have_expected_shape(self) -> None:
        metrics = get_system_metrics()

        self.assertTrue(
            {
                "cpu_percent",
                "per_core_cpu_percent",
                "total_ram_mb",
                "available_ram_mb",
                "ram_usage_percent",
                "top_processes",
            }
            <= metrics.keys()
        )
        self.assertGreater(metrics["total_ram_mb"], 0)
        self.assertGreaterEqual(metrics["available_ram_mb"], 0)
        self.assertLessEqual(len(metrics["top_processes"]), 5)
        for process in metrics["top_processes"]:
            self.assertTrue(
                {"pid", "name", "memory_percent", "cpu_percent"}
                <= process.keys()
            )

    def test_process_details_for_current_process(self) -> None:
        details = get_process_details(os.getpid())

        self.assertEqual(details["pid"], os.getpid())
        self.assertTrue(
            {
                "name",
                "status",
                "cpu_percent",
                "memory_percent",
                "threads",
                "creation_time",
                "executable_path",
            }
            <= details.keys()
        )

    def test_nonexistent_process_details_returns_error(self) -> None:
        with patch("tools.telemetry.psutil.Process", side_effect=psutil.NoSuchProcess(99999999)):
            self.assertIn("error", get_process_details(99999999))

    def test_nonexistent_process_cannot_be_terminated(self) -> None:
        with patch("tools.telemetry.psutil.Process", side_effect=psutil.NoSuchProcess(99999999)):
            self.assertIn("does not exist", kill_process_by_pid(99999999))

    def test_protected_system_pids_are_never_terminated(self) -> None:
        for protected_pid in (0, 1, 4):
            with self.subTest(pid=protected_pid):
                process = Mock()
                process.name.return_value = "ordinary-process.exe"
                with patch("tools.telemetry.psutil.Process", return_value=process):
                    result = kill_process_by_pid(protected_pid)
                if protected_pid == 0:
                    self.assertIn("Error:", result)
                else:
                    self.assertIn("protected system process", result)
                process.terminate.assert_not_called()
                process.kill.assert_not_called()

    def test_critical_process_names_are_never_terminated(self) -> None:
        critical_names = (
            "svchost.exe",
            "Explorer.exe",
            "systemd",
            "init",
            "csrss.exe",
            "services.exe",
        )
        for name in critical_names:
            with self.subTest(name=name):
                process = Mock()
                process.name.return_value = name
                with patch("tools.telemetry.psutil.Process", return_value=process):
                    result = kill_process_by_pid(987654)
                self.assertIn("protected system process", result)
                process.terminate.assert_not_called()
                process.kill.assert_not_called()

    def test_unknown_process_name_fails_closed(self) -> None:
        process = Mock()
        process.name.side_effect = psutil.AccessDenied(987654)
        with patch("tools.telemetry.psutil.Process", return_value=process):
            result = kill_process_by_pid(987654)

        self.assertIn("Cannot safely inspect", result)
        process.terminate.assert_not_called()


class AgentTests(unittest.TestCase):
    """Validate API-key fallback, function tool declarations, and API failures."""

    def test_missing_api_key_is_reported(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                SystemMonitorAgent()

    def test_client_uses_telemetry_functions_as_tools(self) -> None:
        with patch("core.agent.genai.Client") as client_factory:
            agent = SystemMonitorAgent(api_key=" test-key ")
            self.assertEqual(DEFAULT_MODEL, "gemini-3.8-flash")
            self.assertEqual(agent.model, DEFAULT_MODEL)
            self.assertEqual(
                agent.get_tools(),
                [get_system_metrics, get_process_details, kill_process_by_pid],
            )
            client_factory.assert_called_once_with(api_key="test-key")

            client = client_factory.return_value
            client.models.generate_content.return_value.text = "System looks healthy."
            self.assertEqual(agent.chat("Check system health"), "System looks healthy.")

            request = client.models.generate_content.call_args.kwargs
            config = request["config"]
            self.assertEqual(request["model"], DEFAULT_MODEL)
            self.assertEqual(config.tools, agent.get_tools())
            self.assertFalse(config.automatic_function_calling.disable)
            self.assertEqual(config.automatic_function_calling.maximum_remote_calls, 5)

    def test_api_failure_returns_readable_fallback(self) -> None:
        with patch("core.agent.genai.Client") as client_factory:
            agent = SystemMonitorAgent(api_key="test-key")
            client_factory.return_value.models.generate_content.side_effect = OSError(
                "offline"
            )

            answer = agent.chat("Check system health")

        self.assertIn("Gemini API request failed", answer)
        self.assertIn("offline", answer)

    def test_unavailable_error_retries_and_recovers(self) -> None:
        unavailable = APIError(
            503, {"message": "Service Unavailable", "status": "UNAVAILABLE"}
        )
        with patch("core.agent.genai.Client") as client_factory:
            agent = SystemMonitorAgent(api_key="test-key")
            generate_content = client_factory.return_value.models.generate_content
            generate_content.side_effect = [unavailable, unavailable, Mock(text="Recovered")]

            with patch("core.agent.time.sleep") as sleep:
                answer = agent.chat("Check system health")

        self.assertEqual(answer, "Recovered")
        self.assertEqual(generate_content.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_unavailable_error_exhaustion_returns_friendly_fallback(self) -> None:
        unavailable = APIError(
            503, {"message": "Service Unavailable", "status": "UNAVAILABLE"}
        )
        with patch("core.agent.genai.Client") as client_factory:
            agent = SystemMonitorAgent(api_key="test-key")
            generate_content = client_factory.return_value.models.generate_content
            generate_content.side_effect = unavailable

            with patch("core.agent.time.sleep") as sleep:
                answer = agent.chat("Check system health")

        self.assertEqual(answer, UNAVAILABLE_MESSAGE)
        self.assertEqual(generate_content.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])


class ApiKeyConfigTests(unittest.TestCase):
    """Check environment precedence and private local key persistence."""

    def test_saved_key_loads_and_environment_key_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "settings" / "config.json"
            with patch("config.get_config_path", return_value=config_path):
                with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
                    save_api_key(" local-key ")
                    self.assertEqual(load_api_key(), "local-key")

                with patch.dict(os.environ, {"GEMINI_API_KEY": " environment-key "}):
                    self.assertEqual(load_api_key(), "environment-key")

            if os.name != "nt":
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)


class UiAsyncTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the async UI event path without starting a desktop window."""

    async def test_telemetry_loop_keeps_control_counts_bounded(self) -> None:
        page = FakePage()
        await gui_main(page)
        metrics = {
            "cpu_percent": 24.0,
            "per_core_cpu_percent": [18.0, 32.0],
            "total_ram_mb": 8192.0,
            "available_ram_mb": 4096.0,
            "ram_usage_percent": 50.0,
            "top_processes": [
                {
                    "pid": 2000 + index,
                    "name": f"test-process-{index}",
                    "memory_percent": float(10 - index),
                    "cpu_percent": 1.0,
                }
                for index in range(5)
            ],
        }
        sleep_intervals: list[float] = []

        class StopRefresh(Exception):
            pass

        async def stop_after_three_refreshes(seconds: float) -> None:
            sleep_intervals.append(seconds)
            if len(sleep_intervals) == 3:
                raise StopRefresh

        with patch("ui.gui.get_system_metrics", return_value=metrics) as read_metrics:
            with patch("ui.gui.asyncio.sleep", new=stop_after_three_refreshes):
                with self.assertRaises(StopRefresh):
                    await page.background_tasks[0]()

        controls = list(walk_controls(page.controls[0]))
        text_values = [
            control.value for control in controls if isinstance(control, ft.Text)
        ]
        self.assertEqual(read_metrics.call_count, 3)
        self.assertEqual(sleep_intervals, [2, 2, 2])
        self.assertEqual(page.update_count, 3)
        self.assertEqual(text_values.count("CORE 01"), 1)
        self.assertEqual(text_values.count("CORE 02"), 1)
        for index in range(5):
            self.assertEqual(text_values.count(f"test-process-{index}"), 1)

    async def test_slow_agent_does_not_block_ui_event_loop(self) -> None:
        completed = threading.Event()

        class SlowAgent:
            def chat(self, prompt: str) -> str:
                time.sleep(0.12)
                completed.set()
                return f"Mock response: {prompt}"

        page = FakePage()
        await gui_main(page, SlowAgent())
        controls = list(walk_controls(page.controls[0]))
        prompt = next(control for control in controls if isinstance(control, ft.TextField))
        send = next(
            control
            for control in controls
            if isinstance(control, ft.IconButton) and control.tooltip == "Send message"
        )
        prompt.value = "Summarize current load"

        send_task = asyncio.create_task(send.on_click(None))
        await asyncio.sleep(0.02)
        responsive_before_response = not completed.is_set()
        await send_task

        self.assertTrue(responsive_before_response)
        self.assertTrue(completed.is_set())
        rendered_text = [
            control.value
            for control in walk_controls(page.controls[0])
            if isinstance(control, ft.Text)
        ]
        self.assertIn("Mock response: Summarize current load", rendered_text)

    async def test_missing_key_dialog_saves_and_relaunch_loads_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "settings" / "config.json"
            with patch("config.get_config_path", return_value=config_path):
                with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
                    page = FakePage()
                    await app_target(page)

                    self.assertEqual(len(page.dialogs), 1)
                    dialog = page.dialogs[0]
                    key_field = next(
                        control
                        for control in walk_controls(dialog.content)
                        if isinstance(control, ft.TextField)
                    )
                    self.assertTrue(key_field.password)
                    key_field.value = "saved-through-ui"
                    save_button = next(
                        action
                        for action in dialog.actions
                        if getattr(action, "content", None) == "Save & Connect"
                    )

                    with patch("core.agent.genai.Client"):
                        await save_button.on_click(None)

                    self.assertFalse(page.dialogs)
                    self.assertEqual(load_api_key(), "saved-through-ui")

                    relaunched_page = FakePage()
                    with patch("core.agent.genai.Client"):
                        await app_target(relaunched_page)

                    self.assertFalse(relaunched_page.dialogs)
                    self.assertTrue(
                        any(
                            isinstance(control, ft.Text) and control.value == "ONLINE"
                            for control in walk_controls(relaunched_page.controls[0])
                        )
                    )
