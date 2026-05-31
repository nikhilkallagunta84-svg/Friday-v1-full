from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from friday.tools.safety import FileSafety


class FileSystemTool:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.safety = FileSafety(self.root_dir)

    def list_files(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        requested_path = str(parameters.get("path", "."))
        target = self.safety.resolve(requested_path)
        if not target.exists():
            return self._failure(f"Path does not exist: {requested_path}")
        if target.is_file():
            files = [str(target.relative_to(self.root_dir))]
        else:
            files = self._project_files(target)
        return self._success("Project structure read.", {"files": files})

    def read_file(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        target = self.safety.resolve(str(parameters.get("path", "")))
        if not target.exists() or not target.is_file():
            return self._failure("File does not exist.")
        return self._success("File read.", {"path": str(target.relative_to(self.root_dir)), "content": target.read_text(encoding="utf-8")})

    def create_file(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        target = self.safety.resolve(str(parameters.get("path", "")))
        content = str(parameters.get("content", ""))
        overwrite = bool(parameters.get("overwrite", False))
        confirmed = bool(parameters.get("confirmed", False))
        if target.exists() and not overwrite:
            return self._failure("File already exists. Set overwrite with confirmation to replace it.")
        if target.exists() and overwrite and not confirmed:
            return self._confirm("Overwriting a file requires confirmation.", {"path": str(target.relative_to(self.root_dir))})
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self._success("File written.", {"path": str(target.relative_to(self.root_dir))})

    def append_file(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        target = self.safety.resolve(str(parameters.get("path", "")))
        content = str(parameters.get("content", ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as output:
            output.write(content)
        return self._success("Content appended.", {"path": str(target.relative_to(self.root_dir))})

    def move_file(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        source = self.safety.resolve(str(parameters.get("source", "")))
        destination = self.safety.resolve(str(parameters.get("destination", "")))
        confirmed = bool(parameters.get("confirmed", False))
        if not confirmed:
            return self._confirm("Moving files requires confirmation.", {"source": str(source), "destination": str(destination)})
        if not source.exists():
            return self._failure("Source file does not exist.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return self._success("File moved.", {"destination": str(destination.relative_to(self.root_dir))})

    def _project_files(self, target: Path) -> List[str]:
        files: List[str] = []
        for path in sorted(target.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and ".git" not in path.parts:
                files.append(str(path.relative_to(self.root_dir)))
            if len(files) >= 250:
                files.append("...")
                break
        return files

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": {}}

    def _confirm(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": True, "message": message, "data": data}
