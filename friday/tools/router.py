from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from friday.brain.action_planner import plan_screen_actions
from friday.control.controller_router import ControllerRouter
from friday.control.emergency_stop import EmergencyStopController
from friday.memory import ActionLogger
from friday.ollama_engine import OllamaClient
from friday.tools.app_control import AppControlTool
from friday.tools.browser import BrowserTool
from friday.tools.browser_control import BrowserControlTool
from friday.phone.manager import PhoneCallManager
from friday.tools.code_gen import CodeGeneratorTool
from friday.tools.command import RunCommandTool
from friday.tools.email import ResendEmailTool
from friday.tools.filesystem import FileSystemTool
from friday.tools.maps import AppleMapsTool
from friday.tools.music import SpotifyMusicTool
from friday.tools.phone import PhoneTool
from friday.tools.productivity import ProductivityDraftTool
from friday.tools.screen_control import ScreenControlTool
from friday.tools.system import SystemInfoTool
from friday.tools.todo import TodoListTool


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    success: bool
    requires_confirmation: bool
    message: str
    data: Dict[str, Any]


class ToolRouter:
    TOOL_COMMANDS = {
        "run_command",
        "open_app",
        "close_app",
        "get_time",
        "list_files",
        "read_project_structure",
        "read_file",
        "create_file",
        "write_file",
        "append_file",
        "move_file",
        "rename_file",
        "browser_open",
        "browser_close_tab",
        "browser_switch_tab",
        "open_website",
        "browser_search",
        "maps_directions",
        "music_play",
        "draft_document",
        "draft_slides",
        "generate_code",
        "place_call",
        "cancel_call",
        "list_calls",
        "summarize_last_call",
        "screen_control_plan",
        "browser_task",
        "screen_control",
        "browser_extract",
        "extract_webpage_text",
        "send_email",
        "resend_send_email",
        "task_history_summary",
        "todo_add",
        "todo_complete",
        "todo_clear",
        "todo_list",
    }

    def __init__(
        self,
        root_dir: Path,
        resend_api_key: str,
        default_model: str = "",
        vision_model: str = "",
        code_model: str = "",
        ollama_host: str = "",
        ollama: OllamaClient | None = None,
        phone_manager: PhoneCallManager | None = None,
    ) -> None:
        self.apps = AppControlTool()
        self.command = RunCommandTool(root_dir)
        self.files = FileSystemTool(root_dir)
        self.emergency_stop = EmergencyStopController()
        self.controller_router = ControllerRouter(root_dir=root_dir, emergency_stop=self.emergency_stop)
        self.browser = BrowserTool(root_dir)
        self.maps = AppleMapsTool(root_dir)
        self.browser_control = BrowserControlTool(root_dir, reasoning_model=default_model, vision_model=vision_model, ollama_host=ollama_host)
        self.screen = ScreenControlTool(root_dir, vision_model=vision_model, ollama_host=ollama_host)
        self.music = SpotifyMusicTool()
        self.productivity = ProductivityDraftTool(root_dir, model=default_model, ollama_host=ollama_host)
        # code_gen needs a real OllamaClient — share the one server.py already built when possible
        # to keep status caching warm and avoid duplicate /api/tags requests.
        code_ollama = ollama or OllamaClient(
            ollama_host or "http://127.0.0.1:11434",
            default_model or "qwen3:4b",
        )
        self.code_gen = CodeGeneratorTool(
            root_dir=root_dir,
            ollama=code_ollama,
            code_model=code_model,
            default_model=default_model,
        )
        self.action_logger = ActionLogger(Path(root_dir) / "logs" / "screen-actions.jsonl")
        self.email = ResendEmailTool(resend_api_key)
        self.system = SystemInfoTool()
        self.phone = PhoneTool(manager=phone_manager)
        self.todos = TodoListTool(root_dir)

    def control_status(self) -> Dict[str, Any]:
        return self.emergency_stop.snapshot().to_dict()

    def execute(self, intent: Dict[str, Any]) -> List[ToolResult]:
        command = str(intent.get("command", "none")).strip()
        parameters = intent.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        if command in {"", "none", "ask_follow_up", "report_status", "set_tone"}:
            return []
        if command not in self.TOOL_COMMANDS:
            return []
        raw_result = self._execute_one(command, parameters)
        return [
            ToolResult(
                tool_name=command,
                success=bool(raw_result.get("success", False)),
                requires_confirmation=bool(raw_result.get("requires_confirmation", False)),
                message=str(raw_result.get("message", "")),
                data=raw_result.get("data", {}) if isinstance(raw_result.get("data", {}), dict) else {},
            )
        ]

    def _execute_one(self, command: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if command == "run_command":
            return self.command.run(parameters)
        if command == "open_app":
            return self.apps.open_app(parameters)
        if command == "close_app":
            return self.apps.close_app(parameters)
        if command == "get_time":
            return self.system.get_time(parameters)
        if command in {"list_files", "read_project_structure"}:
            return self.files.list_files(parameters)
        if command == "read_file":
            return self.files.read_file(parameters)
        if command in {"create_file", "write_file"}:
            return self.files.create_file(parameters)
        if command == "append_file":
            return self.files.append_file(parameters)
        if command in {"move_file", "rename_file"}:
            return self.files.move_file(parameters)
        if command in {"browser_open", "open_website"}:
            return self._execute_browser_open(parameters)
        if command == "browser_close_tab":
            return self.browser.close_tab(parameters)
        if command == "browser_switch_tab":
            return self.browser.switch_tab(parameters)
        if command == "browser_search":
            return self._execute_browser_search(parameters)
        if command == "maps_directions":
            return self.maps.directions(parameters)
        if command == "music_play":
            return self.music.play(parameters)
        if command == "draft_document":
            try:
                return self.productivity.write_report(parameters)
            except Exception as exc:
                return {
                    "success": False,
                    "requires_confirmation": False,
                    "message": f"I couldn't finish that Google Docs draft cleanly, sir: {exc}",
                    "data": {"error": str(exc)},
                }
        if command == "draft_slides":
            try:
                return self.productivity.make_slides(parameters)
            except Exception as exc:
                return {
                    "success": False,
                    "requires_confirmation": False,
                    "message": f"I couldn't finish that slide draft cleanly, sir: {exc}",
                    "data": {"error": str(exc)},
                }
        if command == "generate_code":
            try:
                return self.code_gen.generate(parameters)
            except Exception as exc:
                return {
                    "success": False,
                    "requires_confirmation": False,
                    "message": f"I couldn't generate that code cleanly, boss: {exc}",
                    "data": {"error": str(exc)},
                }
        if command == "place_call":
            return self.phone.place_call(parameters)
        if command == "cancel_call":
            return self.phone.cancel_call(parameters)
        if command == "list_calls":
            return self.phone.list_calls(parameters)
        if command == "summarize_last_call":
            return self.phone.summarize_last_call(parameters)
        if command == "screen_control_plan":
            return self._execute_screen_control_plan(parameters)
        if command == "browser_task":
            return self.browser_control.run_task(parameters)
        if command == "screen_control":
            return self.screen.run(parameters)
        if command in {"browser_extract", "extract_webpage_text"}:
            return self.browser.extract_text(parameters)
        if command in {"send_email", "resend_send_email"}:
            return self.email.send_email(parameters)
        if command == "task_history_summary":
            return self._execute_task_history_summary()
        if command == "todo_add":
            return self.todos.add_task(parameters)
        if command == "todo_complete":
            return self.todos.complete_task(parameters)
        if command == "todo_clear":
            return self.todos.clear_tasks(parameters)
        if command == "todo_list":
            return self.todos.list_tasks(parameters)
        return {
            "success": False,
            "requires_confirmation": False,
            "message": f"Unknown tool command: {command}",
            "data": {"command": command},
        }

    def _execute_screen_control_plan(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        user_command = str(
            parameters.get("user_command")
            or parameters.get("raw_input")
            or parameters.get("task")
            or parameters.get("command")
            or ""
        ).strip()
        if not user_command:
            return {
                "success": False,
                "requires_confirmation": False,
                "message": "I need a browser command before I can control the page, sir.",
                "data": {},
            }
        actions = plan_screen_actions(user_command)
        if not actions:
            return {
                "success": False,
                "requires_confirmation": False,
                "message": "I couldn't turn that into a safe browser action, sir.",
                "data": {"user_command": user_command},
            }
        confirmed = bool(parameters.get("confirmed", False))
        previous_confirmed = set(self.controller_router.confirmed_action_ids)
        if confirmed:
            self.controller_router.confirmed_action_ids.update(action.action_id for action in actions)
        try:
            results = self.controller_router.execute_plan(actions)
        finally:
            if confirmed:
                self.controller_router.confirmed_action_ids = previous_confirmed
        self.action_logger.log_task(user_command, actions, results)

        requires_confirmation = (not confirmed) and any(
            action.risk_level.value == "high" and not result.success
            for action, result in zip(actions, results)
        )
        blocked = any(action.risk_level.value == "blocked" for action in actions)
        success = bool(results) and all(result.success for result in results) and not blocked and not requires_confirmation
        return {
            "success": success,
            "requires_confirmation": requires_confirmation,
            "message": self._screen_plan_message(user_command, actions, results, requires_confirmation, blocked),
            "data": {
                "user_command": user_command,
                "actions": [action.to_dict() for action in actions],
                "results": [result.to_dict() for result in results],
            },
        }

    def _execute_browser_open(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        url = str(parameters.get("url") or "").strip()
        if not url:
            return {
                "success": False,
                "requires_confirmation": False,
                "message": "I need a URL before I can open that page, sir.",
                "data": {},
            }
        return self.browser.open_page(parameters)

    def _execute_browser_search(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        query = str(parameters.get("query") or "").strip()
        query = re.sub(r"^for\s+", "", query, flags=re.I).strip()
        engine = str(parameters.get("engine") or "google").strip().lower()
        if not query:
            return {
                "success": False,
                "requires_confirmation": False,
                "message": "Search query cannot be empty.",
                "data": {},
            }
        browser_parameters: Dict[str, Any] = {"engine": engine, "query": query}
        if str(parameters.get("browser") or "").strip():
            browser_parameters["browser"] = parameters.get("browser")
        return self.browser.search(browser_parameters)

    def _screen_plan_message(self, user_command: str, actions: List[Any], results: List[Any], requires_confirmation: bool, blocked: bool) -> str:
        if any(getattr(result, "controller_used", "") == "emergency-stop" for result in results):
            return "Stopped, sir."
        if blocked:
            return "I can't do that because it involves a blocked action, boss."
        if requires_confirmation:
            return self._confirmation_message(user_command)
        if results and any(not result.success for result in results):
            return "I couldn't complete that browser action, sir."
        if not actions:
            return "I couldn't find a browser action for that, sir."
        search_action = next((action for action in actions if action.action_type.value == "browser.search"), None)
        open_action = next((action for action in actions if action.action_type.value == "browser.open_url"), None)
        click_action = next((action for action in actions if action.action_type.value == "browser.click"), None)
        if search_action:
            site = self._display_target(search_action.target.replace(" search", "") or (open_action.target if open_action else "the web"))
            query = self._display_search_query(user_command, search_action.value)
            return f"Searching {site} for {query}, sir."
        if open_action and click_action:
            return f"Clicking {click_action.target} on {self._display_target(open_action.target)}, sir."
        if open_action:
            return f"Opening {self._display_target(open_action.target)}, sir."
        first = actions[0]
        action_type = first.action_type.value
        if action_type == "browser.type":
            return "Typing that text, sir."
        if action_type == "browser.click":
            return f"Clicking {first.target}, sir."
        if action_type == "browser.navigate":
            value = first.value.strip().lower()
            if value == "back":
                return "Going back, sir."
            if value == "new_tab":
                return "Opening a new tab, sir."
            if value == "close_tab":
                return "Closing the current tab, sir."
        return "Handled, sir."

    def _confirmation_message(self, user_command: str) -> str:
        text = user_command.lower()
        if any(word in text for word in ("email", "send", "message", "text", "dm")):
            return "I need confirmation before sending that, sir."
        if any(word in text for word in ("submit", "turn in", "hand in", "form", "application")):
            return "I need confirmation before submitting that, sir."
        if any(word in text for word in ("buy", "purchase", "pay", "checkout")):
            return "I need confirmation before making that purchase, sir."
        return "I need confirmation before doing that, sir."

    def _display_target(self, target: str) -> str:
        clean = " ".join(target.strip().split())
        if not clean:
            return "that page"
        special = {
            "chatgpt": "ChatGPT",
            "chat gpt": "ChatGPT",
            "youtube": "YouTube",
            "google docs": "Google Docs",
            "spotify": "Spotify",
        }
        return special.get(clean.lower(), clean.title())

    def _display_search_query(self, user_command: str, fallback: str) -> str:
        match = re.search(r"\b(?:search|find|look\s+up|play)\s+(.+)$", user_command, flags=re.I)
        if " for " in user_command.lower():
            match = re.search(r"\bfor\s+(.+)$", user_command, flags=re.I)
        if match:
            query = match.group(1).strip(" .")
            query = re.sub(r"\s+(?:for\s+me|please)$", "", query, flags=re.I).strip()
            if query:
                return query
        return fallback.strip() or "that"

    def _target_from_url(self, url: str) -> str:
        lowered = url.lower()
        if "youtube.com" in lowered:
            return "youtube"
        if "chatgpt.com" in lowered:
            return "chatgpt"
        if "docs.google.com" in lowered:
            return "google docs"
        if "open.spotify.com" in lowered or "spotify.com" in lowered:
            return "spotify"
        match = re.search(r"https?://(?:www\.)?([^/.]+)", lowered)
        return match.group(1) if match else url

    def _execute_task_history_summary(self) -> Dict[str, Any]:
        summary = self.action_logger.summarize_last_task()
        return {
            "success": True,
            "requires_confirmation": False,
            "message": summary,
            "data": {"recent_actions": self.action_logger.get_recent_actions(limit=3)},
        }
