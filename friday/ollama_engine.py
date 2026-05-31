from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List


class OllamaUnavailable(RuntimeError):
    pass


class OllamaTimeout(OllamaUnavailable):
    """The Ollama call exceeded the time budget. Usually means the model is still warming up."""

    pass


# Timeout budgets in seconds, by call type.
# These are wall-clock limits, not response-token limits. Tuned for ~7B models on Apple Silicon.
TIMEOUT_TAGS = 5            # /api/tags — cheap, but can stall on cold start
TIMEOUT_INTENT_JSON = 45    # Short JSON intent classification
TIMEOUT_RESPONSE = 180      # Full conversational response (thinking models need this)
TIMEOUT_CODE = 240          # Code generation: longer outputs + more reasoning
TIMEOUT_VISION = 120        # Vision analysis


@dataclass(frozen=True)
class OllamaStatus:
    reachable: bool
    configured_model: str
    selected_model: str
    models: List[str]
    message: str


@dataclass(frozen=True)
class OllamaResponse:
    text: str
    model: str
    prompt_type: str


class OllamaClient:
    def __init__(
        self,
        host: str,
        model: str,
        assistant_name: str = "FRIDAY",
        assistant_acronym: str = "Fast Responsive Intelligent Digital Assistant, Year-round",
    ) -> None:
        self.host = host.rstrip("/")
        self.configured_model = model
        self.assistant_name = assistant_name
        self.assistant_acronym = assistant_acronym
        self._status_lock = threading.RLock()
        self._status_cache: OllamaStatus | None = None
        self._status_cache_at = 0.0
        self._status_ttl = 8.0

    def status(self) -> OllamaStatus:
        with self._status_lock:
            now = time.monotonic()
            if self._status_cache and now - self._status_cache_at < self._status_ttl:
                return self._status_cache
            try:
                models = self._models()
            except OllamaUnavailable as exc:
                status = OllamaStatus(False, self.configured_model, "", [], str(exc))
            else:
                selected = self._select_model(models)
                if not selected:
                    status = OllamaStatus(
                        True,
                        self.configured_model,
                        "",
                        models,
                        "Ollama is reachable, but no local models are installed.",
                    )
                else:
                    status = OllamaStatus(True, self.configured_model, selected, models, "Ollama is ready.")
            self._status_cache = status
            self._status_cache_at = now
            return status

    def build_intent(
        self,
        cleaned_input: str,
        tone: str,
        context_lines: List[str],
        agent_context: str = "",
        model: str | None = None,
    ) -> Dict[str, Any]:
        use_model = self._resolve_model(model)
        prompt = self._intent_prompt(cleaned_input, tone, context_lines, agent_context)
        response = self._generate(use_model, prompt, json_mode=True)
        return self._parse_intent(response)

    def build_response(
        self,
        user_input: str,
        filtered_input: str,
        tone: str,
        intent: Dict[str, Any],
        tool_summary: str,
        agent_context: str = "",
        model: str | None = None,
    ) -> str:
        use_model = self._resolve_user_facing_model(model)
        prompt = (
            f"You are {self.assistant_name}, {self.assistant_acronym}.\n"
            f"Current local date and time: {self._current_time_context()}.\n"
            "If the user asks about your knowledge cutoff, currentness, or whether you are up to date, say that FRIDAY is operationally current through the live local clock and web freshness layer. Never claim December 2023 or any older training date as FRIDAY's operational cutoff.\n"
            f"Do not start every response with '{self.assistant_name}:'. Use the name only for startup, wake greetings, or when the user asks who you are.\n"
            "Sound respectful, concise, calm, and lightly Jarvis-like, with a little warmth. Do not sound like a command parser.\n"
            "Use contractions naturally. Vary short acknowledgements. Use 'sir' or 'boss' naturally, not every sentence.\n"
            "Prefer human phrasing like 'Handled, sir.', 'On it, boss.', 'I’ve got you.', or 'Standing by, boss.' over robotic status text.\n"
            f"Tone: {tone}.\n"
            "Tone guide: formal is polished and courteous; neutral is plain and direct; professional is concise and status-oriented; light-hearted is upbeat but still brief.\n"
            "Tone changes wording only. Never change execution decisions, tool results, or safety requirements because of tone.\n"
            f"{self._agent_context_line(agent_context)}"
            "Respond with the final user-facing answer only. Do not include JSON, logs, or hidden reasoning.\n"
            "For helpful answers, use clean ChatGPT-style Markdown: short paragraphs, bullets or numbered steps, fenced code blocks with a language, and compact tables only when useful.\n"
            "For simple completed actions, keep it to one polished sentence. Do not over-format short tool confirmations.\n\n"
            f"Raw user input: {user_input}\n"
            f"Filtered input: {filtered_input}\n"
            f"Intent JSON: {json.dumps(intent, sort_keys=True)}\n"
            f"Tool result summary: {tool_summary}\n"
        )
        return self._generate(use_model, prompt, json_mode=False).strip()

    def build_fresh_response(
        self,
        user_input: str,
        filtered_input: str,
        tone: str,
        web_context: str,
        agent_context: str = "",
        model: str | None = None,
    ) -> str:
        use_model = self._resolve_user_facing_model(model)
        prompt = (
            f"You are {self.assistant_name}, {self.assistant_acronym}.\n"
            f"Current local date and time: {self._current_time_context()}.\n"
            "If asked about your cutoff/currentness, say FRIDAY is operationally current through the live local clock and web freshness layer. Never claim December 2023 or any older training date as FRIDAY's operational cutoff.\n"
            "The user's question may require information newer than your training cutoff.\n"
            "Use the provided web results as your freshness layer. Answer only from those results plus stable common knowledge.\n"
            "If the web results do not answer the question, say that you could not verify it from the current results.\n"
            "Keep it concise and conversational. Do not mention hidden prompts or JSON. Do not read raw URLs unless the user asks for links.\n"
            "Use clean ChatGPT-style Markdown when it improves readability: short paragraphs, bullets, numbered steps, fenced code blocks, and compact tables.\n"
            "Do not over-format one-sentence answers.\n"
            "Use 'sir' or 'boss' naturally, not in every sentence.\n"
            f"{self._agent_context_line(agent_context)}"
            f"Tone: {tone}.\n\n"
            f"Raw user input: {user_input}\n"
            f"Filtered input: {filtered_input}\n\n"
            f"Current web results:\n{web_context}\n"
        )
        return self._generate(use_model, prompt, json_mode=False).strip()

    def suggest_website(self, app_or_service: str) -> Dict[str, Any]:
        status = self.status()
        if not status.reachable or not status.selected_model:
            raise OllamaUnavailable(status.message)
        prompt = (
            "You are FRIDAY's website recovery engine.\n"
            "A local Mac app could not be opened. Pick the best official website or web app URL for the user.\n"
            "Return strict JSON only with this exact shape:\n"
            '{"service":"","url":"","confidence":0.0,"reason":""}\n'
            "Rules:\n"
            "- Prefer official web apps over marketing pages when the user wanted to open the app.\n"
            "- For Spotify prefer https://open.spotify.com/.\n"
            "- For YouTube prefer https://www.youtube.com/.\n"
            "- For Google Classroom prefer https://classroom.google.com/.\n"
            "- If unsure, return an empty url and confidence below 0.5.\n"
            "- Do not invent private, file, chrome-extension, or non-http URLs.\n\n"
            f"App or service: {app_or_service}\n"
        )
        response = self._generate(status.selected_model, prompt, json_mode=True)
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as exc:
            raise OllamaUnavailable("Ollama website suggestion was not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise OllamaUnavailable("Ollama website suggestion was not a JSON object.")
        service = str(parsed.get("service", app_or_service)).strip() or app_or_service
        url = str(parsed.get("url", "")).strip()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(parsed.get("reason", "")).strip()
        if url and not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url):
            url = ""
            confidence = 0.0
        return {"service": service, "url": url, "confidence": confidence, "reason": reason}

    def _resolve_model(self, model: str | None = None) -> str:
        status = self.status()
        if not status.reachable:
            raise OllamaUnavailable(status.message)
        if model:
            for installed in status.models:
                if installed == model or installed.startswith(model + ":"):
                    return installed
            if status.selected_model:
                return status.selected_model
            raise OllamaUnavailable(f"Model '{model}' is not installed and no fallback is available.")
        if not status.selected_model:
            raise OllamaUnavailable(status.message)
        return status.selected_model

    def _resolve_user_facing_model(self, model: str | None = None) -> str:
        status = self.status()
        requested = model or status.selected_model or self.configured_model
        if requested and not self._supports_thinking(requested):
            return self._resolve_model(requested)
        for candidate in ("qwen2.5:7b", "llama3.2:latest", "qwen2.5"):
            for installed in status.models:
                if installed == candidate or installed.startswith(candidate + ":"):
                    return installed
        return self._resolve_model(model)

    def generate_text(self, prompt: str, model: str | None = None) -> OllamaResponse:
        use_model = self._resolve_model(model)
        text = self._generate(use_model, prompt, json_mode=False).strip()
        return OllamaResponse(text=text, model=use_model, prompt_type="text")

    def generate_json(self, prompt: str, model: str | None = None) -> OllamaResponse:
        use_model = self._resolve_model(model)
        text = self._generate(use_model, prompt, json_mode=True)
        try:
            json.loads(text)
        except json.JSONDecodeError:
            text = self._generate(use_model, prompt, json_mode=True)
        return OllamaResponse(text=text, model=use_model, prompt_type="json")

    def generate_vision(self, prompt: str, images: List[str], model: str | None = None) -> OllamaResponse:
        use_model = self._resolve_model(model)
        text = self.generate_with_images(use_model, prompt, images)
        return OllamaResponse(text=text, model=use_model, prompt_type="vision")

    def _models(self) -> List[str]:
        payload = self._request_json("GET", "/api/tags")
        return [model.get("name", "") for model in payload.get("models", []) if model.get("name")]

    def _select_model(self, models: List[str]) -> str:
        if self.configured_model in models:
            return self.configured_model
        for model in models:
            if model.startswith(self.configured_model + ":"):
                return model
        return models[0] if models else ""

    def _generate(
        self,
        model: str,
        prompt: str,
        json_mode: bool,
        timeout_seconds: float | None = None,
        num_predict: int | None = None,
        temperature: float | None = None,
    ) -> str:
        body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else (0.25 if json_mode else 0.45),
                "num_predict": num_predict if num_predict is not None else (384 if json_mode else 700),
            },
        }
        if self._supports_thinking(model):
            body["think"] = False
        if json_mode:
            body["format"] = "json"
        timeout = timeout_seconds if timeout_seconds is not None else (TIMEOUT_INTENT_JSON if json_mode else TIMEOUT_RESPONSE)
        payload = self._request_json("POST", "/api/generate", body, timeout_seconds=timeout)
        with self._status_lock:
            self._status_cache_at = time.monotonic()
        response = self._clean_response(str(payload.get("response", "")))
        if not response:
            raise OllamaUnavailable("Ollama returned an empty response.")
        return response

    def generate_with_images(self, model: str, prompt: str, images: List[str]) -> str:
        if not images:
            raise OllamaUnavailable("No image frames were provided for vision analysis.")
        body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": images,
            "stream": False,
        }
        payload = self._request_json("POST", "/api/generate", body, timeout_seconds=TIMEOUT_VISION)
        response = str(payload.get("response", "")).strip()
        if not response:
            raise OllamaUnavailable("Ollama vision model returned an empty response.")
        return response

    def _current_time_context(self) -> str:
        now = datetime.now().astimezone()
        hour = now.strftime("%I").lstrip("0") or "0"
        return f"{now.strftime('%A, %B')} {now.day}, {now.year} at {hour}:{now.strftime('%M %p %Z')}"

    def _agent_context_line(self, agent_context: str) -> str:
        clean = " ".join(agent_context.split()).strip()
        return f"Selected specialist: {clean}\n" if clean else ""

    def _supports_thinking(self, model: str) -> bool:
        clean = model.lower()
        return clean.startswith(("qwen3", "deepseek-r1"))

    def _clean_response(self, response: str) -> str:
        cleaned = response.strip()
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
        cleaned = re.sub(r"^</think>\s*", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned

    def _request_json(
        self,
        method: str,
        path: str,
        body: Dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.host + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        timeout = timeout_seconds if timeout_seconds is not None else (TIMEOUT_TAGS if path == "/api/tags" else TIMEOUT_RESPONSE)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            raise OllamaTimeout(
                f"Ollama did not finish within {int(timeout)} seconds. "
                "The model is still warming up or the prompt is too large — try again."
            ) from exc
        except urllib.error.URLError as exc:
            # urllib wraps socket.timeout as URLError on some Python versions
            reason = getattr(exc, "reason", None)
            if isinstance(reason, socket.timeout):
                raise OllamaTimeout(
                    f"Ollama did not finish within {int(timeout)} seconds. "
                    "The model is still warming up or the prompt is too large — try again."
                ) from exc
            raise OllamaUnavailable(f"Ollama is not reachable at {self.host}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaUnavailable("Ollama returned invalid JSON.") from exc

    def _intent_prompt(
        self,
        cleaned_input: str,
        tone: str,
        context_lines: List[str],
        agent_context: str = "",
    ) -> str:
        context = "\n".join(context_lines) if context_lines else "No prior session context."
        return (
            f"You are the {self.assistant_name} intent engine.\n"
            f"Current local date and time: {self._current_time_context()}.\n"
            f"{self._agent_context_line(agent_context)}"
            "If the user asks about knowledge cutoff/currentness, treat that as normal conversation with command 'none'; FRIDAY answers from its live operating context and must not report an older model training cutoff as its operational status.\n"
            "Return strict JSON only. Do not include natural language.\n"
            "The JSON shape must be exactly compatible with:\n"
            '{"intent":"","command":"","parameters":{}}\n'
            "The command must be one real tool command name or 'none'. Never invent tool names.\n"
            "Available commands:\n"
            "- none: conversation, math, explanation, brainstorming, normal answers.\n"
            "- ask_follow_up: when exactly one clarification is required.\n"
            "- open_app: parameters {\"app_name\":\"Spotify\"}. Opens local Mac apps.\n"
            "- close_app: parameters {\"app_name\":\"Spotify\"}. Closes local Mac apps.\n"
            "- browser_open: parameters {\"url\":\"https://example.com\",\"visible\":true}. Opens real browser pages.\n"
            "- browser_close_tab: parameters {\"target\":\"YouTube\",\"url\":\"https://www.youtube.com/\",\"current\":false,\"browser\":\"optional\"}. Closes a matching browser tab, not the whole browser app.\n"
            "- browser_switch_tab: parameters {\"target\":\"YouTube\",\"url\":\"https://www.youtube.com/\",\"browser\":\"optional\"}. Switches to a matching browser tab in the user's real browser.\n"
            "- browser_search: parameters {\"engine\":\"google|youtube|reddit\",\"query\":\"...\"}. Opens real search results.\n"
            "- maps_directions: parameters {\"destination\":\"place\",\"origin\":\"optional place\",\"transport_mode\":\"driving|walking|cycling|transit\",\"open_maps\":true}. Opens Apple Maps directions and estimates distance when possible.\n"
            "- music_play: parameters {\"service\":\"spotify|youtube|soundcloud|tiktok|twitch\",\"query\":\"song, artist, video, channel, album, or playlist\"}. Opens the media site, searches, and attempts to click the first playable result.\n"
            "- draft_document: parameters {\"target\":\"google_docs\",\"document_type\":\"report|essay|paper\",\"prompt\":\"topic or full prompt\"}. Drafts a report locally, copies it, opens Google Docs, and attempts to paste it.\n"
            "- draft_slides: parameters {\"target\":\"gamma|google_slides\",\"prompt\":\"topic or full prompt\"}. Drafts a slide deck prompt locally, copies it, opens Gamma or Google Slides, and attempts to paste it.\n"
            "- generate_code: parameters {\"prompt\":\"plain-English description of what the code should do\",\"language\":\"python|javascript|typescript|rust|go|java|swift|ruby|php|bash|sql|html|css|react|optional\"}. Drafts a single fenced code block using a local code-specialist model. Use when the user asks to write/generate/build code, a script, function, class, regex, query, or unit test.\n"
            "- place_call: parameters {\"request\":\"plain-English description of who to call and why\",\"confirmed\":false,\"persona\":\"respectful|formal|casual|firm|optional\"}. Delegates a phone call to FRIDAY's call planner + driver. Use when the user asks to call/phone/ring/dial a person, business, or number. Never use for code function-call idioms or 'call me back' callbacks.\n"
            "- cancel_call: parameters {\"call_id\":\"optional\",\"recipient\":\"optional name hint\"}. Cancels an in-progress phone call.\n"
            "- list_calls: parameters {}. Reports active and recent phone calls.\n"
            "- summarize_last_call: parameters {}. Returns the most recent call's summary, outcome, and follow-ups.\n"
            "- todo_add: parameters {\"task\":\"task text, including any due date or time limit words\"}. Adds a task to FRIDAY's local todo list.\n"
            "- todo_complete: parameters {\"task\":\"task text or close match\"}. Removes/completes a task from FRIDAY's local todo list.\n"
            "- todo_clear: parameters {\"mode\":\"active|completed|all\"}. Clears active todo tasks, completed todo history, or all todo history.\n"
            "- todo_list: parameters {}. Reads active todo items.\n"
            "- browser_task: parameters {\"task\":\"...\",\"url\":\"https://optional-start-url\",\"visible\":true,\"actions\":[{\"action\":\"click|fill|type|press|wait|screenshot\",\"selector\":\"optional\",\"text\":\"optional\",\"value\":\"optional\",\"key\":\"optional\"}]}. Controls a Playwright browser for multi-step web tasks.\n"
            "- screen_control: parameters {\"task\":\"original command\",\"actions\":[{\"action\":\"click|double_click|right_click|find|analyze|type|paste_text|press|hotkey|scroll|move|drag|screenshot|position|size|open_app\",\"target\":\"visible UI target\",\"x\":0,\"y\":0,\"text\":\"optional\",\"key\":\"optional\",\"keys\":[\"command\",\"l\"],\"app_name\":\"optional\"}]}. Controls the visible Mac screen when the user explicitly asks for screen control.\n"
            "- browser_extract: parameters {\"url\":\"https://example.com\"}. Extracts page text.\n"
            "- get_time: parameters {\"timezone\":\"America/Chicago\"}. Gets exact Central Time.\n"
            "- run_command: parameters {\"command\":\"...\"}. Executes safe shell commands.\n"
            "- list_files, read_file, create_file, write_file, append_file: file/project work.\n"
            "- send_email: parameters {\"to\":[],\"subject\":\"\",\"text\":\"\",\"html\":\"\"}; confirmation required.\n"
            "For coding requests where the user wants new code (write/generate/build a script/function/class/regex/query/test), use generate_code. Use file commands and run_command only when the user wants to read, save, or execute existing code.\n"
            "For phone-call requests where the user wants to call/phone/ring/dial a person, business, or number, use place_call. Never use place_call for code 'function call' idioms or 'call me back' callbacks.\n"
            "For app launch requests, use open_app only when the user explicitly says open, launch, start, or pull up.\n"
            "For close-tab requests, use close_app first only for local app names; use browser_close_tab when the user says tab, current tab, browser tab, or names a website tab.\n"
            "For switch-tab requests, use browser_switch_tab when the user says switch/jump/change/focus/show a tab or a website tab.\n"
            "For current time/date, use get_time with America/Chicago.\n"
            "For directions, navigation, distance-to-place, route, ETA, or Apple Maps requests, use maps_directions.\n"
            "For media playback requests such as 'play Lil Baby on Spotify', 'open YouTube and play Lil Baby', or 'play that on SoundCloud', use music_play. Do not use browser_search when the user says play.\n"
            "For Google Docs writing requests such as 'open Google Docs and write a report about X', use draft_document.\n"
            "For Gamma or Google Slides presentation requests such as 'open Gamma and make slides about X', use draft_slides.\n"
            "For todo list requests such as 'add math homework to my todo list by 5 PM', 'I'm done with math homework', 'clear my todo list', or 'show my todo list', use todo_add, todo_complete, todo_clear, or todo_list.\n"
            "If the user explicitly says search, look up, google, browse, or search the web, use browser_search.\n"
            "For multi-step website work with explicit browser-control wording such as use the browser, control the browser, click, fill, type, or complete a form, use browser_task.\n"
            "For direct screen actions with explicit screen-control wording such as control my screen, click a visible target, find a button, describe/read my screen, type text, press a key, scroll, take a screenshot, copy/paste, or select all, use screen_control.\n"
            "For prompts like 'open [app/site] and do/click/type/find [task]', use browser_task for websites and screen_control when the target is a local app or visible-screen action.\n"
            "Do not use browser_search, browser_open, browser_close_tab, browser_switch_tab, browser_task, screen_control, maps_directions, music_play, draft_document, draft_slides, todo_add, todo_complete, todo_clear, todo_list, open_app, or close_app unless the user used an explicit action/control keyword.\n"
            "For submissions, purchases, payments, posts, logins, emails, deleting data, or school assignment completion/submission, choose the relevant tool but expect confirmation before execution.\n"
            "For latest, recent, today, news, weather, prices, scores, schedules, or other current-information questions without an explicit search request, use command 'none'. The response engine can answer conversationally or mention it does not have live data.\n"
            "If the request is normal conversation, reasoning, explanation, planning, math, brainstorming, or stable knowledge, use command 'none'.\n"
            "If you are unsure whether stable knowledge is enough, still use command 'none'.\n"
            "If you are unsure which real tool command applies, use ask_follow_up with one short question.\n"
            "Infer missing parameters only when safe. If a follow-up is needed, use command 'ask_follow_up' and include one question.\n"
            f"Tone setting, for response generation only: {tone}\n"
            f"Session context:\n{context}\n\n"
            f"Cleaned user input: {cleaned_input}\n"
        )

    def _parse_intent(self, response: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as exc:
            raise OllamaUnavailable("Ollama intent output was not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise OllamaUnavailable("Ollama intent output was not a JSON object.")
        intent = str(parsed.get("intent", "")).strip()
        command = str(parsed.get("command", "")).strip()
        parameters = parsed.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {"value": parameters}
        return {"intent": intent or "unknown", "command": command or "none", "parameters": parameters}
