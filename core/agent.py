"""Gemini-powered agent for local hardware telemetry."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import errors
from google.genai import types

from tools.telemetry import (
    get_process_details,
    get_system_metrics,
    kill_process_by_pid,
)

DEFAULT_MODEL = "gemini-3.8-flash"
RETRY_DELAYS = (1, 2, 4)
UNAVAILABLE_MESSAGE = (
    "The AI model is currently under high demand on Google's servers. "
    "Please try your prompt again in a moment."
)
SYSTEM_INSTRUCTION = (
    "Act as an intelligent, helpful hardware system monitor for a laptop with "
    "8 GB of RAM and a dual-core Intel Core i7 processor. Use the available "
    "tools for current system readings instead of guessing. Explain resource "
    "usage clearly and concisely. Only terminate a process when the user "
    "explicitly requests it, and respect all tool safety refusals."
)


class SystemMonitorAgent:
    """Manage the Gemini client and tool-assisted system-monitor chats."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Gemini client from an explicit key or environment.

        Raises:
            ValueError: If ``api_key`` and ``GEMINI_API_KEY`` are both missing.
            RuntimeError: If the Gemini client cannot be initialized.
        """
        resolved_api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved_api_key or not resolved_api_key.strip():
            raise ValueError(
                "Set GEMINI_API_KEY or pass api_key to initialize the agent."
            )

        try:
            self.client = genai.Client(api_key=resolved_api_key.strip())
        except Exception as error:
            raise RuntimeError("Failed to initialize the Gemini API client.") from error

        self.model = DEFAULT_MODEL

    def get_tools(self) -> list[Callable[..., Any]]:
        """Return the telemetry callables registered for Gemini tool calling."""
        return [get_system_metrics, get_process_details, kill_process_by_pid]

    def chat(self, user_prompt: str) -> str:
        """Send a prompt to Gemini and return its final text response.

        The Gen AI SDK automatically executes the registered Python tools when
        the model requests them, then returns the model's follow-up response.
        API and tool execution failures are returned as readable error text.
        """
        try:
            for attempt in range(len(RETRY_DELAYS) + 1):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            tools=self.get_tools(),
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                                disable=False,
                                maximum_remote_calls=5,
                            ),
                        ),
                    )
                    return response.text or "Gemini returned no text response."
                except errors.APIError as error:
                    if error.code != 503 and error.status != "UNAVAILABLE":
                        raise
                    if attempt == len(RETRY_DELAYS):
                        return UNAVAILABLE_MESSAGE
                    time.sleep(RETRY_DELAYS[attempt])
        except Exception as error:
            return f"Gemini API request failed ({type(error).__name__}): {error}"