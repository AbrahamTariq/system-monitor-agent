"""Load and securely persist local application settings."""

from __future__ import annotations

import json
import os
from pathlib import Path

_KEY_NAME = "gemini_api_key"


def get_config_path() -> Path:
    """Return the per-user path used for local application settings."""
    if os.name == "nt":
        base_directory = Path(
            os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        )
    else:
        base_directory = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        )
    return base_directory / "system_monitor_agent" / "config.json"


def load_api_key() -> str | None:
    """Return the environment key or the locally saved key, if available."""
    environment_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if environment_key:
        return environment_key

    try:
        settings = json.loads(get_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    api_key = settings.get(_KEY_NAME) if isinstance(settings, dict) else None
    return api_key.strip() if isinstance(api_key, str) and api_key.strip() else None


def save_api_key(api_key: str) -> None:
    """Persist an API key under the current user's application-data folder."""
    normalized_key = api_key.strip()
    if not normalized_key:
        raise ValueError("Enter a Gemini API key before saving.")

    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        config_path.parent.chmod(0o700)

    temporary_path = config_path.with_suffix(".tmp")
    descriptor = os.open(
        temporary_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as settings_file:
            json.dump({_KEY_NAME: normalized_key}, settings_file)
        os.replace(temporary_path, config_path)
        if os.name != "nt":
            config_path.chmod(0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()