from __future__ import annotations

import logging
from typing import Any, Dict, List

from friday.ollama_engine import OllamaClient, OllamaUnavailable

log = logging.getLogger(__name__)


class ModelManager:
    def __init__(
        self,
        ollama: OllamaClient,
        default_model: str,
        fast_model: str,
        vision_model: str,
        code_model: str = "",
    ) -> None:
        self.ollama = ollama
        self.default_model = default_model
        self.fast_model = fast_model
        self.vision_model = vision_model
        self.code_model = code_model

    def get_installed_models(self) -> List[str]:
        try:
            status = self.ollama.status()
            return list(status.models)
        except Exception:
            return []

    def model_exists(self, model_name: str) -> bool:
        models = self.get_installed_models()
        for m in models:
            if m == model_name or m.startswith(model_name + ":"):
                return True
        return False

    def resolve_model(self, model_name: str) -> str:
        models = self.get_installed_models()
        for m in models:
            if m == model_name:
                return m
        for m in models:
            if m.startswith(model_name + ":"):
                return m
        return ""

    def ensure_model_available(self, model_name: str) -> tuple[bool, str]:
        if self.model_exists(model_name):
            return True, f"{model_name} is installed."
        return False, f"{model_name} is not installed."

    def needs_pull(self, model_name: str) -> bool:
        return not self.model_exists(model_name)

    def pull_suggestion(self, model_name: str) -> str:
        if self.model_exists(model_name):
            return ""
        return (
            f"{model_name} is not installed. "
            f"Say 'Friday yes' to pull it or 'Friday no' to keep the current model."
        )

    def pull_model(self, model_name: str) -> bool:
        try:
            self.ollama._request_json(
                "POST", "/api/pull", {"name": model_name, "stream": False}, timeout_seconds=600
            )
            return True
        except OllamaUnavailable:
            return False

    def select_model_for_task(
        self,
        task_type: str,
        requires_vision: bool = False,
    ) -> str:
        if requires_vision or task_type == "vision":
            if self.model_exists(self.vision_model):
                return self.vision_model
            log.warning("Vision model %s not installed, falling back to default", self.vision_model)
            return self.default_model

        if task_type == "direct":
            return ""

        if task_type == "code":
            if self.code_model and self.model_exists(self.code_model):
                return self.code_model
            log.info(
                "Code model %s not installed, falling back to default %s",
                self.code_model or "(unset)",
                self.default_model,
            )
            return self.default_model

        if task_type == "simple":
            if self.model_exists(self.fast_model):
                return self.fast_model
            return self.default_model

        return self.default_model

    def get_model_status_report(self) -> Dict[str, Any]:
        installed = self.get_installed_models()
        return {
            "default_model": self.default_model,
            "default_installed": self.model_exists(self.default_model),
            "fast_model": self.fast_model,
            "fast_installed": self.model_exists(self.fast_model),
            "vision_model": self.vision_model,
            "vision_installed": self.model_exists(self.vision_model),
            "code_model": self.code_model,
            "code_installed": bool(self.code_model) and self.model_exists(self.code_model),
            "installed_models": installed,
            "ollama_reachable": len(installed) > 0 or self.ollama.status().reachable,
        }

    def startup_check(self) -> List[str]:
        warnings: List[str] = []
        status = self.ollama.status()
        if not status.reachable:
            warnings.append("Ollama is not running. Start Ollama and try again.")
            return warnings
        if not self.model_exists(self.default_model):
            warnings.append(self.pull_suggestion(self.default_model))
        if not self.model_exists(self.vision_model):
            warnings.append(
                f"Vision model {self.vision_model} is not installed. "
                f"Screen vision features will be unavailable until it is pulled."
            )
        if self.code_model and not self.model_exists(self.code_model):
            warnings.append(
                f"Code model {self.code_model} is not installed. "
                f"Code generation will fall back to {self.default_model}."
            )
        return warnings
