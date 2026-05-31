from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

from friday.tools.safety import CommandSafety


class RunCommandTool:
    name = "run_command"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.safety = CommandSafety()

    def run(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        command = str(parameters.get("command", "")).strip()
        confirmed = bool(parameters.get("confirmed", False))
        timeout = int(parameters.get("timeout", 30))
        timeout = max(1, min(timeout, 120))
        decision = self.safety.validate(command, confirmed=confirmed)
        if not decision.allowed:
            return {
                "success": False,
                "requires_confirmation": False,
                "message": decision.reason,
                "data": {"command": command},
            }
        if decision.requires_confirmation:
            return {
                "success": False,
                "requires_confirmation": True,
                "message": decision.reason,
                "data": {"command": command},
            }

        completed = subprocess.run(
            command,
            cwd=str(self.root_dir),
            shell=True,
            executable="/bin/zsh",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": completed.returncode == 0,
            "requires_confirmation": False,
            "message": "Command completed." if completed.returncode == 0 else "Command failed.",
            "data": {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            },
        }
