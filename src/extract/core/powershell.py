"""Safe execution of PowerShell queries that return JSON.

Every module that reads Windows data receives a `PowerShellRunner`. In production that is
`PowerShell` below; in tests it is `FakePowerShell`, which replays recorded samples, so
nothing outside this file ever calls `subprocess`.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60

# Keeps a console window from flashing on every query when running as a windowed .exe.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def default_executable() -> str:
    """Full path of Windows PowerShell, so a stray `powershell.exe` is never picked up.

    A bare name would be searched in the exe's own folder and the working directory first,
    and both are usually the technician's USB stick or the client's Downloads folder.
    """
    if sys.platform == "win32":
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        path = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if path.is_file():
            return str(path)
    return "powershell.exe"


class PowerShellError(RuntimeError):
    """The query failed, timed out or returned something that is not JSON."""


class PowerShellRunner(Protocol):
    def query(self, script: str, timeout: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
        """Run `script` and return its output as a list of objects (empty if none)."""
        ...


class PowerShell:
    """Run scripts through the local `powershell.exe` and decode their JSON output.

    Scripts are always fixed strings from Extract itself, never user input, and are passed
    as an argument list (no `shell=True`), so there is no shell interpretation involved.
    """

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or default_executable()

    def query(self, script: str, timeout: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
        wrapped = (
            "$ErrorActionPreference = 'Stop'; "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            f"@({script}) | ConvertTo-Json -Depth 5 -Compress"
        )
        cmd = [
            self.executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            wrapped,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PowerShellError(f"PowerShell not found: {self.executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PowerShellError(f"Query timed out after {timeout:.0f}s") from exc

        if proc.returncode != 0:
            raise PowerShellError(proc.stderr.strip() or f"exit code {proc.returncode}")
        return parse_json_output(proc.stdout)


def parse_json_output(text: str) -> list[dict[str, Any]]:
    """Normalize `ConvertTo-Json` output: empty, a single object or a list."""
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PowerShellError(f"Output is not JSON: {text[:200]}") from exc
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def safe_query(ps: PowerShellRunner, script: str, timeout: float = DEFAULT_TIMEOUT_S):
    """Like `ps.query`, but logs failures and returns an empty list.

    Use it when a missing value should not abort the whole scan.
    """
    try:
        return ps.query(script, timeout=timeout)
    except PowerShellError as exc:
        log.warning("PowerShell query failed (%s): %s", script[:80], exc)
        return []


class FakePowerShell:
    """Test double: replays recorded responses, matched by a substring of the script.

    >>> ps = FakePowerShell({"Win32_Processor": [{"Name": "Intel"}]})
    >>> ps.query("Get-CimInstance Win32_Processor")
    [{'Name': 'Intel'}]
    """

    def __init__(self, responses: dict[str, list[dict[str, Any]] | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def query(self, script: str, timeout: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
        self.calls.append(script)
        for key, response in self.responses.items():
            if key in script:
                if isinstance(response, Exception):
                    raise response
                return response
        return []
