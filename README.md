# System Performance & Log Monitor Agent

A local system-monitoring dashboard with `psutil` telemetry, guarded process management, a Flet GUI, and optional Gemini-powered analysis.

## System Requirements

- Python 3.10 or newer
- Target hardware: Intel Core i7 7th Generation and 8 GB DDR4 RAM
- Windows, Linux, or macOS with a working Flet desktop runtime
- Internet access and a Gemini API key for AI chat; local telemetry works without either

The telemetry loop refreshes every two seconds and replaces its process rows instead of accumulating controls. The UI is designed for a modest system, but actual memory use and frame rate depend on the operating system and Flet/Flutter runtime. A sub-45 MB footprint and sustained 60 FPS have not been measured or guaranteed.

## Installation

From the project root, create and activate a virtual environment if desired, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Linux or macOS, activate the environment with:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Gemini API Key

Set `GEMINI_API_KEY` in the shell before launch. Do not commit the key to source control.

PowerShell:

```powershell
$env:GEMINI_API_KEY = "your-api-key"
```

Linux or macOS:

```sh
export GEMINI_API_KEY="your-api-key"
```

When the key is absent, the dashboard still opens and local telemetry remains active; Gemini chat reports that it is unavailable. API/network failures are returned as readable chat errors.

## Launch

```sh
python main.py
```

The dashboard shows CPU utilization by core, RAM usage, and the five largest processes by memory. Ask Gemini for an interpretation or process details through the chat panel. Process termination is limited by protected system PIDs and names; the tool refuses to proceed when it cannot safely inspect a process name.

## Tests

Run the end-to-end and safety checks with Python's standard test runner:

```sh
python -m unittest discover -s tests -v
```

The suite covers live telemetry output shapes, critical process protections, missing keys and API failures, Gemini tool registration, refresh-loop control stability, and non-blocking chat behavior. Gemini calls are mocked; no API credentials are needed for tests.
