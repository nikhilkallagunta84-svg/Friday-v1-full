from __future__ import annotations

import os
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

from friday.google_accounts import preferred_google_url


class ProductivityDraftTool:
    def __init__(
        self,
        root_dir: Path,
        model: str = "",
        ollama_host: str = "",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        opener: Callable[..., subprocess.Popen[str]] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.model = model or os.environ.get("FRIDAY_OLLAMA_MODEL", "qwen3:4b")
        self.ollama_host = (ollama_host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.drafts_dir = root_dir / ".friday" / "drafts"
        self._runner = runner or subprocess.run
        self._opener = opener or subprocess.Popen
        self._sleep = sleeper or time.sleep

    def write_report(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        topic = self._clean_prompt(parameters)
        document_type = str(parameters.get("document_type") or "report").strip().lower()
        target = self._normalize_document_target(str(parameters.get("target") or "google_docs"))
        dry_run = bool(parameters.get("dry_run", False))
        if not topic:
            return self._failure("Tell me what the report should be about, sir.", {"target": target})

        use_ollama_draft = bool(parameters.get("use_ollama_draft", False))
        generation_status = "generated" if use_ollama_draft or dry_run else "instant_template"
        if dry_run:
            content = self._build_report(topic, document_type, dry_run)
        elif use_ollama_draft:
            try:
                content = self._build_report(topic, document_type, dry_run)
            except Exception as exc:
                generation_status = f"fallback: {exc}"
                content = self._fallback_report(topic, document_type)
        else:
            content = self._fallback_report(topic, document_type)
        title = self._title_from_topic(topic, document_type)
        path = self._save_draft(title, content, "report", dry_run)
        copied = self._copy_to_clipboard(content, dry_run)
        url = preferred_google_url("https://docs.new" if target == "google_docs" else "https://docs.google.com/document/u/0/create")
        opened = self._open_url(url, dry_run)
        pasted = self._paste_into_front_window(opened and copied, dry_run, wait_seconds=4.0)
        data = {
            "target": target,
            "topic": topic,
            "document_type": document_type,
            "draft_path": str(path),
            "url": url,
            "copied_to_clipboard": copied,
            "opened": opened,
            "pasted": pasted,
            "dry_run": dry_run,
            "generation_status": generation_status,
        }
        if opened and pasted:
            return self._success(f"I drafted the {document_type}, opened Google Docs, and pasted it in, boss.", data)
        if opened and copied:
            return self._success(
                f"I drafted the {document_type}, opened Google Docs, and copied it to the clipboard. Paste is blocked until macOS Accessibility permission is allowed.",
                data,
            )
        if copied:
            return self._success(f"I drafted the {document_type} and copied it to the clipboard, but I couldn't open Google Docs.", data)
        return self._failure(f"I drafted the {document_type}, but couldn't copy or open Google Docs.", data)

    def make_slides(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        topic = self._clean_prompt(parameters)
        target = self._normalize_slide_target(str(parameters.get("target") or "gamma"))
        dry_run = bool(parameters.get("dry_run", False))
        if not topic:
            return self._failure("Tell me what the slides should be about, sir.", {"target": target})

        use_ollama_draft = bool(parameters.get("use_ollama_draft", False))
        generation_status = "generated" if use_ollama_draft or dry_run else "instant_template"
        if dry_run:
            content = self._build_slides(topic, target, dry_run)
        elif use_ollama_draft:
            try:
                content = self._build_slides(topic, target, dry_run)
            except Exception as exc:
                generation_status = f"fallback: {exc}"
                content = self._fallback_slides(topic, target)
        else:
            content = self._fallback_slides(topic, target)
        title = self._title_from_topic(topic, "slides")
        path = self._save_draft(title, content, "slides", dry_run)
        copied = self._copy_to_clipboard(content, dry_run)
        url = preferred_google_url(self._slide_target_url(target))
        opened = self._open_url(url, dry_run)
        pasted = self._paste_into_front_window(opened and copied, dry_run, wait_seconds=4.0)
        data = {
            "target": target,
            "topic": topic,
            "draft_path": str(path),
            "url": url,
            "copied_to_clipboard": copied,
            "opened": opened,
            "pasted": pasted,
            "dry_run": dry_run,
            "generation_status": generation_status,
        }
        display_target = "Gamma" if target == "gamma" else "Google Slides"
        if opened and pasted:
            return self._success(f"I drafted the slide deck, opened {display_target}, and pasted the prompt in, boss.", data)
        if opened and copied:
            return self._success(
                f"I drafted the slide deck, opened {display_target}, and copied the prompt to the clipboard. Paste is blocked until macOS Accessibility permission is allowed.",
                data,
            )
        if copied:
            return self._success(f"I drafted the slide deck and copied it to the clipboard, but I couldn't open {display_target}.", data)
        return self._failure(f"I drafted the slide deck, but couldn't copy or open {display_target}.", data)

    def _build_report(self, topic: str, document_type: str, dry_run: bool) -> str:
        if dry_run:
            return f"# {self._title_from_topic(topic, document_type)}\n\nDraft report about {topic}."
        prompt = (
            "You are FRIDAY writing a polished report draft for the user.\n"
            "Create original, useful writing. Do not claim the user personally did research unless supplied.\n"
            "If the topic sounds like schoolwork, write it as a study draft the user can review and edit, not as a submitted final.\n"
            "Use Markdown that pastes cleanly into Google Docs.\n"
            "Include: title, short introduction, clear section headings, evidence-style explanation, conclusion, and a short 'Sources to verify' section with search suggestions instead of fake citations.\n"
            "Keep it concise: 500-800 words maximum.\n\n"
            f"Document type: {document_type}\n"
            f"Topic/prompt: {topic}\n"
        )
        return self._generate_text(prompt)

    def _build_slides(self, topic: str, target: str, dry_run: bool) -> str:
        if dry_run:
            return f"Create an 8-slide deck about {topic} with title, agenda, main points, visuals, and conclusion."
        platform_hint = "Gamma" if target == "gamma" else "Google Slides"
        prompt = (
            f"You are FRIDAY preparing a {platform_hint} presentation prompt.\n"
            "Create content that can be pasted directly into a slide-generation tool.\n"
            "Return Markdown only. Include a strong title, visual style direction, exactly 7 slide sections, brief speaker notes, and suggested visuals for each slide.\n"
            "Do not invent fake citations. If sources are needed, add a final 'Sources to verify' slide with search suggestions.\n\n"
            f"Presentation topic/prompt: {topic}\n"
        )
        return self._generate_text(prompt)

    def _generate_text(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 420},
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.ollama_host + "/api/generate",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError("Ollama draft generation timed out or is unavailable") from exc
        text = str(payload.get("response", "")).strip()
        if not text:
            raise RuntimeError(f"Ollama model {self.model} returned an empty draft.")
        return text

    def _fallback_report(self, topic: str, document_type: str) -> str:
        title = self._title_from_topic(topic, document_type)
        return (
            f"# {title}\n\n"
            "## Introduction\n"
            f"This {document_type} explains the key ideas behind {topic} and gives a clear structure to expand from.\n\n"
            "## Main Points\n"
            f"- Define the topic: {topic}.\n"
            "- Explain why it matters.\n"
            "- Add 2-3 concrete examples.\n"
            "- Compare benefits, limitations, and real-world impact.\n\n"
            "## Draft Body\n"
            f"{topic.title()} is important because it connects practical needs with broader changes in technology, society, or everyday life. "
            "A strong final version should explain the background, show specific examples, and evaluate both strengths and concerns.\n\n"
            "## Conclusion\n"
            "The strongest conclusion should restate the main claim, summarize the evidence, and leave the reader with one clear takeaway.\n\n"
            "## Sources To Verify\n"
            f"- Search for recent articles about {topic}\n"
            f"- Look up official or educational sources related to {topic}\n"
        )

    def _fallback_slides(self, topic: str, target: str) -> str:
        platform = "Gamma" if target == "gamma" else "Google Slides"
        return (
            f"# {topic.title()} Presentation\n\n"
            f"Create a polished {platform} deck with a futuristic but clean visual style.\n\n"
            "## Slide 1: Title\n"
            f"Title: {topic.title()}\nVisual: bold opener image or abstract concept visual.\n\n"
            "## Slide 2: Why It Matters\n"
            "Explain the importance in 3 concise bullets.\n\n"
            "## Slide 3: Core Idea\n"
            "Define the main concept clearly.\n\n"
            "## Slide 4: Real-World Examples\n"
            "Show 2-3 practical examples.\n\n"
            "## Slide 5: Benefits\n"
            "Summarize the biggest advantages.\n\n"
            "## Slide 6: Challenges\n"
            "Explain risks, limits, or open questions.\n\n"
            "## Slide 7: Conclusion\n"
            "End with the key takeaway and a simple call to action.\n\n"
            "## Sources To Verify\n"
            f"Search for current credible sources about {topic} before presenting.\n"
        )

    def _save_draft(self, title: str, content: str, kind: str, dry_run: bool) -> Path:
        filename = re.sub(r"[^a-zA-Z0-9_.-]+", "-", title.lower()).strip("-")[:72] or kind
        path = self.drafts_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{filename}.md"
        if not dry_run:
            self.drafts_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return path

    def _copy_to_clipboard(self, content: str, dry_run: bool) -> bool:
        if dry_run:
            return True
        try:
            completed = self._runner(["pbcopy"], input=content, capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired, Exception):
            return False
        return completed.returncode == 0

    def _open_url(self, url: str, dry_run: bool) -> bool:
        if dry_run:
            return True
        try:
            self._opener(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, Exception):
            return False
        return True

    def _paste_into_front_window(self, should_try: bool, dry_run: bool, wait_seconds: float) -> bool:
        if dry_run:
            return should_try
        if not should_try:
            return False
        self._sleep(wait_seconds)
        script = """
tell application "System Events"
  if UI elements enabled is false then error "Accessibility permission is required to paste into the browser."
  keystroke "v" using command down
end tell
"""
        try:
            completed = self._runner(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired, Exception):
            return False
        return completed.returncode == 0

    def _clean_prompt(self, parameters: Dict[str, Any]) -> str:
        value = str(parameters.get("prompt") or parameters.get("topic") or parameters.get("query") or "").strip()
        value = re.sub(r"\s+(?:for\s+me|please)$", "", value, flags=re.I).strip()
        return value.strip(" .'\"")

    def _normalize_document_target(self, target: str) -> str:
        clean = " ".join(target.lower().strip().split())
        return "google_docs" if clean in {"", "docs", "google docs", "google_docs", "document"} else clean

    def _normalize_slide_target(self, target: str) -> str:
        clean = " ".join(target.lower().strip().split())
        if clean in {"google slides", "google_slides", "slides"}:
            return "google_slides"
        return "gamma"

    def _slide_target_url(self, target: str) -> str:
        if target == "google_slides":
            return "https://slides.new"
        return "https://gamma.app/create/generate"

    def _title_from_topic(self, topic: str, kind: str) -> str:
        clean = re.sub(r"\s+", " ", topic.strip(" .'\""))
        words = clean.split()[:10]
        base = " ".join(words) if words else kind
        return f"{base.title()} {kind.title()}"

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}
