import flet as ft

from config import load_api_key
from core.agent import SystemMonitorAgent
from ui.gui import gui_main


async def app_target(page: ft.Page) -> None:
    """Initialize the agent and launch the Flet dashboard."""
    api_key = load_api_key()
    agent = None
    if api_key:
        try:
            agent = SystemMonitorAgent(api_key=api_key)
        except (RuntimeError, ValueError):
            agent = None
    await gui_main(page, agent)


if __name__ == "__main__":
    ft.run(app_target)