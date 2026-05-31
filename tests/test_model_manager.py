from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from friday.config import FridayConfig
from friday.model_manager import ModelManager
from friday.ollama_engine import OllamaClient, OllamaStatus


def _mock_status(models: list[str], reachable: bool = True) -> OllamaStatus:
    selected = models[0] if models else ""
    msg = "Ollama is ready." if reachable else "Ollama is not reachable."
    return OllamaStatus(reachable=reachable, configured_model="qwen3:4b", selected_model=selected, models=models, message=msg)


class TestConfigDefaults(unittest.TestCase):
    def test_default_model(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRIDAY_OLLAMA_MODEL", None)
            os.environ.pop("OLLAMA_MODEL", None)
            config = FridayConfig.load()
            self.assertEqual(config.ollama_default_model, "qwen3:4b")

    def test_fast_model_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRIDAY_FAST_MODEL", None)
            config = FridayConfig.load()
            self.assertEqual(config.ollama_fast_model, "qwen3:1.7b")

    def test_vision_model_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRIDAY_VISION_MODEL", None)
            config = FridayConfig.load()
            self.assertEqual(config.ollama_vision_model, "llama3.2-vision:11b")

    def test_env_override(self):
        with patch.dict(os.environ, {"FRIDAY_FAST_MODEL": "custom:fast", "FRIDAY_VISION_MODEL": "custom:vision"}):
            config = FridayConfig.load()
            self.assertEqual(config.ollama_fast_model, "custom:fast")
            self.assertEqual(config.ollama_vision_model, "custom:vision")


class TestModelManager(unittest.TestCase):
    def _manager(self, models: list[str]) -> ModelManager:
        ollama = MagicMock(spec=OllamaClient)
        ollama.status.return_value = _mock_status(models)
        return ModelManager(ollama, "qwen3:4b", "qwen3:1.7b", "llama3.2-vision:11b")

    def test_model_exists_exact(self):
        mgr = self._manager(["qwen3:4b", "llama3.2-vision:11b"])
        self.assertTrue(mgr.model_exists("qwen3:4b"))
        self.assertTrue(mgr.model_exists("llama3.2-vision:11b"))

    def test_model_exists_prefix(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertTrue(mgr.model_exists("qwen3"))

    def test_model_missing(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertFalse(mgr.model_exists("nonexistent"))

    def test_select_default_for_normal(self):
        mgr = self._manager(["qwen3:4b", "qwen3:1.7b"])
        self.assertEqual(mgr.select_model_for_task("normal"), "qwen3:4b")

    def test_select_default_for_complex(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertEqual(mgr.select_model_for_task("complex"), "qwen3:4b")

    def test_select_fast_for_simple(self):
        mgr = self._manager(["qwen3:4b", "qwen3:1.7b"])
        self.assertEqual(mgr.select_model_for_task("simple"), "qwen3:1.7b")

    def test_select_fallback_when_fast_missing(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertEqual(mgr.select_model_for_task("simple"), "qwen3:4b")

    def test_select_vision(self):
        mgr = self._manager(["qwen3:4b", "llama3.2-vision:11b"])
        self.assertEqual(mgr.select_model_for_task("vision"), "llama3.2-vision:11b")

    def test_select_vision_fallback_to_default(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertEqual(mgr.select_model_for_task("vision"), "qwen3:4b")

    def test_select_direct_returns_empty(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertEqual(mgr.select_model_for_task("direct"), "")

    def test_status_report(self):
        mgr = self._manager(["qwen3:4b", "llama3.2-vision:11b"])
        report = mgr.get_model_status_report()
        self.assertEqual(report["default_model"], "qwen3:4b")
        self.assertTrue(report["default_installed"])
        self.assertFalse(report["fast_installed"])
        self.assertTrue(report["vision_installed"])

    def test_startup_check_all_present(self):
        mgr = self._manager(["qwen3:4b", "qwen3:1.7b", "llama3.2-vision:11b"])
        warnings = mgr.startup_check()
        self.assertEqual(warnings, [])

    def test_startup_check_missing_default(self):
        mgr = self._manager(["qwen3:1.7b"])
        warnings = mgr.startup_check()
        self.assertTrue(any("qwen3:4b" in w for w in warnings))

    def test_startup_check_ollama_down(self):
        ollama = MagicMock(spec=OllamaClient)
        ollama.status.return_value = _mock_status([], reachable=False)
        mgr = ModelManager(ollama, "qwen3:4b", "qwen3:1.7b", "llama3.2-vision:11b")
        warnings = mgr.startup_check()
        self.assertTrue(any("not running" in w for w in warnings))

    def test_pull_suggestion_when_missing(self):
        mgr = self._manager(["qwen3:4b"])
        suggestion = mgr.pull_suggestion("llama3.2-vision:11b")
        self.assertIn("not installed", suggestion)

    def test_pull_suggestion_when_present(self):
        mgr = self._manager(["qwen3:4b"])
        self.assertEqual(mgr.pull_suggestion("qwen3:4b"), "")


if __name__ == "__main__":
    unittest.main()
