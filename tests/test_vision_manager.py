from __future__ import annotations

import base64
import unittest

from friday.services import VisionManager


class VisionManagerTests(unittest.TestCase):
    def _manager(self, preferred: str = "") -> VisionManager:
        mgr = VisionManager.__new__(VisionManager)
        mgr.preferred_vision_model = preferred
        return mgr

    def test_selects_best_available_vision_model(self) -> None:
        model = self._manager().select_vision_model(["qwen3:4b", "llava:latest"])

        self.assertEqual(model, "llava:latest")

    def test_prefers_llama_vision_when_available(self) -> None:
        model = self._manager().select_vision_model(["llava:latest", "llama3.2-vision:latest"])

        self.assertEqual(model, "llama3.2-vision:latest")

    def test_prefers_configured_model_first(self) -> None:
        model = self._manager("llama3.2-vision:11b").select_vision_model(["llava:latest", "llama3.2-vision:11b"])

        self.assertEqual(model, "llama3.2-vision:11b")

    def test_extracts_base64_from_data_url(self) -> None:
        manager = VisionManager.__new__(VisionManager)
        encoded = base64.b64encode(b"tiny-image").decode("ascii")

        self.assertEqual(manager._extract_base64_image(f"data:image/jpeg;base64,{encoded}"), encoded)
        self.assertEqual(manager._extract_base64_image("not-base64"), "")


if __name__ == "__main__":
    unittest.main()
