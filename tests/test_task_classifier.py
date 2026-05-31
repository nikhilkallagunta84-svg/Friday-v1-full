from __future__ import annotations

import unittest

from friday.task_classifier import classify_task


class TestClassifyTask(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(classify_task(""), "simple")

    def test_open_command(self):
        self.assertEqual(classify_task("open YouTube"), "simple")

    def test_search_command(self):
        self.assertEqual(classify_task("search AI news"), "simple")

    def test_launch_command(self):
        self.assertEqual(classify_task("launch Spotify"), "simple")

    def test_greeting(self):
        self.assertEqual(classify_task("hello"), "simple")

    def test_yes_no(self):
        self.assertEqual(classify_task("yes"), "simple")
        self.assertEqual(classify_task("no"), "simple")

    def test_what_time(self):
        self.assertEqual(classify_task("what time is it"), "simple")

    def test_tell_me_a_joke(self):
        self.assertEqual(classify_task("tell me a joke"), "simple")

    def test_normal_explanation(self):
        self.assertEqual(classify_task("explain what an API is"), "normal")

    def test_normal_help(self):
        self.assertEqual(classify_task("help me plan my day"), "normal")

    def test_normal_current_info(self):
        self.assertEqual(classify_task("what happened in AI today"), "normal")

    def test_complex_build(self):
        self.assertEqual(classify_task("build me a React app"), "complex")

    def test_complex_draft(self):
        self.assertEqual(classify_task("draft an email to John"), "complex")

    def test_complex_compare(self):
        self.assertEqual(classify_task("compare Python and JavaScript"), "complex")

    def test_code_debug_request(self):
        # "debug this code" now routes to the code model, not generic complex.
        self.assertEqual(classify_task("debug this code for me"), "code")

    def test_code_write_python(self):
        self.assertEqual(classify_task("write a python function that adds two numbers"), "code")

    def test_code_generate_javascript(self):
        self.assertEqual(classify_task("generate javascript code to fetch data"), "code")

    def test_code_write_unit_test(self):
        self.assertEqual(classify_task("write a unit test for my parser"), "code")

    def test_code_in_language(self):
        self.assertEqual(classify_task("create a rust function to parse json"), "code")

    def test_code_bare_word_is_not_code(self):
        # Bare reference shouldn't trigger code generation.
        self.assertNotEqual(classify_task("what is code"), "code")

    def test_complex_long_input(self):
        long_text = "word " * 55
        self.assertEqual(classify_task(long_text), "complex")

    def test_vision_screen(self):
        self.assertEqual(classify_task("what's on my screen"), "vision")

    def test_vision_screenshot(self):
        self.assertEqual(classify_task("take a screenshot"), "vision")

    def test_vision_read_screen(self):
        self.assertEqual(classify_task("read what is on my screen"), "vision")

    def test_vision_click_button(self):
        self.assertEqual(classify_task("click the blue continue button"), "vision")

    def test_vision_image(self):
        self.assertEqual(classify_task("analyze this image for me"), "vision")

    def test_vision_looking_at(self):
        self.assertEqual(classify_task("what am i looking at"), "vision")


if __name__ == "__main__":
    unittest.main()
