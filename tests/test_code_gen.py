from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from friday.ollama_engine import OllamaResponse, OllamaTimeout, OllamaUnavailable
from friday.tools.code_gen import CodeGeneratorTool


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 30, 12, 0, 0)


def _make_tool(root: Path, ollama: MagicMock, code_model: str = "qwen2.5-coder:7b") -> CodeGeneratorTool:
    return CodeGeneratorTool(
        root_dir=root,
        ollama=ollama,
        code_model=code_model,
        default_model="qwen3:4b",
        clock=_fixed_clock,
    )


class CodeGeneratorToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _ok(self, text: str, model: str = "qwen2.5-coder:7b") -> OllamaResponse:
        return OllamaResponse(text=text, model=model, prompt_type="text")

    def test_extracts_fenced_python_block_and_saves_to_disk(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok(
            "Here is your code:\n```python\ndef add(a, b):\n    return a + b\n```\n"
        )
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "function that adds two numbers", "language": "python"})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["language"], "python")
        self.assertIn("def add", result["data"]["code"])
        self.assertNotIn("```", result["data"]["code"])
        self.assertTrue(result["data"]["fenced"].startswith("```python\n"))
        # File was saved with .py extension
        path = Path(result["data"]["draft_path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix, ".py")
        self.assertIn("def add", path.read_text())

    def test_detects_language_from_prompt_when_unspecified(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok(
            "```rust\nfn main() { println!(\"hi\"); }\n```"
        )
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "write a hello world in rust"})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["language"], "rust")
        self.assertEqual(result["data"]["extension"], "rs")

    def test_defaults_to_python_when_no_language_hint(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok("```\nprint('hi')\n```")
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "print hello"})

        self.assertEqual(result["data"]["language"], "python")
        self.assertEqual(result["data"]["extension"], "py")

    def test_explicit_language_parameter_overrides_prompt_hint(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok("```typescript\nconst x = 1;\n```")
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "write something in rust", "language": "typescript"})

        self.assertEqual(result["data"]["language"], "typescript")
        self.assertEqual(result["data"]["extension"], "ts")

    def test_empty_prompt_returns_failure_without_calling_ollama(self) -> None:
        ollama = MagicMock()
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": ""})

        self.assertFalse(result["success"])
        ollama.generate_text.assert_not_called()

    def test_timeout_returns_friendly_message(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.side_effect = OllamaTimeout("Ollama did not finish within 240 seconds.")
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "write a python function to fizzbuzz"})

        self.assertFalse(result["success"])
        self.assertTrue(result["data"]["timeout"])
        self.assertIn("didn't finish", result["message"].lower())

    def test_ollama_unavailable_returns_failure(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.side_effect = OllamaUnavailable("not reachable")
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "write a python function to fizzbuzz"})

        self.assertFalse(result["success"])
        self.assertIn("not reachable", result["message"])

    def test_dry_run_does_not_call_ollama_and_skips_disk_write(self) -> None:
        ollama = MagicMock()
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "write a python parser", "dry_run": True})

        self.assertTrue(result["success"])
        ollama.generate_text.assert_not_called()
        self.assertIn("TODO", result["data"]["code"])
        self.assertFalse(Path(result["data"]["draft_path"]).exists())

    def test_prefers_code_model_over_default(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok("```python\npass\n```")
        tool = _make_tool(self.root, ollama, code_model="qwen2.5-coder:7b")

        tool.generate({"prompt": "noop function"})

        call_kwargs = ollama.generate_text.call_args.kwargs
        self.assertEqual(call_kwargs.get("model"), "qwen2.5-coder:7b")

    def test_falls_back_to_default_model_when_no_code_model(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok("```python\npass\n```")
        tool = _make_tool(self.root, ollama, code_model="")

        tool.generate({"prompt": "noop function"})

        call_kwargs = ollama.generate_text.call_args.kwargs
        self.assertEqual(call_kwargs.get("model"), "qwen3:4b")

    def test_falls_back_to_default_model_when_code_model_is_not_installed(self) -> None:
        ollama = MagicMock()
        ollama.status.return_value.models = ["qwen3:4b"]
        ollama.generate_text.return_value = self._ok("```python\npass\n```", model="qwen3:4b")
        tool = _make_tool(self.root, ollama, code_model="qwen2.5-coder:7b")

        tool.generate({"prompt": "noop function"})

        call_kwargs = ollama.generate_text.call_args.kwargs
        self.assertEqual(call_kwargs.get("model"), "qwen3:4b")

    def test_unfenced_response_still_extracted(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok("def foo():\n    return 42")
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "function returning 42"})

        self.assertTrue(result["success"])
        self.assertIn("def foo", result["data"]["code"])

    def test_strips_conversational_voice_prefix(self) -> None:
        ollama = MagicMock()
        ollama.generate_text.return_value = self._ok("```python\npass\n```")
        tool = _make_tool(self.root, ollama)

        result = tool.generate({"prompt": "hey friday please write a python function to sort a list"})

        self.assertTrue(result["success"])
        # The cleaned prompt should not still start with the conversational prefix.
        # We check by inspecting the prompt the tool actually passed to ollama.
        passed_prompt = ollama.generate_text.call_args.args[0]
        self.assertNotIn("hey friday", passed_prompt.lower())


if __name__ == "__main__":
    unittest.main()
