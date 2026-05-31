from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


class ScreenControlTool:
    def __init__(self, root_dir: Path, vision_model: str = "", ollama_host: str = "") -> None:
        self.root_dir = root_dir
        self.screenshot_dir = root_dir / ".friday" / "screen-screenshots"
        self.vision_model = vision_model or os.environ.get("FRIDAY_VISION_MODEL", "llama3.2-vision:11b")
        self.ollama_host = ollama_host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    def run(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import pyautogui
        except ImportError as exc:
            return self._failure(f"PyAutoGUI is not installed in this environment: {exc}")

        task = str(parameters.get("raw_input") or parameters.get("task") or parameters.get("prompt") or "").strip()
        actions = parameters.get("actions")
        if not isinstance(actions, list) or not actions:
            action = str(parameters.get("action") or "").strip()
            actions = [{"action": action, **parameters}] if action else self._actions_from_task(task)
        elif task and not any(isinstance(item, dict) and item.get("action") == "open_app" for item in actions):
            derived_actions = self._actions_from_task(task)
            if derived_actions:
                actions = derived_actions
        if not actions:
            return self._failure("I need a clearer screen command, such as click the login button, type hello, press command l, scroll down, or describe my screen.")

        confirmed = bool(parameters.get("confirmed", False))
        if self._requires_confirmation(actions, task) and not confirmed:
            return {
                "success": False,
                "requires_confirmation": True,
                "message": "This screen action may submit, send, delete, pay, type sensitive text, or affect schoolwork. Say confirm before I continue.",
                "data": {"task": task, "actions": actions},
            }

        dry_run = bool(parameters.get("dry_run", False))
        pyautogui.PAUSE = 0.05
        pyautogui.FAILSAFE = True
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        performed: List[str] = []
        data: Dict[str, Any] = {"dry_run": dry_run, "vision_model": self.vision_model}
        try:
            for action in actions[:24]:
                if not isinstance(action, dict):
                    performed.append("Skipped invalid action")
                    continue
                performed.append(self._run_action(pyautogui, action, dry_run, data))
        except BaseException as exc:
            return self._failure(f"Screen control failed: {exc}")
        return self._success(f"Screen control completed: {'; '.join(performed[:6])}.", {**data, "performed": performed})

    def _run_action(self, pyautogui: Any, action: Dict[str, Any], dry_run: bool, data: Dict[str, Any]) -> str:
        kind = str(action.get("action") or action.get("type") or "").strip().lower().replace("-", "_")
        if kind in {"size", "screen_size"}:
            size = pyautogui.size()
            data["screen_size"] = {"width": int(size.width), "height": int(size.height)}
            return f"Read screen size {size.width}x{size.height}"
        if kind in {"position", "mouse_position"}:
            pos = pyautogui.position()
            data["mouse_position"] = {"x": int(pos.x), "y": int(pos.y)}
            return f"Read mouse position {pos.x},{pos.y}"
        if kind in {"screenshot", "capture"}:
            path = self._capture_screenshot(pyautogui, action)
            data["screenshot"] = str(path)
            return f"Saved screenshot {path}"
        if kind == "open_app":
            app_name = str(action.get("app_name") or action.get("app") or "").strip()
            if not app_name:
                return "Skipped open_app without an app name"
            if not dry_run:
                completed = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=10)
                if completed.returncode != 0:
                    raise RuntimeError(f"Could not open {app_name}: {completed.stderr.strip()}")
            return f"Opened {app_name}"
        if kind in {"analyze", "describe", "read_screen", "screen_summary"}:
            path = self._capture_screenshot(pyautogui, action)
            prompt = (
                "Describe the visible computer screen for an automation assistant. "
                "Mention app/window names if visible, important text, buttons, fields, and likely next actions. "
                "Be concise and practical."
            )
            description = self._ask_vision_text(path, prompt)
            data["screenshot"] = str(path)
            data["description"] = description
            return "Analyzed the screen"
        if kind in {"find", "locate"}:
            target = str(action.get("target") or action.get("text") or action.get("label") or "").strip()
            if dry_run:
                return f"Would locate {target}"
            located = self._locate_target(pyautogui, target)
            data.setdefault("located_targets", []).append(located)
            if not located.get("found"):
                return f"Could not confidently locate {target}"
            return f"Located {target} at {located['x']},{located['y']}"
        if kind == "move":
            target = str(action.get("target") or action.get("text") or action.get("label") or "").strip()
            if dry_run and target and (action.get("x") is None or action.get("y") is None):
                return f"Would move mouse to {target}"
            x, y = self._coords_for_action(pyautogui, action, data)
            duration = float(action.get("duration", 0.15) or 0.15)
            if not dry_run:
                pyautogui.moveTo(x, y, duration=duration)
            return f"Moved mouse to {x:g},{y:g}"
        if kind in {"click", "double_click", "right_click", "click_target"}:
            target = str(action.get("target") or action.get("text") or "").strip()
            if dry_run and target and (action.get("x") is None or action.get("y") is None):
                return f"Would click {target}"
            x, y = self._coords_for_action(pyautogui, action, data)
            clicks = int(action.get("clicks", 2 if kind == "double_click" else 1) or 1)
            button = str(action.get("button") or ("right" if kind == "right_click" else "left"))
            if not dry_run:
                pyautogui.click(x, y, clicks=clicks, button=button)
            return f"Clicked {target or 'mouse'}"
        if kind == "drag":
            start_x = action.get("start_x", action.get("x"))
            start_y = action.get("start_y", action.get("y"))
            end_x = action.get("end_x")
            end_y = action.get("end_y")
            if None in {start_x, start_y, end_x, end_y}:
                return "Skipped drag without complete coordinates"
            duration = float(action.get("duration", 0.3) or 0.3)
            if not dry_run:
                pyautogui.moveTo(float(start_x), float(start_y), duration=0.1)
                pyautogui.dragTo(float(end_x), float(end_y), duration=duration, button=str(action.get("button", "left")))
            return f"Dragged from {start_x},{start_y} to {end_x},{end_y}"
        if kind == "type":
            text = str(action.get("text") or action.get("value") or "")
            interval = float(action.get("interval", 0.01) or 0.01)
            if not dry_run:
                pyautogui.write(text, interval=interval)
            return "Typed text"
        if kind in {"paste_text", "paste"}:
            text = str(action.get("text") or action.get("value") or "")
            if not dry_run:
                self._paste_text(pyautogui, text)
            return "Pasted text"
        if kind == "press":
            key = self._normalize_key(str(action.get("key") or ""))
            if not key:
                return "Skipped press without key"
            if not dry_run:
                pyautogui.press(key)
            return f"Pressed {key}"
        if kind == "hotkey":
            keys = self._normalize_hotkeys(action.get("keys", []))
            if not keys:
                return "Skipped hotkey without keys"
            if not dry_run:
                pyautogui.hotkey(*keys)
            return f"Pressed hotkey {'+'.join(keys)}"
        if kind == "scroll":
            clicks = self._scroll_amount(action)
            if not dry_run:
                pyautogui.scroll(clicks)
            return f"Scrolled {'up' if clicks > 0 else 'down'}"
        if kind == "wait":
            seconds = float(action.get("seconds", 1.0) or 1.0)
            if not dry_run:
                time.sleep(min(seconds, 10.0))
            return f"Waited {seconds:g}s"
        return f"Skipped unknown action {kind or 'blank'}"

    def _coords_for_action(self, pyautogui: Any, action: Dict[str, Any], data: Dict[str, Any]) -> tuple[float, float]:
        x = action.get("x")
        y = action.get("y")
        if x is not None and y is not None:
            return float(x), float(y)
        target = str(action.get("target") or action.get("text") or action.get("label") or "").strip()
        if not target:
            pos = pyautogui.position()
            return float(pos.x), float(pos.y)
        located = self._locate_target(pyautogui, target)
        data.setdefault("located_targets", []).append(located)
        if not located.get("found") or float(located.get("confidence", 0.0)) < 0.45:
            raise RuntimeError(f"I could not confidently locate '{target}' on screen.")
        return float(located["x"]), float(located["y"])

    def _locate_target(self, pyautogui: Any, target: str) -> Dict[str, Any]:
        if not target:
            return {"found": False, "target": target, "reason": "No target text was provided."}
        screenshot = self._capture_screenshot(pyautogui, {"name": "vision-target.png"})
        image_width, image_height = self._image_size(screenshot)
        screen = pyautogui.size()
        prompt = (
            "You are FRIDAY's screen-control vision model. Locate the requested UI target in the screenshot.\n"
            "Return strict JSON only with this exact shape:\n"
            '{"found":true,"x":0,"y":0,"confidence":0.0,"description":""}\n'
            "Coordinates must be screenshot pixel coordinates measured from the top-left corner. "
            "Choose the center of the clickable target. If the target is not visible, return found false and confidence 0.\n"
            f"Target: {target}\n"
            f"Screenshot size: {image_width}x{image_height}. PyAutoGUI screen size: {screen.width}x{screen.height}.\n"
        )
        raw = self._ask_vision_text(screenshot, prompt)
        parsed = self._parse_json_object(raw)
        found = bool(parsed.get("found", False))
        try:
            confidence = float(parsed.get("confidence", 0.0))
            raw_x = float(parsed.get("x", 0.0))
            raw_y = float(parsed.get("y", 0.0))
        except (TypeError, ValueError):
            confidence, raw_x, raw_y = 0.0, 0.0, 0.0
        scaled_x = raw_x * (float(screen.width) / max(float(image_width), 1.0))
        scaled_y = raw_y * (float(screen.height) / max(float(image_height), 1.0))
        return {
            "found": found,
            "target": target,
            "x": round(scaled_x, 1),
            "y": round(scaled_y, 1),
            "raw_x": raw_x,
            "raw_y": raw_y,
            "confidence": confidence,
            "description": str(parsed.get("description") or raw).strip()[:600],
            "screenshot": str(screenshot),
        }

    def _capture_screenshot(self, pyautogui: Any, action: Dict[str, Any]) -> Path:
        name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(action.get("name") or "screen.png"))
        path = self.screenshot_dir / name
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                image = pyautogui.screenshot()
            image.save(path)
            self._validate_screenshot(path)
            return path
        except BaseException:
            pass
        try:
            completed = subprocess.run(["screencapture", "-x", str(path)], capture_output=True, text=True, timeout=8)
            if completed.returncode == 0:
                self._validate_screenshot(path)
                return path
        except BaseException:
            pass
        raise RuntimeError(
            "macOS blocked screen capture, so FRIDAY's vision fallback cannot see the screen yet. "
            "Enable Screen Recording for Codex, Terminal, Python, or your shell in System Settings > Privacy & Security > Screen Recording, then restart FRIDAY."
        )

    def _validate_screenshot(self, path: Path) -> None:
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError("Screenshot file was empty.")
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        return path

    def _ask_vision_text(self, image_path: Path, prompt: str) -> str:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        body = {
            "model": self.vision_model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.ollama_host + "/api/generate",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama vision model is not reachable at {self.ollama_host}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama vision model returned invalid JSON.") from exc
        text = str(payload.get("response", "")).strip()
        if not text:
            raise RuntimeError(f"Ollama vision model {self.vision_model} returned an empty response.")
        return text

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

    def _actions_from_task(self, task: str) -> List[Dict[str, Any]]:
        text = " ".join(task.strip().split())
        lowered = text.lower()
        if not lowered:
            return []
        if re.search(r"\b(describe|read|analyze|what'?s on|what is on|look at)\b.*\b(screen|display|window|page)\b", lowered) or lowered in {"describe screen", "read screen", "analyze screen"}:
            return [{"action": "analyze", "name": "vision-screen.png"}]
        if re.search(r"\b(screenshot|screen shot|capture screen)\b", lowered):
            return [{"action": "screenshot", "name": "friday-screen.png"}]
        if re.search(r"\b(position|where is the mouse|mouse position|cursor position)\b", lowered):
            return [{"action": "position"}]
        if re.search(r"\b(size|resolution|screen dimensions)\b", lowered):
            return [{"action": "size"}]
        if re.search(r"\b(select all)\b", lowered):
            return [{"action": "hotkey", "keys": ["command", "a"]}]
        if re.search(r"\b(copy)\b", lowered):
            return [{"action": "hotkey", "keys": ["command", "c"]}]
        if re.search(r"\b(paste)\b", lowered) and not re.search(r"\bpaste\s+['\"]?(.+)", lowered):
            return [{"action": "hotkey", "keys": ["command", "v"]}]
        if re.search(r"\b(new tab)\b", lowered):
            return [{"action": "hotkey", "keys": ["command", "t"]}]
        if re.search(r"\b(close tab)\b", lowered):
            return [{"action": "hotkey", "keys": ["command", "w"]}]

        actions: List[Dict[str, Any]] = []
        for part in re.split(r"\s+(?:and then|then|and)\s+", text):
            action = self._action_from_phrase(part.strip())
            if action:
                actions.append(action)
        return actions

    def _action_from_phrase(self, phrase: str) -> Dict[str, Any] | None:
        lowered = phrase.lower()
        coord = re.search(r"\b(?:at|to)?\s*(-?\d{1,5})\s*,\s*(-?\d{1,5})\b", lowered)
        x = int(coord.group(1)) if coord else None
        y = int(coord.group(2)) if coord else None
        if lowered.startswith(("double click", "double-click")):
            target = self._target_after(phrase, r"double[-\s]?click(?:\s+(?:on|the))?")
            return {"action": "double_click", **self._target_or_coords(target, x, y)}
        if lowered.startswith(("right click", "right-click")):
            target = self._target_after(phrase, r"right[-\s]?click(?:\s+(?:on|the))?")
            return {"action": "right_click", **self._target_or_coords(target, x, y)}
        if lowered.startswith("click") or lowered.startswith("tap"):
            target = self._target_after(phrase, r"(?:click|tap)(?:\s+(?:on|the))?")
            return {"action": "click", **self._target_or_coords(target, x, y)}
        if lowered.startswith("move"):
            target = self._target_after(phrase, r"move(?:\s+(?:mouse|cursor))?(?:\s+(?:to|over|on))?")
            return {"action": "move", **self._target_or_coords(target, x, y)}
        if lowered.startswith("type"):
            value = self._quoted_or_tail(phrase, "type")
            return {"action": "type", "text": value}
        if lowered.startswith("paste"):
            value = self._quoted_or_tail(phrase, "paste")
            return {"action": "paste_text", "text": value} if value else {"action": "hotkey", "keys": ["command", "v"]}
        if lowered.startswith(("press", "hit")):
            key_text = re.sub(r"^(?:press|hit)\s+", "", phrase, flags=re.I).strip()
            keys = self._normalize_hotkeys(key_text)
            if len(keys) > 1:
                return {"action": "hotkey", "keys": keys}
            return {"action": "press", "key": keys[0] if keys else key_text}
        if lowered.startswith("scroll"):
            direction = "up" if "up" in lowered else "down"
            return {"action": "scroll", "direction": direction}
        if lowered.startswith("find") or lowered.startswith("locate"):
            target = re.sub(r"^(?:find|locate)\s+", "", phrase, flags=re.I).strip()
            return {"action": "find", "target": target}
        return None

    def _target_after(self, phrase: str, pattern: str) -> str:
        target = re.sub(rf"^{pattern}", "", phrase, flags=re.I).strip()
        target = re.sub(r"^(?:button|field|link|menu|icon)\s+(?:called|named)\s+", "", target, flags=re.I).strip()
        target = re.sub(r"\s+(?:button|field|link|menu|icon)$", "", target, flags=re.I).strip()
        return target.strip(" '\"")

    def _target_or_coords(self, target: str, x: int | None, y: int | None) -> Dict[str, Any]:
        if x is not None and y is not None:
            return {"x": x, "y": y}
        return {"target": target} if target else {}

    def _quoted_or_tail(self, phrase: str, verb: str) -> str:
        match = re.search(r"['\"](.+?)['\"]", phrase)
        if match:
            return match.group(1)
        return re.sub(rf"^{verb}\s+", "", phrase, flags=re.I).strip()

    def _normalize_key(self, key: str) -> str:
        aliases = {
            "return": "enter",
            "escape": "esc",
            "spacebar": "space",
            "cmd": "command",
            "⌘": "command",
            "option": "alt",
            "control": "ctrl",
            "delete": "backspace",
        }
        clean = key.lower().strip().replace(" ", "")
        return aliases.get(clean, clean)

    def _normalize_hotkeys(self, value: Any) -> List[str]:
        if isinstance(value, str):
            raw_keys = re.split(r"\s*\+\s*|\s+", value.strip())
        elif isinstance(value, list):
            raw_keys = [str(item) for item in value]
        else:
            raw_keys = []
        return [self._normalize_key(key) for key in raw_keys if self._normalize_key(key)]

    def _scroll_amount(self, action: Dict[str, Any]) -> int:
        if "clicks" in action or "amount" in action:
            return int(action.get("clicks", action.get("amount", 0)) or 0)
        direction = str(action.get("direction", "down")).lower()
        return 6 if direction == "up" else -6

    def _paste_text(self, pyautogui: Any, text: str) -> None:
        try:
            import pyperclip

            pyperclip.copy(text)
            pyautogui.hotkey("command", "v")
        except ImportError:
            pyautogui.write(text, interval=0.01)

    def _requires_confirmation(self, actions: List[Any], task: str) -> bool:
        text = f"{task} {actions}".lower()
        risky_patterns = [
            r"\bsubmit\b",
            r"\bturn\s+in\b",
            r"\bsend\b",
            r"\bdelete\b",
            r"\bremove\b",
            r"\bpay\b",
            r"\bpurchase\b",
            r"\bpassword\b",
            r"\bsocial\s+security\b",
            r"\bcredit\s+card\b",
            r"\bassignment\b.*\b(do|complete|answer|submit|turn\s+in)\b",
            r"\b(do|complete|answer|submit|turn\s+in)\b.*\bassignment\b",
        ]
        return any(re.search(pattern, text) for pattern in risky_patterns)

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": {}}
