from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote, urlencode

from friday.google_accounts import account_chooser_url, classroom_google_account, preferred_google_url


BROWSER_WEBSITE_ALIASES = {
    "ap classroom": "https://myap.collegeboard.org/",
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/",
    "github": "https://github.com/",
    "gmail": "https://mail.google.com/",
    "google": "https://www.google.com/",
    "google classroom": "https://classroom.google.com/",
    "google docs": "https://docs.google.com/",
    "google drive": "https://drive.google.com/",
    "instagram": "https://www.instagram.com/",
    "reddit": "https://www.reddit.com/",
    "youtube": "https://www.youtube.com/",
}


class BrowserControlTool:
    def __init__(self, root_dir: Path, reasoning_model: str = "", vision_model: str = "", ollama_host: str = "") -> None:
        self.root_dir = root_dir
        self.profile_dir = root_dir / ".friday" / "browser-profile"
        self.screenshot_dir = root_dir / ".friday" / "browser-screenshots"
        self.ollama_host = ollama_host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.reasoning_model = reasoning_model or os.environ.get("FRIDAY_OLLAMA_MODEL", os.environ.get("OLLAMA_MODEL", "qwen3:4b"))
        self.vision_model = vision_model or os.environ.get("FRIDAY_VISION_MODEL", "llama3.2-vision:11b")
        self.browser_channel = os.environ.get("FRIDAY_BROWSER_CHANNEL", "chrome").strip() or "chrome"
        self.classroom_account = classroom_google_account()
        self.classroom_index_path = root_dir / ".friday" / "classroom-index.json"
        self._opener = shutil.which("open")

    def run_task(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        task = str(parameters.get("task") or parameters.get("prompt") or "").strip()
        if not task:
            return self._failure("Browser task needs a prompt.")
        confirmed = bool(parameters.get("confirmed", False))
        if self._is_classroom_task(task, parameters):
            return self._run_classroom_task(task, parameters, confirmed=confirmed)
        if self._requires_confirmation(task, parameters) and not confirmed:
            return {
                "success": False,
                "requires_confirmation": True,
                "message": "This browser task may submit, send, purchase, delete, log in, or affect schoolwork. Say confirm before I continue.",
                "data": {"task": task},
            }

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return self._failure(f"Playwright is not installed in this environment: {exc}")

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        visible = bool(parameters.get("visible", True))
        headless = bool(parameters.get("headless", not visible))
        actions = parameters.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        start_url = str(parameters.get("url") or "").strip() or self._infer_start_url(task)
        search_query, search_engine = self._infer_search(task)
        performed: List[str] = []
        page_text = ""

        try:
            with sync_playwright() as playwright:
                context = self._launch_context(playwright, headless)
                page = context.new_page()
                try:
                    if start_url:
                        try:
                            self._goto(page, start_url)
                        except PlaywrightError as exc:
                            handoff = self._signin_handoff_if_needed(start_url, task, f"Playwright could not load the sign-in page: {exc}")
                            if handoff:
                                return handoff
                            raise
                        performed.append(f"Opened {start_url}")
                        handoff = self._signin_handoff_if_needed(page.url, task, "Google or another sign-in page needs your real Chrome session.", page=page)
                        if handoff:
                            return handoff
                    if actions:
                        for action in actions[:12]:
                            performed.append(self._run_action(page, action))
                    elif search_query:
                        if not start_url:
                            self._goto(page, self._search_home(search_engine))
                            performed.append(f"Opened {search_engine}")
                        self._perform_search(page, search_query, search_engine)
                        performed.append(f"Searched for {search_query}")
                    else:
                        planned_actions = self._plan_actions(page, task, confirmed=confirmed)
                        if planned_actions:
                            for action in planned_actions[:10]:
                                performed.append(self._run_action(page, action))
                        else:
                            inferred = self._run_simple_prompt_action(page, task)
                            if inferred:
                                performed.append(inferred)
                    page.wait_for_timeout(600)
                    page_text = self._page_text(page)
                    title = page.title()
                    current_url = page.url
                finally:
                    context.close()
        except PlaywrightError as exc:
            fallback = self._screen_fallback(task, confirmed, f"Playwright failed: {exc}")
            if fallback:
                return fallback
            return self._failure(f"Browser control failed: {exc}")
        except BaseException as exc:
            fallback = self._screen_fallback(task, confirmed, f"Playwright failed: {exc}")
            if fallback:
                return fallback
            return self._failure(f"Browser control failed: {exc}")

        summary = self._summarize_page_text(page_text)
        message = "Browser task completed."
        if performed:
            message = f"Browser task completed: {'; '.join(performed[:4])}."
        return self._success(
            message,
            {
                "task": task,
                "url": current_url,
                "title": title,
                "performed": performed,
                "page_summary": summary,
                "profile_dir": str(self.profile_dir),
            },
        )

    def _launch_context(self, playwright: Any, headless: bool) -> Any:
        kwargs = {
            "user_data_dir": str(self.profile_dir),
            "headless": headless,
            "accept_downloads": True,
            "viewport": {"width": 1440, "height": 900},
        }
        if self.browser_channel and self.browser_channel.lower() not in {"chromium", "default", "none"}:
            try:
                return playwright.chromium.launch_persistent_context(channel=self.browser_channel, **kwargs)
            except BaseException:
                pass
        return playwright.chromium.launch_persistent_context(**kwargs)

    def _goto(self, page: Any, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

    def _run_action(self, page: Any, action: Any) -> str:
        if not isinstance(action, dict):
            return "Skipped invalid action"
        kind = str(action.get("action") or action.get("type") or "").strip().lower()
        if kind in {"navigate", "open", "go_to"}:
            url = self._normalize_url(str(action.get("url") or ""))
            self._goto(page, url)
            return f"Navigated to {url}"
        if kind == "click":
            selector = str(action.get("selector") or "").strip()
            text = str(action.get("text") or action.get("target") or action.get("label") or "").strip()
            x = action.get("x")
            y = action.get("y")
            if selector:
                page.locator(selector).first.click(timeout=8000)
                return f"Clicked selector {selector}"
            if text:
                self._click_text_or_vision(page, text)
                return f"Clicked text {text}"
            if x is not None and y is not None:
                page.mouse.click(float(x), float(y))
                return f"Clicked coordinates {x}, {y}"
            return "Skipped click without selector, text, or coordinates"
        if kind in {"fill", "set"}:
            value = str(action.get("value") or action.get("text") or "").strip()
            selector = str(action.get("selector") or "").strip()
            label = str(action.get("label") or action.get("target") or "").strip()
            placeholder = str(action.get("placeholder") or "").strip()
            if selector:
                page.locator(selector).first.fill(value, timeout=8000)
                return f"Filled selector {selector}"
            if label:
                try:
                    page.get_by_label(label, exact=False).first.fill(value, timeout=8000)
                except BaseException:
                    page.get_by_placeholder(label, exact=False).first.fill(value, timeout=8000)
                return f"Filled label {label}"
            if placeholder:
                page.get_by_placeholder(placeholder, exact=False).first.fill(value, timeout=8000)
                return f"Filled placeholder {placeholder}"
            return "Skipped fill without selector, label, or placeholder"
        if kind == "type":
            text = str(action.get("text") or action.get("value") or "")
            page.keyboard.type(text, delay=int(action.get("delay_ms", 15) or 15))
            return "Typed text"
        if kind == "press":
            key = str(action.get("key") or "Enter")
            page.keyboard.press(key)
            return f"Pressed {key}"
        if kind == "wait":
            selector = str(action.get("selector") or "").strip()
            ms = int(action.get("ms", 1000) or 1000)
            if selector:
                page.locator(selector).first.wait_for(timeout=max(ms, 1000))
                return f"Waited for {selector}"
            page.wait_for_timeout(ms)
            return f"Waited {ms}ms"
        if kind == "screenshot":
            name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(action.get("name") or "browser.png"))
            path = self.screenshot_dir / name
            page.screenshot(path=str(path), full_page=bool(action.get("full_page", False)))
            return f"Saved screenshot {path}"
        if kind == "extract":
            return "Extracted page text"
        return f"Skipped unknown action {kind or 'blank'}"

    def _is_classroom_task(self, task: str, parameters: Dict[str, Any]) -> bool:
        if str(parameters.get("workflow", "")).lower() == "google_classroom":
            return True
        return bool(re.search(r"\b(google\s+classroom|classroom|class\s*work|classwork|assignment|assignments)\b", task, re.I))

    def _run_classroom_task(self, task: str, parameters: Dict[str, Any], confirmed: bool) -> Dict[str, Any]:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return self._failure(f"Playwright is not installed in this environment: {exc}")

        account = str(parameters.get("account") or self._classroom_account_from_task(task) or self.classroom_account).strip()
        parsed = self._parse_classroom_request(task)
        class_query = str(parameters.get("class_name") or parsed.get("class_name") or "").strip()
        assignment_query = str(parameters.get("assignment_name") or parsed.get("assignment_name") or "").strip()
        latest = bool(parameters.get("latest", parsed.get("latest", False)))
        existing_index = self._load_classroom_index()
        selection = self._resolve_classroom_selection(existing_index, class_query, assignment_query, latest, str(parsed.get("action", "")))
        if not confirmed and self._classroom_needs_match_confirmation(parsed, class_query, assignment_query, latest):
            confirmation = self._classroom_confirmation_result(task, parsed, selection, class_query, assignment_query, latest)
            if confirmation:
                return confirmation

        classroom_url = self._classroom_url(account)
        visible = bool(parameters.get("visible", True))
        headless = bool(parameters.get("headless", not visible))
        performed: List[str] = []
        page_text = ""
        title = ""
        current_url = classroom_url

        try:
            with sync_playwright() as playwright:
                context = self._launch_context(playwright, headless)
                page = context.new_page()
                try:
                    try:
                        self._goto(page, classroom_url)
                    except PlaywrightError as exc:
                        return self._open_classroom_in_real_chrome(
                            account,
                            f"Playwright could not load Classroom: {exc}",
                            parsed,
                        )
                    performed.append(f"Opened Google Classroom for {account}")
                    if self._page_needs_signin(page):
                        return self._open_classroom_in_real_chrome(account, "Google Classroom needs the signed-in Chrome account.", parsed)

                    index = self._extract_classroom_index(page, account)
                    selection = self._resolve_classroom_selection(index, class_query, assignment_query, latest, str(parsed.get("action", "")))
                    class_item = selection.get("class") if isinstance(selection.get("class"), dict) else None
                    assignment_item = selection.get("assignment") if isinstance(selection.get("assignment"), dict) else None
                    class_name = str(class_item.get("name", "") if class_item else class_query).strip()
                    assignment_name = str(assignment_item.get("name", "") if assignment_item else assignment_query).strip()
                    if class_name:
                        clicked = self._open_indexed_item(page, class_item, class_name)
                        performed.append(f"Opened class {class_name}" if clicked else f"Could not find class {class_name}")
                        page.wait_for_timeout(1200)
                        self._open_classwork_tab(page, performed)
                        class_assignments = self._extract_assignments_from_page(page)
                        if class_assignments:
                            index = self._merge_class_assignments(index, class_name, class_assignments)
                        selection = self._resolve_classroom_selection(index, class_query or class_name, assignment_query, latest, str(parsed.get("action", "")))
                        assignment_item = selection.get("assignment") if isinstance(selection.get("assignment"), dict) else None
                        assignment_name = str(assignment_item.get("name", "") if assignment_item else assignment_name).strip()
                    elif parsed.get("action") in {"organize", "list_assignments", "latest_assignment"}:
                        self._open_to_do_if_available(page, performed)
                        page.wait_for_timeout(1200)
                        assignments = self._extract_assignments_from_page(page)
                        if assignments:
                            index["assignments"] = assignments
                        selection = self._resolve_classroom_selection(index, class_query, assignment_query, latest, str(parsed.get("action", "")))
                        class_item = selection.get("class") if isinstance(selection.get("class"), dict) else None
                        assignment_item = selection.get("assignment") if isinstance(selection.get("assignment"), dict) else None
                        class_name = str(class_item.get("name", "") if class_item else class_name).strip()
                        assignment_name = str(assignment_item.get("name", "") if assignment_item else assignment_name).strip()

                    if not confirmed and self._classroom_needs_match_confirmation(parsed, class_query, assignment_query, latest):
                        self._save_classroom_index(index)
                        confirmation = self._classroom_confirmation_result(task, parsed, selection, class_query, assignment_query, latest)
                        if confirmation:
                            return confirmation
                    if parsed.get("action") == "turn_in" and not assignment_name:
                        self._save_classroom_index(index)
                        return self._failure("I need a class and assignment match before I can turn anything in.")
                    if assignment_name:
                        clicked = self._open_indexed_item(page, assignment_item, assignment_name)
                        performed.append(f"Opened assignment {assignment_name}" if clicked else f"Could not find assignment {assignment_name}")
                    if parsed.get("action") == "turn_in":
                        turned_in = self._click_turn_in_controls(page, performed)
                        if not turned_in:
                            performed.append("Could not find a Turn in, Submit, or Mark as done control")

                    self._remember_classroom_selection(index, class_name, assignment_name)
                    self._save_classroom_index(index)
                    page_text = self._page_text(page)
                    title = page.title()
                    current_url = page.url
                finally:
                    context.close()
        except PlaywrightError as exc:
            return self._open_classroom_in_real_chrome(account, f"Playwright Classroom automation failed: {exc}", parsed)
        except BaseException as exc:
            return self._failure(f"Google Classroom workflow failed: {exc}")

        summary = self._classroom_summary(index)
        message = "Google Classroom workflow completed."
        if performed:
            message = f"Google Classroom workflow completed: {'; '.join(performed[:5])}."
        if assignment_name and parsed.get("action") in {"do_assignment", "latest_assignment"}:
            message += " I opened or located the assignment workspace; I can help you understand and draft work, but I will not silently submit graded work."
        if assignment_name and parsed.get("action") == "turn_in":
            message += " I only attempted the turn-in action after your confirmation."
        return self._success(
            message,
            {
                "task": task,
                "account": account,
                "url": current_url,
                "title": title,
                "performed": performed,
                "matched_class": class_name,
                "matched_assignment": assignment_name,
                "classroom": summary,
                "page_summary": self._summarize_page_text(page_text),
                "index_path": str(self.classroom_index_path),
            },
        )

    def _classroom_account_from_task(self, task: str) -> str:
        match = re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", task, re.I)
        return match.group(0) if match else ""

    def _classroom_url(self, account: str) -> str:
        if account:
            return "https://classroom.google.com/?" + urlencode({"authuser": account})
        return "https://classroom.google.com/"

    def _classroom_account_chooser_url(self, account: str) -> str:
        continue_url = self._classroom_url(account)
        return account_chooser_url(continue_url, account)

    def _open_classroom_in_real_chrome(self, account: str, reason: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
        url = self._classroom_account_chooser_url(account)
        opened = self._open_real_chrome(url)
        if not opened:
            return self._failure("I could not open Google Classroom in Chrome.")
        return self._success(
            (
                f"I opened Google Classroom in Chrome using the school account selector for {account}. "
                "If Chrome asks, choose that account and finish sign-in. After that, ask me for the class or assignment again. "
                "I do not read, store, or type your password."
            ),
            {
                "url": url,
                "account": account,
                "signin_handoff": True,
                "reason": reason,
                "parsed_request": parsed,
            },
        )

    def _parse_classroom_request(self, task: str) -> Dict[str, Any]:
        text = " ".join(task.lower().split())
        parsed: Dict[str, Any] = {"action": "open", "latest": False, "class_name": "", "assignment_name": ""}
        after_classroom = re.sub(r"^.*?\b(?:google\s+)?classroom\b", "", task, flags=re.I).strip()
        class_then_task = re.search(
            r"\b(?:go to|open|choose|select|enter)\s+(.+?)\s+(?:and|then)\s+(.+)$",
            after_classroom,
            re.I,
        )
        if class_then_task:
            parsed["class_name"] = class_then_task.group(1).strip(" .'\"")
            classroom_action = class_then_task.group(2).strip(" .'\"")
            lowered_action = classroom_action.lower()
            if re.search(r"\b(turn\s+(?:it\s+)?in|submit(?:\s+it)?|hand\s+(?:it\s+)?in|mark\s+(?:it\s+)?as\s+done)\b", lowered_action):
                parsed["action"] = "turn_in"
            elif re.search(r"\b(do|complete|answer|work on|start)\b", lowered_action):
                parsed["action"] = "do_assignment"
            elif re.search(r"\b(open|go to)\b", lowered_action):
                parsed["action"] = "open"
            if re.search(r"\b(latest|newest|most recent|next|first)\b.*\bassignment\b|\bassignment\b.*\b(latest|newest|most recent|next|first)\b", lowered_action):
                parsed["action"] = "latest_assignment" if parsed["action"] != "turn_in" else "turn_in"
                parsed["latest"] = True
            if not parsed["latest"]:
                assignment = re.sub(
                    r"^(?:do|complete|answer|work\s+on|start|open|go\s+to|turn\s+in|submit|hand\s+in|mark\s+as\s+done)\s+",
                    "",
                    classroom_action,
                    flags=re.I,
                )
                assignment = re.sub(r"^(?:the|my|an|a)\s+", "", assignment, flags=re.I)
                assignment = re.sub(r"\s+assignment$", "", assignment, flags=re.I)
                if assignment and assignment.lower() not in {"it", "that"}:
                    parsed["assignment_name"] = assignment.strip(" .'\"")
        if re.search(r"\b(organize|index|remember|scan|list)\b", text):
            parsed["action"] = "organize"
        if re.search(r"\b(assignments|classwork|to do|todo|missing|due)\b", text):
            parsed["action"] = "list_assignments"
        if re.search(r"\b(latest|newest|most recent|next|first)\b.*\bassignment\b|\bassignment\b.*\b(latest|newest|most recent|next|first)\b", text):
            parsed["action"] = "latest_assignment"
            parsed["latest"] = True
        if re.search(r"\b(do|complete|answer|work on|start)\b.*\bassignment\b|\bassignment\b.*\b(do|complete|answer|work on|start)\b", text):
            parsed["action"] = "do_assignment"
        if re.search(r"\b(turn\s+(?:it\s+)?in|submit(?:\s+it)?|hand\s+(?:it\s+)?in|mark\s+(?:it\s+)?as\s+done)\b", text):
            parsed["action"] = "turn_in"
        class_patterns = [
            r"\bin\s+(?:my\s+)?(.+?)\s+class\b",
            r"\bfor\s+(?:my\s+)?(.+?)\s+class\b",
            r"\bclass\s+(.+?)(?:\s+assignment|\s+latest|\s+due|$)",
        ]
        class_text = re.sub(r"^(?:turn\s+(?:it\s+)?in|submit(?:\s+it)?|hand\s+(?:it\s+)?in|mark\s+(?:it\s+)?as\s+done)\s+", "", task, flags=re.I).strip()
        for pattern in class_patterns:
            match = re.search(pattern, class_text, re.I)
            if match:
                parsed["class_name"] = match.group(1).strip(" .'\"")
                break
        assignment_patterns = [
            r"\bassignment\s+(?:called|named|titled)\s+(.+)$",
            r"\b(?:turn\s+in|submit|hand\s+in)\s+(.+?)\s+assignment\b",
            r"\b(?:turn\s+in|submit|hand\s+in)\s+assignment\s+(.+?)(?:\s+(?:in|for)\s+.+?\s+class\b|$)",
            r"\bopen\s+(.+?)\s+assignment\b",
            r"\bdo\s+(.+?)\s+assignment\b",
            r"\bwork\s+on\s+(.+?)\s+assignment\b",
        ]
        if not parsed.get("latest"):
            for pattern in assignment_patterns:
                match = re.search(pattern, task, re.I)
                if match:
                    parsed["assignment_name"] = match.group(1).strip(" .'\"")
                    break
        return parsed

    def _classroom_needs_match_confirmation(self, parsed: Dict[str, Any], class_query: str, assignment_query: str, latest: bool) -> bool:
        action = str(parsed.get("action", ""))
        if action in {"latest_assignment", "do_assignment", "turn_in"}:
            return True
        return bool(assignment_query or (class_query and action == "open"))

    def _resolve_classroom_selection(
        self,
        index: Dict[str, Any],
        class_query: str,
        assignment_query: str,
        latest: bool,
        action: str,
    ) -> Dict[str, Any]:
        class_candidates = [item for item in index.get("classes", []) if isinstance(item, dict) and item.get("name")]
        last_selection = index.get("last_selection", {}) if isinstance(index.get("last_selection"), dict) else {}
        effective_class_query = class_query
        effective_assignment_query = assignment_query
        if action == "turn_in":
            effective_class_query = effective_class_query or str(last_selection.get("class_name") or "")
            effective_assignment_query = effective_assignment_query or str(last_selection.get("assignment_name") or "")

        class_item, class_score = self._best_named_match(effective_class_query, class_candidates)
        assignment_candidates = self._assignment_candidates(index, class_item)
        assignment_item: Dict[str, Any] | None = None
        assignment_score = 0.0
        if effective_assignment_query:
            assignment_item, assignment_score = self._best_named_match(effective_assignment_query, assignment_candidates)
        elif latest and assignment_candidates:
            assignment_item = assignment_candidates[0]
            assignment_score = 1.0

        if assignment_item and not class_item:
            inferred_class = str(assignment_item.get("class_name") or "")
            if inferred_class:
                class_item, class_score = self._best_named_match(inferred_class, class_candidates)
        return {
            "class": class_item,
            "class_score": class_score,
            "class_query": effective_class_query,
            "class_candidates": class_candidates,
            "assignment": assignment_item,
            "assignment_score": assignment_score,
            "assignment_query": effective_assignment_query,
            "assignment_candidates": assignment_candidates,
        }

    def _classroom_confirmation_result(
        self,
        task: str,
        parsed: Dict[str, Any],
        selection: Dict[str, Any],
        class_query: str,
        assignment_query: str,
        latest: bool,
    ) -> Dict[str, Any] | None:
        action = str(parsed.get("action", "open"))
        class_item = selection.get("class") if isinstance(selection.get("class"), dict) else None
        assignment_item = selection.get("assignment") if isinstance(selection.get("assignment"), dict) else None
        class_candidates = [item for item in selection.get("class_candidates", []) if isinstance(item, dict)]
        assignment_candidates = [item for item in selection.get("assignment_candidates", []) if isinstance(item, dict)]
        effective_class_query = str(selection.get("class_query") or class_query).strip()
        effective_assignment_query = str(selection.get("assignment_query") or assignment_query).strip()

        if effective_class_query and not class_item:
            if class_candidates:
                names = ", ".join(str(item.get("name", "")) for item in class_candidates[:6])
                return self._failure(f"I could not match the class '{effective_class_query}'. I found these classes: {names}.")
            return self._unindexed_classroom_confirmation(task, action, effective_class_query, effective_assignment_query, latest)
        needs_assignment = bool(latest or effective_assignment_query or action in {"latest_assignment", "do_assignment", "turn_in"})
        if needs_assignment and not assignment_item:
            if action in {"do_assignment", "turn_in"} and not effective_assignment_query and not latest:
                return self._failure("Tell me the assignment name, or say latest assignment, before I begin.")
            if assignment_candidates:
                names = ", ".join(str(item.get("name", "")) for item in assignment_candidates[:6])
                label = "latest assignment" if latest else (effective_assignment_query or "that assignment")
                return self._failure(f"I could not match {label}. I found these assignments: {names}.")
            return self._unindexed_classroom_confirmation(task, action, effective_class_query, effective_assignment_query, latest)
        if not class_item and not assignment_item:
            return None

        matched_parts = []
        if class_item:
            matched_parts.append(f"class '{class_item.get('name', '')}'")
        if assignment_item:
            matched_parts.append(f"assignment '{assignment_item.get('name', '')}'")
        low_confidence = (
            (class_item and effective_class_query and float(selection.get("class_score", 0.0)) < 0.55)
            or (assignment_item and effective_assignment_query and float(selection.get("assignment_score", 0.0)) < 0.55)
        )
        confidence_note = " This is a low-confidence match, so only confirm if it is right." if low_confidence else ""
        verb = "open it"
        if action == "do_assignment":
            verb = "open it so we can work through it"
        elif action == "turn_in":
            verb = "turn it in"
        message = f"I matched {' and '.join(matched_parts)}. Say confirm to {verb}.{confidence_note}"
        return {
            "success": False,
            "requires_confirmation": True,
            "message": message,
            "data": {
                "task": task,
                "action": action,
                "matched_class": class_item,
                "matched_assignment": assignment_item,
                "class_score": selection.get("class_score", 0.0),
                "assignment_score": selection.get("assignment_score", 0.0),
            },
        }

    def _unindexed_classroom_confirmation(
        self,
        task: str,
        action: str,
        class_query: str,
        assignment_query: str,
        latest: bool,
    ) -> Dict[str, Any] | None:
        if not class_query and not assignment_query and not latest:
            return None
        parts = []
        if class_query:
            parts.append(f"class '{class_query}'")
        if latest:
            parts.append("the latest assignment")
        elif assignment_query:
            parts.append(f"assignment or task '{assignment_query}'")
        target = " and ".join(parts) if parts else "that Classroom item"
        action_text = "open Classroom and look for it"
        if action == "do_assignment":
            action_text = "open Classroom and find it so we can work through it"
        elif action == "turn_in":
            action_text = "open Classroom and find it before attempting turn-in"
        return {
            "success": False,
            "requires_confirmation": True,
            "message": (
                f"I do not have a Classroom index yet, but I heard {target}. "
                f"Say confirm to {action_text}."
            ),
            "data": {
                "task": task,
                "action": action,
                "heard_class": class_query,
                "heard_assignment": assignment_query,
                "latest": latest,
                "needs_classroom_scan": True,
            },
        }

    def _assignment_candidates(self, index: Dict[str, Any], class_item: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        if class_item:
            class_name = str(class_item.get("name") or "")
            assignments = class_item.get("assignments", [])
            if isinstance(assignments, list):
                for item in assignments:
                    if isinstance(item, dict) and item.get("name"):
                        candidates.append({**item, "class_name": str(item.get("class_name") or class_name)})
        else:
            for item in index.get("assignments", []):
                if isinstance(item, dict) and item.get("name"):
                    candidates.append(dict(item))
            for class_candidate in index.get("classes", []):
                if not isinstance(class_candidate, dict):
                    continue
                class_name = str(class_candidate.get("name") or "")
                assignments = class_candidate.get("assignments", [])
                if not isinstance(assignments, list):
                    continue
                for item in assignments:
                    if isinstance(item, dict) and item.get("name"):
                        candidates.append({**item, "class_name": str(item.get("class_name") or class_name)})
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            key = "|".join(
                [
                    self._normalize_match_text(str(item.get("class_name") or "")),
                    self._normalize_match_text(str(item.get("name") or "")),
                    str(item.get("url") or ""),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _best_named_match(self, query: str, candidates: List[Dict[str, Any]]) -> tuple[Dict[str, Any] | None, float]:
        clean_query = self._normalize_match_text(query)
        if not clean_query or not candidates:
            return None, 0.0
        best: Dict[str, Any] | None = None
        best_score = 0.0
        for item in candidates:
            score = self._match_score(clean_query, str(item.get("name") or ""))
            if score > best_score:
                best = item
                best_score = score
        if best is None or best_score < 0.25:
            return None, best_score
        return best, best_score

    def _match_score(self, normalized_query: str, candidate: str) -> float:
        normalized_candidate = self._normalize_match_text(candidate)
        if not normalized_query or not normalized_candidate:
            return 0.0
        if normalized_query == normalized_candidate:
            return 1.0
        score = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
        query_tokens = set(normalized_query.split())
        candidate_tokens = set(normalized_candidate.split())
        if query_tokens and query_tokens.issubset(candidate_tokens):
            score = max(score, 0.9)
        elif query_tokens and candidate_tokens:
            overlap = len(query_tokens & candidate_tokens) / len(query_tokens | candidate_tokens)
            score = max(score, overlap * 0.95)
        if normalized_query in normalized_candidate:
            score = max(score, 0.82)
        if normalized_candidate in normalized_query:
            score = max(score, 0.72)
        return score

    def _normalize_match_text(self, text: str) -> str:
        clean = text.lower().replace("&", " and ")
        clean = re.sub(r"[^a-z0-9]+", " ", clean)
        clean = re.sub(r"\b(?:the|my|class|assignment|period|hour)\b", " ", clean)
        return " ".join(clean.split())

    def _open_indexed_item(self, page: Any, item: Dict[str, Any] | None, fallback_text: str) -> bool:
        url = str(item.get("url") or "") if isinstance(item, dict) else ""
        if url:
            if url.startswith("/"):
                url = "https://classroom.google.com" + url
            try:
                self._goto(page, url)
                return True
            except BaseException:
                pass
        return self._click_best_text(page, fallback_text)

    def _click_turn_in_controls(self, page: Any, performed: List[str]) -> bool:
        clicked_any = False
        for _ in range(2):
            clicked_this_round = False
            for label in ("Turn in", "Submit", "Hand in", "Mark as done"):
                if self._click_best_text(page, label):
                    performed.append(f"Clicked {label}")
                    page.wait_for_timeout(900)
                    clicked_any = True
                    clicked_this_round = True
                    break
            if not clicked_this_round:
                break
        return clicked_any

    def _remember_classroom_selection(self, index: Dict[str, Any], class_name: str, assignment_name: str) -> None:
        if not class_name and not assignment_name:
            return
        index["last_selection"] = {
            "class_name": class_name,
            "assignment_name": assignment_name,
        }

    def _signin_handoff_if_needed(self, url: str, task: str, reason: str, page: Any | None = None) -> Dict[str, Any] | None:
        if page is not None and not self._page_needs_signin(page) and "accounts.google.com" not in url.lower():
            return None
        if not self._looks_like_signin_url(url) and not self._looks_like_login_task(task):
            return None
        if not self._looks_like_signin_url(url) and "classroom.google.com" not in url and "google classroom" not in task.lower():
            return None
        account = self.classroom_account if ("classroom.google.com" in url.lower() or "google classroom" in task.lower()) else ""
        opened_url = preferred_google_url(url, account=account) if account else preferred_google_url(url)
        opened = self._open_real_chrome(opened_url)
        if not opened:
            return None
        return {
            "success": True,
            "requires_confirmation": False,
            "message": (
                "I opened this in your real Chrome session so Chrome/macOS can use your saved sign-in. "
                "Finish signing in there, then give me the next browser or screen command. "
                "I do not read, store, or type your password."
            ),
            "data": {"url": opened_url, "task": task, "signin_handoff": True, "reason": reason, "browser": "Google Chrome"},
        }

    def _looks_like_signin_url(self, url: str) -> bool:
        lowered = url.lower()
        login_hosts = [
            "accounts.google.com",
            "signin",
            "login",
            "auth",
            "classroom.google.com",
            "myap.collegeboard.org",
        ]
        return any(item in lowered for item in login_hosts)

    def _looks_like_login_task(self, task: str) -> bool:
        return bool(re.search(r"\b(sign\s*in|log\s*in|login|classroom|gmail|google drive|google docs|ap classroom)\b", task, re.I))

    def _open_real_chrome(self, url: str) -> bool:
        normalized = self._normalize_url(url)
        commands = []
        if self._opener:
            commands.append([self._opener, "-a", "Google Chrome", normalized])
            commands.append([self._opener, normalized])
        for command in commands:
            try:
                subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
        return False

    def _page_needs_signin(self, page: Any) -> bool:
        try:
            text = page.locator("body").inner_text(timeout=3000).lower()
        except BaseException:
            text = ""
        url = page.url.lower()
        return (
            "accounts.google.com" in url
            or "signin" in url
            or "sign in" in text
            or "use your google account" in text
            or "choose an account" in text
            or "email or phone" in text
        )

    def _click_text_or_vision(self, page: Any, text: str) -> None:
        attempts = [
            lambda: page.get_by_role("button", name=re.compile(re.escape(text), re.I)).first.click(timeout=3500),
            lambda: page.get_by_role("link", name=re.compile(re.escape(text), re.I)).first.click(timeout=3500),
            lambda: page.get_by_text(text, exact=False).first.click(timeout=3500),
            lambda: page.locator(f"[aria-label*={json.dumps(text)}]").first.click(timeout=3500),
        ]
        for attempt in attempts:
            try:
                attempt()
                return
            except BaseException:
                continue
        point = self._locate_on_page_with_vision(page, text)
        if not point.get("found") or float(point.get("confidence", 0.0)) < 0.45:
            raise RuntimeError(f"Could not locate '{text}' with Playwright or vision.")
        page.mouse.click(float(point["x"]), float(point["y"]))

    def _click_best_text(self, page: Any, text: str) -> bool:
        if not text:
            return False
        attempts = [
            lambda: page.get_by_text(text, exact=False).first.click(timeout=4000),
            lambda: page.get_by_role("link", name=re.compile(re.escape(text), re.I)).first.click(timeout=4000),
            lambda: page.get_by_role("button", name=re.compile(re.escape(text), re.I)).first.click(timeout=4000),
        ]
        for attempt in attempts:
            try:
                attempt()
                return True
            except BaseException:
                continue
        return False

    def _open_classwork_tab(self, page: Any, performed: List[str]) -> None:
        for label in ("Classwork", "Assignments", "To-do", "To do"):
            if self._click_best_text(page, label):
                performed.append(f"Opened {label}")
                return

    def _open_to_do_if_available(self, page: Any, performed: List[str]) -> None:
        for label in ("To-do", "To do", "Missing", "Assigned"):
            if self._click_best_text(page, label):
                performed.append(f"Opened {label}")
                return

    def _extract_classroom_index(self, page: Any, account: str) -> Dict[str, Any]:
        classes = self._extract_classes_from_page(page)
        existing = self._load_classroom_index()
        existing.update({"account": account, "last_url": page.url})
        if classes:
            known = {item.get("name", "").lower(): item for item in existing.get("classes", []) if isinstance(item, dict)}
            for item in classes:
                known[item["name"].lower()] = {**known.get(item["name"].lower(), {}), **item}
            existing["classes"] = sorted(known.values(), key=lambda item: item.get("name", "").lower())
        return existing

    def _extract_classes_from_page(self, page: Any) -> List[Dict[str, str]]:
        script = """
        () => Array.from(document.querySelectorAll('a[href*="/c/"], div[role="listitem"], div[class]'))
          .map((el) => {
            const text = (el.innerText || el.textContent || '').trim();
            const link = el.closest('a') || el.querySelector('a[href*="/c/"]') || (el.matches('a') ? el : null);
            return {text, url: link ? link.href : ''};
          })
          .filter((item) => item.text && item.text.length > 2)
          .slice(0, 80)
        """
        try:
            raw_items = page.evaluate(script)
        except BaseException:
            raw_items = []
        classes: List[Dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get("text", "")).split())
            name = text.split("\n", 1)[0].strip()
            if not name or len(name) > 120:
                continue
            lowered = name.lower()
            if lowered in seen or lowered in {"stream", "classwork", "people", "grades", "to-do", "calendar"}:
                continue
            seen.add(lowered)
            classes.append({"name": name, "url": str(item.get("url", ""))})
        return classes[:30]

    def _extract_assignments_from_page(self, page: Any) -> List[Dict[str, str]]:
        script = """
        () => Array.from(document.querySelectorAll('a[href*="/a/"], div[role="listitem"], div[role="button"], li'))
          .map((el) => {
            const text = (el.innerText || el.textContent || '').trim();
            const link = el.closest('a') || el.querySelector('a[href*="/a/"]') || (el.matches('a') ? el : null);
            return {text, url: link ? link.href : ''};
          })
          .filter((item) => item.text && item.text.length > 2)
          .slice(0, 100)
        """
        try:
            raw_items = page.evaluate(script)
        except BaseException:
            raw_items = []
        assignments: List[Dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get("text", "")).split())
            name = text.split("\n", 1)[0].strip()
            if not name or len(name) > 160:
                continue
            lowered = name.lower()
            ignored = {"stream", "classwork", "people", "grades", "view assignment", "mark as done"}
            if lowered in seen or lowered in ignored:
                continue
            if not re.search(r"\b(assignment|quiz|question|material|due|posted|missing|turned in|assigned|points?)\b", text, re.I) and not item.get("url"):
                continue
            seen.add(lowered)
            assignments.append({"name": name, "url": str(item.get("url", "")), "summary": text[:500]})
        return assignments[:50]

    def _merge_class_assignments(self, index: Dict[str, Any], class_name: str, assignments: List[Dict[str, str]]) -> Dict[str, Any]:
        classes = index.setdefault("classes", [])
        if not isinstance(classes, list):
            classes = []
            index["classes"] = classes
        target = None
        for item in classes:
            if isinstance(item, dict) and item.get("name", "").lower() == class_name.lower():
                target = item
                break
        if target is None:
            target = {"name": class_name, "url": "", "assignments": []}
            classes.append(target)
        target["assignments"] = assignments
        return index

    def _latest_assignment_name(self, index: Dict[str, Any], class_name: str) -> str:
        for item in index.get("classes", []):
            if not isinstance(item, dict):
                continue
            if item.get("name", "").lower() != class_name.lower():
                continue
            assignments = item.get("assignments", [])
            if isinstance(assignments, list) and assignments:
                first = assignments[0]
                if isinstance(first, dict):
                    return str(first.get("name", ""))
        return ""

    def _load_classroom_index(self) -> Dict[str, Any]:
        if not self.classroom_index_path.exists():
            return {"account": self.classroom_account, "classes": [], "assignments": []}
        try:
            parsed = json.loads(self.classroom_index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"account": self.classroom_account, "classes": [], "assignments": []}
        return parsed if isinstance(parsed, dict) else {"account": self.classroom_account, "classes": [], "assignments": []}

    def _save_classroom_index(self, index: Dict[str, Any]) -> None:
        self.classroom_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.classroom_index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")

    def _classroom_summary(self, index: Dict[str, Any]) -> Dict[str, Any]:
        classes = [item for item in index.get("classes", []) if isinstance(item, dict)]
        assignments = [item for item in index.get("assignments", []) if isinstance(item, dict)]
        return {
            "account": index.get("account", self.classroom_account),
            "class_count": len(classes),
            "classes": [item.get("name", "") for item in classes[:20]],
            "assignment_count": sum(len(item.get("assignments", [])) for item in classes if isinstance(item.get("assignments", []), list)) + len(assignments),
            "assignments": [item.get("name", "") for item in assignments[:20]],
        }

    def _plan_actions(self, page: Any, task: str, confirmed: bool) -> List[Dict[str, Any]]:
        if not self._needs_agent_plan(task):
            return []
        heuristic_actions = self._heuristic_actions_from_task(task)
        if heuristic_actions:
            return heuristic_actions
        snapshot = self._interactive_snapshot(page)
        prompt = (
            "You are FRIDAY's browser automation planner. Return strict JSON only.\n"
            "Create a short action plan for the current web page. Use only these actions:\n"
            '{"action":"click","text":"visible button/link text"}, '
            '{"action":"fill","label":"field label or placeholder","value":"text"}, '
            '{"action":"type","text":"text"}, {"action":"press","key":"Enter"}, '
            '{"action":"wait","ms":1000}, {"action":"extract"}.\n'
            "Do not invent private credentials. If the task requires login, payment, purchase, deletion, sending, posting, or graded schoolwork, only navigate/read/wait unless confirmed is true.\n"
            "Prefer clicking/filling visible elements from the snapshot. If no useful action is possible, return {\"actions\":[{\"action\":\"extract\"}]}.\n\n"
            f"Confirmed: {confirmed}\n"
            f"Task: {task}\n"
            f"Current URL: {page.url}\n"
            f"Visible interactive elements:\n{json.dumps(snapshot[:80], ensure_ascii=True)}\n"
            'Return: {"actions":[...]}\n'
        )
        try:
            raw = self._ollama_generate(self.reasoning_model, prompt)
            parsed = self._parse_json_object(raw)
            actions = parsed.get("actions", [])
            return [item for item in actions if isinstance(item, dict) and self._valid_planned_action(item)]
        except BaseException:
            return []

    def _needs_agent_plan(self, task: str) -> bool:
        return bool(re.search(r"\b(and|then|click|fill|type|press|choose|select|find|do|complete|answer|assignment|form|quiz|login|log in)\b", task, re.I))

    def _heuristic_actions_from_task(self, task: str) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        for part in re.split(r"\s+(?:and then|then|and)\s+", task.strip()):
            lowered = part.lower().strip()
            if not lowered:
                continue
            click_match = re.search(r"\b(?:click|choose|select)\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\s+button|\s+link|\s+tab)?$", part, re.I)
            if click_match:
                target = click_match.group(1).strip(" '\"")
                if target and target.lower() not in {"page", "site", "website"}:
                    actions.append({"action": "click", "text": target})
                    continue
            fill_match = re.search(r"\bfill\s+(?:the\s+)?(.+?)\s+(?:with|as)\s+(.+)$", part, re.I)
            if fill_match:
                actions.append({"action": "fill", "label": fill_match.group(1).strip(), "value": fill_match.group(2).strip(" '\"")})
                continue
            type_match = re.search(r"\btype\s+(.+)$", part, re.I)
            if type_match:
                actions.append({"action": "type", "text": type_match.group(1).strip(" '\"")})
                continue
            press_match = re.search(r"\b(?:press|hit)\s+(.+)$", part, re.I)
            if press_match:
                actions.append({"action": "press", "key": press_match.group(1).strip()})
                continue
        return actions

    def _valid_planned_action(self, action: Dict[str, Any]) -> bool:
        placeholder_values = {
            "visible button/link text",
            "field label or placeholder",
            "text",
            "optional",
            "",
        }
        for key in ("text", "target", "label", "placeholder", "value"):
            value = str(action.get(key, "")).strip().lower()
            if value in placeholder_values:
                return False
        return True

    def _interactive_snapshot(self, page: Any) -> List[Dict[str, str]]:
        script = """
        els => els.slice(0, 120).map((el) => {
          const label = el.labels && el.labels[0] ? el.labels[0].innerText : "";
          return {
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.textContent || "").trim().slice(0, 120),
            aria: (el.getAttribute("aria-label") || "").trim(),
            role: (el.getAttribute("role") || "").trim(),
            placeholder: (el.getAttribute("placeholder") || "").trim(),
            name: (el.getAttribute("name") || "").trim(),
            id: (el.id || "").trim(),
            type: (el.getAttribute("type") || "").trim(),
            label: label.trim().slice(0, 120)
          };
        })
        """
        try:
            return page.locator("a,button,input,textarea,select,[role=button],[role=link],[contenteditable=true]").evaluate_all(script)
        except BaseException:
            return []

    def _locate_on_page_with_vision(self, page: Any, target: str) -> Dict[str, Any]:
        path = self.screenshot_dir / "browser-vision-target.png"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=False)
        width, height = self._image_size(path)
        prompt = (
            "You are FRIDAY's browser vision fallback. Locate the requested clickable UI target in this browser screenshot.\n"
            "Return strict JSON only with this shape: "
            '{"found":true,"x":0,"y":0,"confidence":0.0,"description":""}\n'
            "Coordinates must be screenshot pixel coordinates from the top-left, at the center of the target. "
            "If not visible, return found false.\n"
            f"Target: {target}\nScreenshot size: {width}x{height}\n"
        )
        raw = self._vision_generate(path, prompt)
        parsed = self._parse_json_object(raw)
        try:
            x = float(parsed.get("x", 0.0))
            y = float(parsed.get("y", 0.0))
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            x, y, confidence = 0.0, 0.0, 0.0
        return {
            "found": bool(parsed.get("found", False)),
            "x": x,
            "y": y,
            "confidence": confidence,
            "description": str(parsed.get("description") or raw).strip()[:500],
        }

    def _ollama_generate(self, model: str, prompt: str) -> str:
        body = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
        request = urllib.request.Request(
            self.ollama_host + "/api/generate",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload.get("response", "")).strip()

    def _vision_generate(self, image_path: Path, prompt: str) -> str:
        body = {
            "model": self.vision_model,
            "prompt": prompt,
            "images": [base64.b64encode(image_path.read_bytes()).decode("ascii")],
            "stream": False,
        }
        request = urllib.request.Request(
            self.ollama_host + "/api/generate",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload.get("response", "")).strip()

    def _parse_json_object(self, raw: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return {}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return parsed if isinstance(parsed, dict) else {}

    def _image_size(self, path: Path) -> tuple[int, int]:
        try:
            from PIL import Image

            with Image.open(path) as image:
                return int(image.width), int(image.height)
        except BaseException:
            return 1, 1

    def _screen_fallback(self, task: str, confirmed: bool, reason: str) -> Dict[str, Any] | None:
        try:
            from friday.tools.screen_control import ScreenControlTool

            result = ScreenControlTool(self.root_dir).run({"task": task, "raw_input": task, "confirmed": confirmed})
        except BaseException:
            return None
        if not result.get("success") and not result.get("requires_confirmation"):
            return None
        result["message"] = f"{reason} I used the screen-control fallback. {result.get('message', '')}"
        return result

    def _run_simple_prompt_action(self, page: Any, task: str) -> str:
        click_match = re.search(r"\bclick\s+(?:on\s+)?['\"]?([^'\"]{2,80})['\"]?$", task, re.I)
        if click_match:
            target = click_match.group(1).strip()
            page.get_by_text(target, exact=False).first.click(timeout=8000)
            return f"Clicked {target}"
        return ""

    def _infer_start_url(self, task: str) -> str:
        lowered = task.lower()
        url_match = re.search(r"https?://[^\s]+|(?:www\.)?[a-z0-9-]+\.[a-z]{2,}(?:/[^\s]*)?", lowered)
        if url_match:
            return self._normalize_url(url_match.group(0))
        for alias in sorted(BROWSER_WEBSITE_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return BROWSER_WEBSITE_ALIASES[alias]
        if "google" in lowered:
            return "https://www.google.com/"
        return ""

    def _infer_search(self, task: str) -> Tuple[str, str]:
        lowered = task.lower()
        engine = "google"
        if "youtube" in lowered:
            engine = "youtube"
        elif "reddit" in lowered:
            engine = "reddit"
        patterns = [
            r"\bsearch\s+(?:google|youtube|reddit)?\s*(?:for\s+)?(.+)$",
            r"\blook up\s+(.+)$",
            r"\bgoogle\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, task, re.I)
            if match:
                query = re.sub(r"\s+(?:and\s+)?(?:click|open)\s+.*$", "", match.group(1).strip(), flags=re.I).strip()
                if query:
                    return query, engine
        return "", engine

    def _perform_search(self, page: Any, query: str, engine: str) -> None:
        if engine == "youtube":
            locator = page.locator("input[name='search_query']").first
        else:
            locator = page.locator("textarea[name='q'], input[name='q']").first
        locator.fill(query, timeout=10000)
        locator.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=30000)

    def _search_home(self, engine: str) -> str:
        if engine == "youtube":
            return "https://www.youtube.com/"
        if engine == "reddit":
            return "https://www.reddit.com/"
        return "https://www.google.com/"

    def _requires_confirmation(self, task: str, parameters: Dict[str, Any]) -> bool:
        text = f"{task} {parameters}".lower()
        risky_patterns = [
            r"\bsubmit\b",
            r"\bturn\s+in\b",
            r"\bfinalize\b",
            r"\bpurchase\b",
            r"\bbuy\b",
            r"\bcheckout\b",
            r"\bpay\b",
            r"\bsend\b",
            r"\bpost\b",
            r"\bpublish\b",
            r"\bdelete\b",
            r"\bremove\b",
            r"\blog\s*in\b",
            r"\bpassword\b",
            r"\bassignment\b.*\b(do|complete|answer|submit|turn\s+in)\b",
            r"\b(do|complete|answer|submit|turn\s+in)\b.*\bassignment\b",
        ]
        return any(re.search(pattern, text) for pattern in risky_patterns)

    def _page_text(self, page: Any) -> str:
        try:
            return page.locator("body").inner_text(timeout=4000)[:6000]
        except BaseException:
            return ""

    def _summarize_page_text(self, text: str) -> str:
        clean = " ".join(text.split())
        return clean[:1200]

    def _normalize_url(self, url: str) -> str:
        clean = url.strip()
        if clean.startswith(("http://", "https://")):
            return clean
        if clean.startswith("www.") or "." in clean:
            return "https://" + clean
        return "https://" + clean + ".com"

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": {}}
