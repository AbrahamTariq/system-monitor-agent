"""Responsive Flet dashboard for live system telemetry and Gemini chat."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import flet as ft

from config import save_api_key
from core.agent import SystemMonitorAgent
from tools.telemetry import get_system_metrics

_BACKGROUND = "#0f172a"
_PANEL = "#172238"
_PANEL_SOFT = "#1b2940"
_BORDER = "#293a55"
_TEXT = "#e5edf8"
_MUTED = "#92a2ba"
_MINT = "#39d6a3"
_BLUE = "#66a6ff"
_AMBER = "#f4bd62"
_RED = "#ff6b72"


def _load_color(value: float) -> str:
    """Return the telemetry meter color for a percentage load."""
    if value >= 85:
        return _RED
    if value >= 60:
        return _AMBER
    return _MINT


def _glass_card(content: ft.Control, *, padding: int = 18) -> ft.Container:
    """Create a restrained translucent-style dashboard panel."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=_PANEL,
        border=ft.Border.all(1, _BORDER),
        border_radius=16,
        shadow=ft.BoxShadow(
            blur_radius=22,
            spread_radius=0,
            color="#090f1d66",
            offset=ft.Offset(0, 8),
        ),
    )


def _section_heading(title: str, trailing: ft.Control | None = None) -> ft.Row:
    """Build a compact dashboard section heading."""
    controls = [
        ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=_TEXT, expand=True)
    ]
    if trailing is not None:
        controls.append(trailing)
    return ft.Row(controls=controls, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)


async def gui_main(
    page: ft.Page,
    agent: SystemMonitorAgent | None = None,
) -> None:
    """Build the dashboard and run responsive telemetry/chat interactions."""
    page.title = "System Monitor"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = _BACKGROUND
    page.padding = 0
    page.spacing = 0

    if page.window is not None:
        page.window.min_width = 760
        page.window.min_height = 620
    page.scroll = ft.ScrollMode.AUTO

    core_rows: dict[int, tuple[ft.ProgressBar, ft.Text]] = {}
    process_list = ft.Column(spacing=8)
    overall_cpu = ft.ProgressRing(
        width=58,
        height=58,
        stroke_width=5,
        value=0,
        color=_MINT,
        bgcolor=_BORDER,
    )
    overall_cpu_label = ft.Text("--%", size=13, weight=ft.FontWeight.BOLD, color=_TEXT)
    ram_bar = ft.ProgressBar(
        value=0,
        bar_height=8,
        color=_BLUE,
        bgcolor="#2b3b54",
        border_radius=8,
        animate_size=300,
    )
    ram_percent = ft.Text("--%", size=22, weight=ft.FontWeight.W_600, color=_TEXT)
    ram_summary = ft.Text("Waiting for telemetry", size=11, color=_MUTED)
    telemetry_status = ft.Text("Starting local monitor", size=11, color=_MUTED)
    ai_status_dot = ft.Container(
        width=6,
        height=6,
        bgcolor=_MINT if agent is not None else _AMBER,
        border_radius=5,
    )
    ai_status_text = ft.Text(
        "ONLINE" if agent is not None else "OFFLINE",
        size=9,
        weight=ft.FontWeight.BOLD,
        color=_MINT if agent is not None else _AMBER,
    )
    gemini_status = ft.Text(
        "GEMINI ONLINE" if agent is not None else "GEMINI NOT CONNECTED",
        size=9,
        color=_TEXT,
    )

    messages = ft.ListView(
        expand=True,
        spacing=14,
        padding=ft.Padding(left=18, right=18, top=18, bottom=18),
        auto_scroll=True,
        auto_scroll_animation=ft.Animation(240, ft.AnimationCurve.EASE_OUT),
        controls=[],
    )
    prompt_field = ft.TextField(
        hint_text="Ask about CPU, memory, or a process...",
        hint_style=ft.TextStyle(color="#8293ad", size=13),
        text_style=ft.TextStyle(color=_TEXT, size=14),
        border=ft.InputBorder.NONE,
        bgcolor="transparent",
        expand=True,
        multiline=True,
        min_lines=1,
        max_lines=4,
        content_padding=ft.Padding(left=4, right=4, top=12, bottom=12),
        on_submit=None,
    )
    send_button: ft.IconButton
    input_frame: ft.Container

    def add_message(text: str, *, from_user: bool, transient: bool = False) -> ft.Container:
        """Append one styled message bubble to the chat stream."""
        bubble = ft.Container(
            content=ft.Text(text, size=13, color=_TEXT, selectable=True),
            padding=ft.Padding(left=15, right=15, top=11, bottom=11),
            bgcolor="#24416a" if from_user else _PANEL_SOFT,
            border=ft.Border.all(1, "#355b86" if from_user else _BORDER),
            border_radius=ft.BorderRadius(
                top_left=15,
                top_right=15,
                bottom_left=15 if from_user else 5,
                bottom_right=5 if from_user else 15,
            ),
            width=560,
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )
        messages.controls.append(
            ft.Row(
                controls=[bubble],
                alignment=(
                    ft.MainAxisAlignment.END if from_user else ft.MainAxisAlignment.START
                ),
            )
        )
        if transient:
            return bubble
        return bubble

    def update_ai_status(connected: bool) -> None:
        """Refresh visible Gemini connection indicators."""
        color = _MINT if connected else _AMBER
        ai_status_dot.bgcolor = color
        ai_status_text.value = "ONLINE" if connected else "OFFLINE"
        ai_status_text.color = color
        gemini_status.value = "GEMINI ONLINE" if connected else "GEMINI NOT CONNECTED"

    def open_key_settings(_: Any = None) -> None:
        """Show the key-entry dialog for initial setup or key updates."""
        key_field = ft.TextField(
            label="Gemini API key",
            hint_text="Paste your API key",
            password=True,
            can_reveal_password=True,
            autofocus=True,
            border_color=_BORDER,
            focused_border_color=_BLUE,
            cursor_color=_MINT,
            enable_suggestions=False,
            autocorrect=False,
        )
        dialog_error = ft.Text("", size=11, color=_RED)

        async def save_and_connect(_: Any = None) -> None:
            nonlocal agent
            api_key = (key_field.value or "").strip()
            if not api_key:
                dialog_error.value = "Enter an API key to continue."
                page.update()
                return

            save_button.disabled = True
            save_button.content = "Connecting..."
            dialog_error.value = ""
            page.update()
            try:
                connected_agent = await asyncio.to_thread(SystemMonitorAgent, api_key)
                save_api_key(api_key)
            except (OSError, RuntimeError, ValueError) as error:
                dialog_error.value = f"Unable to save or connect: {error}"
                save_button.disabled = False
                save_button.content = "Save & Connect"
                page.update()
                return

            agent = connected_agent
            update_ai_status(True)
            page.pop_dialog()
            add_message("Gemini is connected. AI diagnostics are ready.", from_user=False)
            page.update()

        save_button = ft.TextButton(
            content="Save & Connect",
            style=ft.ButtonStyle(color="#071821", bgcolor=_MINT),
            on_click=save_and_connect,
        )
        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=_PANEL,
            title=ft.Text("Connect Gemini", size=18, color=_TEXT),
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Enter your Gemini API Key to enable AI Diagnostics",
                        size=13,
                        color=_TEXT,
                    ),
                    key_field,
                    dialog_error,
                ],
                tight=True,
                spacing=12,
                width=420,
            ),
            actions=[
                ft.TextButton(
                    content="Get an API key from Google AI Studio",
                    url="https://aistudio.google.com/app/apikey",
                    style=ft.ButtonStyle(color=_BLUE),
                ),
                ft.TextButton(content="Not now", on_click=lambda _: page.pop_dialog()),
                save_button,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dialog)

    add_message(
        "System monitor ready. Ask for a live resource snapshot or details about a process.",
        from_user=False,
    )

    async def send_prompt(_: Any = None) -> None:
        """Submit a prompt without blocking Flet's async event loop."""
        prompt = (prompt_field.value or "").strip()
        if not prompt:
            return

        prompt_field.value = ""
        add_message(prompt, from_user=True)
        if agent is None:
            add_message(
                "Gemini is unavailable because GEMINI_API_KEY is not configured. "
                "Local telemetry will continue updating.",
                from_user=False,
            )
            page.update()
            return

        send_button.disabled = True
        send_button.icon = ft.Icons.HOURGLASS_TOP
        add_message("Checking the latest telemetry...", from_user=False)
        page.update()
        try:
            answer = await asyncio.to_thread(agent.chat, prompt)
            messages.controls.pop()
            add_message(answer, from_user=False)
        except Exception as error:
            messages.controls.pop()
            add_message(f"Unable to complete the request: {error}", from_user=False)
        finally:
            send_button.disabled = False
            send_button.icon = ft.Icons.ARROW_UPWARD
            page.update()

    async def refresh_telemetry() -> None:
        """Refresh CPU, memory, and top-process controls every two seconds."""
        while True:
            try:
                metrics = await asyncio.to_thread(get_system_metrics)
                cpu_value = float(metrics.get("cpu_percent", 0))
                overall_cpu.value = cpu_value / 100
                overall_cpu.color = _load_color(cpu_value)
                overall_cpu_label.value = f"{cpu_value:.0f}%"

                per_core = metrics.get("per_core_cpu_percent", [])
                for core_index, core_value in enumerate(per_core):
                    load = float(core_value)
                    if core_index not in core_rows:
                        label = ft.Text("", size=11, color=_MUTED, width=38)
                        meter = ft.ProgressBar(
                            value=load / 100,
                            bar_height=6,
                            color=_load_color(load),
                            bgcolor="#2b3b54",
                            border_radius=6,
                            expand=True,
                            animate_size=300,
                        )
                        core_rows[core_index] = (meter, label)
                        core_meter_list.controls.append(
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        f"CORE {core_index + 1:02d}",
                                        size=10,
                                        color=_MUTED,
                                        width=58,
                                    ),
                                    meter,
                                    label,
                                ],
                                spacing=9,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            )
                        )
                    meter, label = core_rows[core_index]
                    meter.value = max(0.0, min(1.0, load / 100))
                    meter.color = _load_color(load)
                    label.value = f"{load:.0f}%"

                ram_used = float(metrics.get("ram_usage_percent", 0))
                ram_bar.value = max(0.0, min(1.0, ram_used / 100))
                ram_bar.color = _load_color(ram_used)
                ram_percent.value = f"{ram_used:.0f}%"
                ram_summary.value = (
                    f"{metrics.get('available_ram_mb', 0):,.0f} MB available of "
                    f"{metrics.get('total_ram_mb', 0):,.0f} MB"
                )

                process_list.controls = []
                for process in metrics.get("top_processes", [])[:5]:
                    name = str(process.get("name") or "Unknown")
                    process_list.controls.append(
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.MEMORY,
                                        size=15,
                                        color=_BLUE,
                                    ),
                                    width=30,
                                    height=30,
                                    alignment=ft.Alignment.CENTER,
                                    bgcolor="#22334d",
                                    border_radius=8,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            name[:24],
                                            size=11,
                                            color=_TEXT,
                                            weight=ft.FontWeight.W_500,
                                            max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                        ft.Text(
                                            f"PID {process.get('pid', '—')}",
                                            size=10,
                                            color=_MUTED,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Text(
                                    f"{float(process.get('memory_percent', 0)):.1f}%",
                                    size=11,
                                    color=_TEXT,
                                    weight=ft.FontWeight.W_600,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=8,
                        )
                    )

                telemetry_status.value = "LIVE  ·  refreshed just now"
                page.update()
            except Exception as error:
                telemetry_status.value = f"Telemetry unavailable: {type(error).__name__}"
                page.update()
            await asyncio.sleep(2)

    send_button = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD,
        icon_color="#071821",
        bgcolor=_MINT,
        tooltip="Send message",
        on_click=send_prompt,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
    )

    def input_hover(event: ft.ControlEvent) -> None:
        """Give the prompt container a subtle focus-like hover response."""
        input_frame.border = ft.Border.all(1, "#4a7195" if event.data == "true" else _BORDER)
        input_frame.shadow = ft.BoxShadow(
            blur_radius=20 if event.data == "true" else 12,
            color="#0b152580",
            offset=ft.Offset(0, 5),
        )
        page.update()

    input_frame = ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(content=prompt_field, expand=True),
                send_button,
            ],
            vertical_alignment=ft.CrossAxisAlignment.END,
            spacing=10,
        ),
        padding=ft.Padding(left=16, right=10, top=8, bottom=8),
        bgcolor="#141f32",
        border=ft.Border.all(1, _BORDER),
        border_radius=17,
        animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        shadow=ft.BoxShadow(blur_radius=12, color="#0b152580", offset=ft.Offset(0, 5)),
        on_hover=input_hover,
    )
    prompt_field.on_submit = send_prompt

    brand = ft.Row(
        controls=[
            ft.Container(
                content=ft.Icon(ft.Icons.DEVICE_HUB, color=_MINT, size=21),
                width=42,
                height=42,
                alignment=ft.Alignment.CENTER,
                bgcolor="#183a3c",
                border_radius=13,
            ),
            ft.Column(
                controls=[
                    ft.Text("NORTHSTAR", size=13, weight=ft.FontWeight.BOLD, color=_TEXT),
                    ft.Text("SYSTEM MONITOR", size=9, color=_MUTED),
                ],
                spacing=3,
                expand=True,
            ),
            ft.Container(
                content=ft.Row(
                    controls=[ai_status_dot, ai_status_text],
                    spacing=6,
                ),
                padding=ft.Padding(left=9, right=9, top=7, bottom=7),
                bgcolor="#183a3c",
                border_radius=20,
            ),
        ],
        spacing=11,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    core_meter_list = ft.Column(spacing=12)
    cpu_card = _glass_card(
        ft.Column(
            controls=[
                _section_heading("PROCESSOR", ft.Text("LIVE LOAD", size=9, color=_MUTED)),
                ft.Row(
                    controls=[
                        ft.Stack(
                            controls=[overall_cpu, overall_cpu_label],
                            alignment=ft.Alignment.CENTER,
                            width=58,
                            height=58,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("CPU UTILIZATION", size=10, color=_MUTED),
                                ft.Text("Intel Core i7 · dual core", size=12, color=_TEXT),
                            ],
                            spacing=5,
                            expand=True,
                        ),
                    ],
                    spacing=15,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Divider(height=1, color=_BORDER),
                core_meter_list,
            ],
            spacing=14,
        )
    )
    ram_card = _glass_card(
        ft.Column(
            controls=[
                _section_heading("MEMORY", ft.Icon(ft.Icons.MEMORY, size=16, color=_BLUE)),
                ft.Row(
                    controls=[
                        ram_percent,
                        ft.Text("IN USE", size=9, color=_MUTED),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                ram_bar,
                ram_summary,
            ],
            spacing=11,
        )
    )
    process_card = _glass_card(
        ft.Column(
            controls=[
                _section_heading("MEMORY LEADERS", ft.Text("TOP 5", size=9, color=_MUTED)),
                process_list,
            ],
            spacing=15,
        )
    )

    sidebar = ft.Container(
        content=ft.Column(
            controls=[
                brand,
                ft.Container(height=8),
                cpu_card,
                ram_card,
                process_card,
                ft.Container(height=2),
                telemetry_status,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=22,
        bgcolor="#111b2d",
        border=ft.Border.only(right=ft.BorderSide(1, _BORDER)),
        expand=True,
    )

    chat_header = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Text("Performance desk", size=21, weight=ft.FontWeight.W_600, color=_TEXT),
                    ft.Text(
                        "Local telemetry, interpreted in plain language",
                        size=11,
                        color=_MUTED,
                    ),
                ],
                spacing=5,
                expand=True,
            ),
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.AUTO_AWESOME, size=14, color=_AMBER),
                        gemini_status,
                    ],
                    spacing=6,
                ),
                padding=ft.Padding(left=10, right=10, top=8, bottom=8),
                bgcolor=_PANEL,
                border=ft.Border.all(1, _BORDER),
                border_radius=20,
            ),
            ft.IconButton(
                icon=ft.Icons.SETTINGS,
                icon_color=_MUTED,
                tooltip="Gemini API key settings",
                on_click=open_key_settings,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    chat_panel = ft.Column(
        controls=[
            chat_header,
            ft.Container(
                content=messages,
                expand=True,
                bgcolor="#111b2a",
                border=ft.Border.all(1, _BORDER),
                border_radius=17,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ),
            input_frame,
            ft.Row(
                controls=[
                    ft.Text("LOCAL TELEMETRY  ·  2 SECOND REFRESH", size=9, color=_MUTED),
                    ft.Text("ENTER TO SEND", size=9, color=_MUTED),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        ],
        spacing=15,
        expand=True,
    )
    main_panel = ft.Container(content=chat_panel, padding=26, expand=True)

    page.add(
        ft.ResponsiveRow(
            controls=[
                ft.Container(content=sidebar, col={"xs": 12, "md": 4, "lg": 4}),
                ft.Container(content=main_panel, col={"xs": 12, "md": 8, "lg": 8}),
            ],
            columns=12,
            spacing=0,
            run_spacing=0,
            expand=True,
        )
    )
    page.run_task(refresh_telemetry)
    if agent is None:
        open_key_settings()