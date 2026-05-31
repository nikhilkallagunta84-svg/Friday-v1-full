from __future__ import annotations

import unittest

from friday.services import VisualContextManager


class VisualContextManagerTests(unittest.TestCase):
    def _manager_with_context(self) -> VisualContextManager:
        manager = VisualContextManager()
        manager.store(
            file_name="math.png",
            mime_type="image/png",
            image_data_urls=["data:image/png;base64,ZmFrZQ=="],
            frame_labels=["image"],
            analysis="The image shows a math equation.",
            vision_model="llava:latest",
        )
        return manager

    def test_routes_short_follow_up_to_visual_context(self) -> None:
        manager = self._manager_with_context()

        self.assertTrue(manager.should_use_for_prompt("solve"))
        self.assertTrue(manager.should_use_for_prompt("solve it"))
        self.assertTrue(manager.should_use_for_prompt("what does this say"))

    def test_does_not_route_unrelated_tool_commands_to_visual_context(self) -> None:
        manager = self._manager_with_context()

        self.assertFalse(manager.should_use_for_prompt("open YouTube"))
        self.assertFalse(manager.should_use_for_prompt("what time is it"))
        self.assertFalse(manager.should_use_for_prompt("thanks Friday"))

    def test_follow_up_prompt_preserves_prior_analysis(self) -> None:
        manager = self._manager_with_context()

        prompt = manager.build_follow_up_prompt("solve it")

        self.assertIn("previously uploaded file", prompt.lower())
        self.assertIn("The image shows a math equation.", prompt)
        self.assertIn("solve it", prompt)


if __name__ == "__main__":
    unittest.main()
