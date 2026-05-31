"""Code generation tool — drafts code from a natural-language prompt using Ollama.

Routes through a code-specialist model (e.g. qwen2.5-coder:7b) when installed,
falling back to the default reasoning model. Generated code is saved to
.friday/code-drafts/ and returned inline.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from friday.ollama_engine import (
    TIMEOUT_CODE,
    OllamaClient,
    OllamaTimeout,
    OllamaUnavailable,
)


# Map common spoken/typed language names to canonical names and file extensions.
# Keep this small — only languages the underlying coder models reliably emit.
_LANGUAGE_TABLE: Dict[str, Tuple[str, str]] = {
    "python": ("python", "py"),
    "py": ("python", "py"),
    "javascript": ("javascript", "js"),
    "js": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "ts": ("typescript", "ts"),
    "tsx": ("tsx", "tsx"),
    "jsx": ("jsx", "jsx"),
    "rust": ("rust", "rs"),
    "go": ("go", "go"),
    "golang": ("go", "go"),
    "c": ("c", "c"),
    "c++": ("cpp", "cpp"),
    "cpp": ("cpp", "cpp"),
    "c#": ("csharp", "cs"),
    "csharp": ("csharp", "cs"),
    "java": ("java", "java"),
    "kotlin": ("kotlin", "kt"),
    "swift": ("swift", "swift"),
    "ruby": ("ruby", "rb"),
    "php": ("php", "php"),
    "bash": ("bash", "sh"),
    "shell": ("bash", "sh"),
    "sh": ("bash", "sh"),
    "zsh": ("bash", "sh"),
    "sql": ("sql", "sql"),
    "html": ("html", "html"),
    "css": ("css", "css"),
    "react": ("tsx", "tsx"),
    "vue": ("vue", "vue"),
    "svelte": ("svelte", "svelte"),
    "node": ("javascript", "js"),
    "nodejs": ("javascript", "js"),
    "node.js": ("javascript", "js"),
}

# Regex for detecting a language token anywhere in the prompt.
_LANGUAGE_TOKENS_RE = re.compile(
    r"\b(python|py|javascript|js|typescript|ts|tsx|jsx|rust|go(?:lang)?|c\+\+|cpp|c#|csharp"
    r"|java|kotlin|swift|ruby|php|bash|shell|zsh|sql|html|css|react|vue|svelte|node(?:\.?js)?)\b",
    re.IGNORECASE,
)

# Regex to strip leading conversational prefixes that arrive from voice input.
_INSTRUCTION_PREFIXES = re.compile(
    r"^(?:hey\s+friday[,\s]+|friday[,\s]+|please\s+|can\s+you\s+|could\s+you\s+)+",
    re.IGNORECASE,
)


class CodeGeneratorTool:
    """Generates code via Ollama and persists the draft to disk."""

    def __init__(
        self,
        root_dir: Path,
        ollama: OllamaClient,
        code_model: str = "",
        default_model: str = "",
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.ollama = ollama
        self.code_model = code_model.strip()
        self.default_model = default_model.strip()
        self.drafts_dir = self.root_dir / ".friday" / "code-drafts"
        self._clock = clock or datetime.now

    def generate(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._clean_prompt(str(parameters.get("prompt") or parameters.get("task") or ""))
        if not prompt:
            return self._failure(
                "Tell me what code to write, boss.",
                {"prompt": ""},
            )

        requested_language = str(parameters.get("language") or "").strip()
        language, extension = self._resolve_language(requested_language, prompt)
        dry_run = bool(parameters.get("dry_run", False))
        model_override = str(parameters.get("model") or "").strip()
        model = self._pick_model(model_override)

        data: Dict[str, Any] = {
            "prompt": prompt,
            "language": language,
            "extension": extension,
            "model": model,
            "dry_run": dry_run,
        }

        if dry_run:
            stub = self._stub_code(prompt, language)
            path = self._save_draft(stub, language, extension, prompt, dry_run=True)
            data.update({"code": stub, "draft_path": str(path), "fenced": self._fence(stub, language)})
            return self._success(f"Drafted a {language} stub for {self._short(prompt)}.", data)

        try:
            response = self.ollama.generate_text(
                self._build_prompt(prompt, language),
                model=model or None,
            )
        except OllamaTimeout as exc:
            return self._failure(
                f"The {model or 'code'} model didn't finish in time. Try again — it should be faster once it's warmed up.",
                {**data, "timeout": True, "detail": str(exc)},
            )
        except OllamaUnavailable as exc:
            return self._failure(
                f"I couldn't reach the code model: {exc}",
                {**data, "detail": str(exc)},
            )

        code = self._extract_code(response.text, language)
        if not code:
            return self._failure(
                "The model replied but I couldn't extract a clean code block, boss.",
                {**data, "raw_response": response.text[:600]},
            )

        path = self._save_draft(code, language, extension, prompt, dry_run=False)
        data.update(
            {
                "code": code,
                "draft_path": str(path),
                "fenced": self._fence(code, language),
                "model": response.model,
            }
        )
        return self._success(
            f"Drafted a {language} snippet — saved to {path.name}.",
            data,
        )

    # --- model selection ---------------------------------------------------

    def _pick_model(self, override: str) -> str:
        if override:
            return override
        if self.code_model and self._model_available(self.code_model):
            return self.code_model
        return self.default_model

    def _model_available(self, model_name: str) -> bool:
        try:
            status = self.ollama.status()
        except BaseException:
            return True
        models = getattr(status, "models", None)
        if not isinstance(models, list):
            return True
        if not models:
            return False
        return any(model == model_name or model.startswith(model_name + ":") for model in models)

    # --- prompt + parsing helpers -----------------------------------------

    def _build_prompt(self, user_request: str, language: str) -> str:
        return (
            "You are FRIDAY's local code generator.\n"
            f"Write {language} code that satisfies the request.\n"
            "Hard rules:\n"
            "- Return ONLY one fenced code block, starting with ```" + language + " and ending with ```.\n"
            "- No prose before or after the block.\n"
            "- No XML/HTML wrappers, no <think>, no commentary.\n"
            "- Include short inline comments where they materially help.\n"
            "- Prefer the standard library; avoid invented APIs.\n"
            "- If the request is ambiguous, choose reasonable defaults rather than asking.\n"
            f"\nRequest:\n{user_request}\n"
        )

    @staticmethod
    def _fence(code: str, language: str) -> str:
        clean = code.rstrip()
        return f"```{language}\n{clean}\n```"

    @staticmethod
    def _extract_code(response: str, language: str) -> str:
        if not response:
            return ""
        # Prefer the first fenced block; tolerate ``` with or without a language tag.
        fenced = re.search(r"```(?:[a-zA-Z0-9_+\-#.]*\n)?(.*?)```", response, re.DOTALL)
        if fenced:
            return fenced.group(1).strip("\n")
        # No fence — strip leading/trailing prose lines if present.
        lines = response.strip().splitlines()
        if not lines:
            return ""
        return "\n".join(lines).strip()

    @staticmethod
    def _clean_prompt(value: str) -> str:
        clean = " ".join(str(value).split())
        clean = _INSTRUCTION_PREFIXES.sub("", clean).strip()
        return clean.strip(" .?!")

    def _resolve_language(self, explicit: str, prompt: str) -> Tuple[str, str]:
        candidate = explicit.lower().strip()
        if candidate in _LANGUAGE_TABLE:
            return _LANGUAGE_TABLE[candidate]
        match = _LANGUAGE_TOKENS_RE.search(prompt)
        if match:
            token = match.group(1).lower()
            if token in _LANGUAGE_TABLE:
                return _LANGUAGE_TABLE[token]
        return ("python", "py")

    @staticmethod
    def _short(text: str, limit: int = 60) -> str:
        clean = " ".join(text.split())
        return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"

    # --- persistence ------------------------------------------------------

    def _save_draft(
        self,
        code: str,
        language: str,
        extension: str,
        prompt: str,
        dry_run: bool,
    ) -> Path:
        timestamp = self._clock().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", prompt.lower()).strip("-")[:48] or language
        filename = f"{timestamp}-{slug}.{extension}"
        path = self.drafts_dir / filename
        if not dry_run:
            self.drafts_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(code.rstrip() + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _stub_code(prompt: str, language: str) -> str:
        clean = " ".join(prompt.split())
        if language in {"python", "py"}:
            return f'"""TODO: implement {clean}."""\n\n\ndef main() -> None:\n    pass\n'
        if language in {"javascript", "typescript", "tsx", "jsx", "vue", "svelte"}:
            return f"// TODO: implement {clean}\nexport function main() {{}}\n"
        return f"// TODO: implement {clean}\n"

    # --- result envelopes -------------------------------------------------

    @staticmethod
    def _success(message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    @staticmethod
    def _failure(message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}
