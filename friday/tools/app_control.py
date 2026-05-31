from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict


APP_ALIASES: Dict[str, Dict[str, str]] = {
    "activity monitor": {"Darwin": "Activity Monitor"},
    "calculator": {"Darwin": "Calculator"},
    "chrome": {"Darwin": "Google Chrome"},
    "code": {"Darwin": "Visual Studio Code"},
    "discord": {"Darwin": "Discord"},
    "edge": {"Darwin": "Microsoft Edge"},
    "figma": {"Darwin": "Figma"},
    "finder": {"Darwin": "Finder"},
    "firefox": {"Darwin": "Firefox"},
    "google chrome": {"Darwin": "Google Chrome"},
    "messages": {"Darwin": "Messages"},
    "music": {"Darwin": "Music"},
    "notes": {"Darwin": "Notes"},
    "safari": {"Darwin": "Safari"},
    "slack": {"Darwin": "Slack"},
    "spotfy": {"Darwin": "Spotify"},
    "spotify": {"Darwin": "Spotify"},
    "spotifiy": {"Darwin": "Spotify"},
    "spotufy": {"Darwin": "Spotify"},
    "system settings": {"Darwin": "System Settings"},
    "terminal": {"Darwin": "Terminal"},
    "textedit": {"Darwin": "TextEdit"},
    "visual studio code": {"Darwin": "Visual Studio Code"},
    "vscode": {"Darwin": "Visual Studio Code"},
    "zoom": {"Darwin": "zoom.us"},
}


class AppControlTool:
    def __init__(self) -> None:
        self.system = platform.system()

    def open_app(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        requested = str(parameters.get("app_name", parameters.get("app", ""))).strip()
        if not requested:
            return self._failure("No application name was provided.", {"app_name": requested})
        app_name = self.normalize_app_name(requested)
        if self.system == "Darwin":
            return self._open_macos(app_name, requested)
        return self._failure(f"Application launching is not implemented for {self.system}.", {"app_name": requested})

    def close_app(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        requested = str(parameters.get("app_name", parameters.get("app", ""))).strip()
        if not requested:
            return self._failure("No application name was provided.", {"app_name": requested})
        app_name = self.normalize_app_name(requested)
        if self.system != "Darwin":
            return self._failure(f"Application closing is not implemented for {self.system}.", {"app_name": requested})
        script = f'tell application "{app_name}" to quit'
        completed = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
        if completed.returncode == 0:
            return self._success(f"Closed {app_name}.", {"app_name": app_name})
        return self._failure(f"Could not close {app_name}: {completed.stderr.strip()}", {"app_name": app_name})

    def normalize_app_name(self, raw: str) -> str:
        key = " ".join(raw.lower().strip().split())
        if key in APP_ALIASES:
            return APP_ALIASES[key].get(self.system, raw)
        for alias, os_map in APP_ALIASES.items():
            if alias in key or key in alias:
                return os_map.get(self.system, raw)
        return raw.strip()

    def _open_macos(self, app_name: str, requested: str) -> Dict[str, Any]:
        attempts = [
            ["open", "-a", app_name],
            ["open", "-a", f"{app_name}.app"],
        ]
        bundle = self._find_app_bundle(app_name)
        if bundle:
            attempts.append(["open", str(bundle)])
        for command in attempts:
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
            except subprocess.TimeoutExpired:
                continue
            if completed.returncode == 0:
                time.sleep(1.0)
                running = self._macos_app_running(app_name)
                return self._success(
                    f"Opened {app_name}." if running else f"Launch request sent for {app_name}.",
                    {"requested": requested, "app_name": app_name, "running": running},
                )
        binary = shutil.which(requested) or shutil.which(requested.lower())
        if binary:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self._success(f"Started {requested}.", {"requested": requested, "app_name": requested, "running": True})
        return self._failure(f"I could not find or open {requested}.", {"requested": requested, "app_name": app_name})

    def _find_app_bundle(self, app_name: str) -> Path | None:
        bundle_names = {app_name, f"{app_name}.app"}
        roots = [
            Path("/Applications"),
            Path("/System/Applications"),
            Path.home() / "Applications",
        ]
        for root in roots:
            if not root.exists():
                continue
            for bundle_name in bundle_names:
                direct = root / bundle_name
                if direct.exists():
                    return direct
            for path in root.glob("*.app"):
                stem = path.stem.lower()
                target = app_name.lower()
                if stem == target or target in stem or stem in target:
                    return path
        return None

    def _macos_app_running(self, app_name: str) -> bool:
        script = f'application "{app_name}" is running'
        completed = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        return completed.stdout.strip().lower() == "true"

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}
