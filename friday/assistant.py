from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List

from friday.agents import AgentSelection, MultiAgentOrchestrator
from friday.brain import IntentParser
from friday.config import DEFAULT_PERSONALITY_CONFIG, PersonalityConfig
from friday.events import EventBus
from friday.input_filter import InputProcessor
from friday.local_intents import LocalIntentResolver
from friday.memory import ShortTermMemory
from friday.model_manager import ModelManager
from friday.ollama_engine import OllamaClient, OllamaUnavailable
from friday.services import WebSearchClient
from friday.state import StateManager
from friday.task_classifier import classify_task
from friday.tools import ToolResult, ToolRouter
from friday.transcript import TranscriptEntry, TranscriptLogger
from friday.tts import MacOSTTS
from friday.voice.personality_engine import PersonalityEngine
from friday.voice.stop_phrase_detector import StopPhraseDetector


@dataclass(frozen=True)
class InteractionResult:
    source: str
    raw_input: str
    filtered_input: str
    intent: Dict[str, Any]
    executed_commands: List[Dict[str, Any]]
    final_output: str


class _QueuedInput:
    def __init__(self, text: str, source: str) -> None:
        self.text = text
        self.source = source
        self.event = threading.Event()
        self.result: InteractionResult | None = None
        self.error: BaseException | None = None


class FridayAssistant:
    def __init__(
        self,
        state: StateManager,
        tts: MacOSTTS,
        transcript: TranscriptLogger,
        events: EventBus,
        ollama: OllamaClient,
        tools: ToolRouter,
        assistant_name: str = "FRIDAY",
        assistant_acronym: str = "Fast Responsive Intelligent Digital Assistant, Year-round",
        personality: PersonalityConfig | None = None,
        publish_ready: bool = True,
        model_manager: ModelManager | None = None,
        timezone: str = "",
    ) -> None:
        self.state = state
        self.tts = tts
        self.transcript = transcript
        self.events = events
        self.ollama = ollama
        self.tools = tools
        self.assistant_name = assistant_name
        self.assistant_acronym = assistant_acronym
        self.model_manager = model_manager
        self.personality = personality or PersonalityConfig.from_dict(DEFAULT_PERSONALITY_CONFIG)
        self.personality_engine = PersonalityEngine(self.personality)
        self.input_processor = InputProcessor()
        self.stop_phrases = StopPhraseDetector()
        self.intent_parser = IntentParser()
        self.local_intents = LocalIntentResolver(timezone=timezone)
        self.memory = ShortTermMemory()
        self.web_search = WebSearchClient()
        self.agents = MultiAgentOrchestrator()
        self._pending_intent: Dict[str, Any] | None = None
        self._queue: queue.Queue[_QueuedInput] = queue.Queue()
        self._worker = threading.Thread(target=self._work_loop, name="friday-input-worker", daemon=True)
        self._worker.start()
        if publish_ready:
            greeting = f"{self.assistant_name}: Online. {self.assistant_acronym} is ready."
            self.events.publish("assistant_ready", {"message": greeting})

    def submit_text(self, text: str, source: str = "text") -> InteractionResult:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Input cannot be empty.")
        self.tts.interrupt()
        stop_category = self.stop_phrases.category(clean_text)
        if stop_category in {"cancel", "interrupt"}:
            self.tools.emergency_stop.trigger_from_text(clean_text)
        item = _QueuedInput(clean_text, source)
        self._queue.put(item)
        item.event.wait()
        if item.error:
            raise item.error
        if item.result is None:
            raise RuntimeError("FRIDAY did not produce a result.")
        return item.result

    def submit_file_analysis(
        self,
        prompt: str,
        file_name: str,
        mime_type: str,
        vision_model: str,
        frame_count: int,
        analysis: str,
    ) -> InteractionResult:
        clean_prompt = " ".join((prompt or "Analyze this file.").split())
        raw_input = f"Uploaded {file_name}. {clean_prompt}"
        source = "file-upload"
        self.tts.interrupt()
        self.state.begin_session()
        self.events.publish("input_received", {"source": source, "text": raw_input})
        try:
            processed = self.input_processor.normalize(raw_input)
            filtered_input = self.memory.resolve_context_reference(processed.cleaned)
            agent = self.agents.select(f"analyze uploaded screenshot video visual file {filtered_input}")
            intent: Dict[str, Any] = {
                "intent": "visual_file_analysis",
                "command": "none",
                "parameters": {
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "vision_model": vision_model,
                    "frame_count": frame_count,
                },
            }
            intent = self._validate_intent(raw_input, filtered_input, intent)
            self._attach_agent_context(intent, agent)
            final_output = self._ensure_named_response(analysis)
            self.memory.remember(source, processed)
            result = InteractionResult(
                source=source,
                raw_input=raw_input,
                filtered_input=filtered_input,
                intent=intent,
                executed_commands=[],
                final_output=final_output,
            )
            self.transcript.log(
                TranscriptEntry(
                    created_at=time.time(),
                    source=source,
                    raw_input=raw_input,
                    filtered_input=filtered_input,
                    intent=intent,
                    executed_commands=[],
                    final_output=final_output,
                )
            )
            self.events.publish("assistant_response", {"message": final_output, "intent": intent, "source": source})
            self._speak_async(final_output)
            return result
        finally:
            self.state.end_session()

    def interrupt_tts(self) -> bool:
        interrupted = self.tts.interrupt()
        self.events.publish("tts_interrupted", {"interrupted": interrupted})
        return interrupted

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.assistant_name,
            "full_name": self.assistant_acronym,
            "state": asdict(self.state.snapshot()),
            "personality": {
                "tone": self.personality.tone,
                "style": self.personality.style,
                "address_terms": self.personality.default_address_terms,
            },
            "tts": asdict(self.tts.status()),
            "ollama": asdict(self.ollama.status()),
            "control": self.tools.control_status(),
            "todos": self.tools.todos.snapshot(),
            "queue_depth": self._queue.qsize(),
        }

    def _work_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                item.result = self._process_text(item.text, item.source)
            except BaseException as exc:
                item.error = exc
            finally:
                item.event.set()
                self._queue.task_done()

    def _process_text(self, raw_input: str, source: str) -> InteractionResult:
        self.state.begin_session()
        self.events.publish("input_received", {"source": source, "text": raw_input})
        task_type = ""
        selected_model = ""
        try:
            processed = self.input_processor.normalize(raw_input)
            filtered_input = self.memory.resolve_context_reference(processed.cleaned)
            agent = self.agents.select(filtered_input)
            lowered = raw_input.lower()
            stop_category = self.stop_phrases.category(filtered_input)
            if stop_category not in {"cancel", "interrupt"} and self.tools.emergency_stop.is_stop_requested():
                self.tools.emergency_stop.clear()
            executed_tool_results: List[ToolResult] = []
            if lowered.startswith("set tone to "):
                tone = raw_input[len("set tone to ") :].strip()
                selected_tone = self.state.set_tone(tone)
                final_output = self._ensure_named_response(f"Tone set to {selected_tone}.")
                intent = {"intent": "set_tone", "command": "set_tone", "parameters": {"tone": selected_tone}}
            elif lowered in {"status", "friday status", "system status"}:
                final_output = self._status_response()
                intent = {"intent": "status", "command": "report_status", "parameters": {}}
            elif self._is_operational_freshness_request(filtered_input):
                final_output = self._freshness_status_response()
                intent = {"intent": "freshness_status", "command": "none", "parameters": {"live_web_freshness": True}}
            elif stop_category in {"gratitude", "night", "cancel", "interrupt"}:
                category = stop_category
                self.state.mute()
                if category in {"cancel", "interrupt"}:
                    self.tools.emergency_stop.trigger_from_text(filtered_input)
                final_output = self._stop_phrase_response(category)
                intent = {"intent": "stop_phrase", "command": "none", "parameters": {"category": category}}
            elif self._is_pending_confirmation(lowered) and self._pending_intent:
                intent = self._pending_intent
                self._pending_intent = None
                parameters = intent.setdefault("parameters", {})
                if isinstance(parameters, dict):
                    parameters["confirmed"] = True
                intent = self._validate_intent(raw_input, filtered_input, intent)
                executed_tool_results = self.tools.execute(intent)
                final_output = self._final_output(raw_input, filtered_input, intent, executed_tool_results, agent)
            else:
                local_intent = self.local_intents.resolve(filtered_input)
                if local_intent:
                    intent = local_intent.intent
                    self._attach_raw_task_context(intent, raw_input)
                    intent = self._validate_intent(raw_input, filtered_input, intent)
                    final_output = local_intent.final_output
                    if intent.get("command") == "set_tts":
                        silent = bool(intent.get("parameters", {}).get("silent", False))
                        self.tts.set_silent(silent)
                        final_output = self._ensure_named_response("TTS is now silent." if silent else "TTS is now on.")
                    elif intent.get("command") == "test_tts":
                        final_output = self._ensure_named_response("TTS is working. I will speak final responses out loud.")
                    elif intent.get("command") == "ask_follow_up":
                        final_output = self._follow_up_output(intent, filtered_input)
                    elif not final_output:
                        executed_tool_results = self.tools.execute(intent)
                        if self._needs_open_app_web_fallback(intent, executed_tool_results):
                            extra_results, final_output = self._open_app_web_fallback(intent, executed_tool_results[0])
                            executed_tool_results.extend(extra_results)
                        else:
                            if any(result.requires_confirmation for result in executed_tool_results):
                                self._pending_intent = intent
                            final_output = self._local_final_output(intent, executed_tool_results)
                else:
                    task_type = classify_task(filtered_input)
                    selected_model = self.model_manager.select_model_for_task(task_type) if self.model_manager else ""
                    try:
                        if self._should_use_freshness_search(filtered_input):
                            intent = {
                                "intent": "current_web_answer",
                                "command": "none",
                                "parameters": {"query": filtered_input, "freshness": "web"},
                            }
                            intent = self._validate_intent(raw_input, filtered_input, intent)
                            final_output = self._fresh_current_response(raw_input, filtered_input, agent, model=selected_model or None)
                        elif self._can_agent_answer_directly(filtered_input, agent):
                            intent = self._conversation_intent(filtered_input, f"{agent.name} direct reasoning path.")
                            intent = self._validate_intent(raw_input, filtered_input, intent)
                            final_output = self._final_output(raw_input, filtered_input, intent, executed_tool_results, agent, model=selected_model or None)
                        else:
                            intent = self.ollama.build_intent(
                                filtered_input,
                                self.state.snapshot().tone,
                                self.memory.context_lines(),
                                agent.prompt_context,
                                model=selected_model or None,
                            )
                            intent = self._stabilize_ollama_intent(intent, filtered_input)
                            self._attach_raw_task_context(intent, raw_input)
                            intent = self._validate_intent(raw_input, filtered_input, intent)
                            if intent.get("command") == "ask_follow_up":
                                final_output = self._follow_up_output(intent, filtered_input)
                            else:
                                executed_tool_results = self.tools.execute(intent)
                                app_fallback_output = ""
                                if self._needs_open_app_web_fallback(intent, executed_tool_results):
                                    extra_results, app_fallback_output = self._open_app_web_fallback(intent, executed_tool_results[0])
                                    executed_tool_results.extend(extra_results)
                                if any(result.requires_confirmation for result in executed_tool_results):
                                    self._pending_intent = intent
                                final_output = app_fallback_output or self._final_output(raw_input, filtered_input, intent, executed_tool_results, agent, model=selected_model or None)
                    except OllamaUnavailable as exc:
                        if self._explicit_web_search_requested(filtered_input):
                            intent = self._web_search_intent(filtered_input, "User requested web search while Ollama was unavailable.")
                            intent = self._validate_intent(raw_input, filtered_input, intent)
                            executed_tool_results = self.tools.execute(intent)
                            final_output = self._local_final_output(intent, executed_tool_results)
                        else:
                            intent = {
                                "intent": "local_system_notice",
                                "command": "none",
                                "parameters": {"reason": str(exc)},
                            }
                            default_name = self.model_manager.default_model if self.model_manager else "qwen3:4b"
                            final_output = self._ensure_named_response(
                                f"{exc} Pull a local model such as {default_name}, then I can use Ollama for reasoning."
                            )

            self._attach_agent_context(intent, agent)
            self.memory.remember(source, processed)

            result = InteractionResult(
                source=source,
                raw_input=raw_input,
                filtered_input=filtered_input,
                intent=intent,
                executed_commands=[asdict(item) for item in executed_tool_results],
                final_output=final_output,
            )
            model_type = ""
            if selected_model:
                if self.model_manager and selected_model == self.model_manager.fast_model:
                    model_type = "fast"
                elif self.model_manager and selected_model == self.model_manager.vision_model:
                    model_type = "vision"
                else:
                    model_type = "default"
            self.transcript.log(
                TranscriptEntry(
                    created_at=time.time(),
                    source=source,
                    raw_input=raw_input,
                    filtered_input=filtered_input,
                    intent=intent,
                    executed_commands=[asdict(item) for item in executed_tool_results],
                    final_output=final_output,
                    task_classification=task_type,
                    selected_model=selected_model,
                    model_type=model_type,
                )
            )
            self.events.publish("assistant_response", {"message": final_output, "intent": intent, "source": source})
            self._speak_async(final_output)
            return result
        finally:
            self.state.end_session()

    def _speak_async(self, text: str) -> None:
        threading.Thread(
            target=self.tts.speak,
            args=(text,),
            name="friday-tts",
            daemon=True,
        ).start()

    def _status_response(self) -> str:
        status = self.ollama.status()
        tts_status = self.tts.status()
        if status.selected_model:
            ollama_text = f"Ollama is ready with {status.selected_model}."
        else:
            ollama_text = status.message
        speech_text = "TTS is silent." if tts_status.silent else "TTS is ready."
        return self._ensure_named_response(f"I'm online. {ollama_text} {speech_text}")

    def _stop_phrase_response(self, category: str) -> str:
        if category == "gratitude":
            return self._ensure_named_response("Anytime, sir.")
        if category == "night":
            return self._ensure_named_response("Good night, sir.")
        return self._ensure_named_response("Stopped, sir.")

    def _final_output(
        self,
        raw_input: str,
        filtered_input: str,
        intent: Dict[str, Any],
        tool_results: List[ToolResult],
        agent: AgentSelection | None = None,
        model: str | None = None,
    ) -> str:
        tool_summary = self._tool_summary(tool_results)
        if tool_results and any(result.requires_confirmation for result in tool_results):
            return self._ensure_named_response(f"{tool_summary} Say confirm to proceed.")
        if tool_results:
            return self._local_final_output(intent, tool_results)
        try:
            return self._ensure_named_response(
                self.ollama.build_response(
                    user_input=raw_input,
                    filtered_input=filtered_input,
                    tone=self.state.snapshot().tone,
                    intent=intent,
                    tool_summary=tool_summary,
                    agent_context=agent.prompt_context if agent else "",
                    model=model,
                )
            )
        except OllamaUnavailable as exc:
            if tool_results:
                return self._ensure_named_response(tool_summary)
            return self._ensure_named_response(str(exc))

    def _local_final_output(self, intent: Dict[str, Any], tool_results: List[ToolResult]) -> str:
        if not tool_results:
            return self._ensure_named_response("Done.")
        result = tool_results[0]
        command = str(intent.get("command", ""))
        if command == "get_time" and result.success:
            return self._ensure_named_response(result.data.get("spoken", result.message))
        if command == "generate_code" and result.success:
            fenced = result.data.get("fenced") or ""
            language = result.data.get("language") or "code"
            model = result.data.get("model") or ""
            draft_path = result.data.get("draft_path") or ""
            lines = [result.message]
            if fenced:
                lines.append("")
                lines.append(fenced)
            footer_bits = []
            if model:
                footer_bits.append(f"_Model: `{model}`_")
            if draft_path:
                footer_bits.append(f"_Saved to `{draft_path}`_")
            if footer_bits:
                lines.append("")
                lines.append(" · ".join(footer_bits))
            return self._ensure_named_response("\n".join(lines), context="task_complete")
        if command == "place_call":
            lines = [result.message]
            preview = (result.data or {}).get("brief_preview") if isinstance(result.data, dict) else None
            if isinstance(preview, dict):
                points = preview.get("talking_points") or []
                if isinstance(points, list) and points:
                    lines.append("")
                    lines.append("**Talking points:** " + ", ".join(str(p) for p in points[:3]))
                objective = preview.get("objective")
                if objective:
                    lines.append(f"**Objective:** {objective}")
            return self._ensure_named_response("\n".join(lines), context="task_complete" if result.success else None)
        if command == "summarize_last_call" and result.success:
            data = result.data if isinstance(result.data, dict) else {}
            lines = [result.message]
            follow_ups = data.get("follow_ups") or []
            if isinstance(follow_ups, list) and follow_ups:
                lines.append("")
                lines.append("**Follow-ups:**")
                for item in follow_ups:
                    lines.append(f"- {item}")
            return self._ensure_named_response("\n".join(lines), context="task_complete")
        if command in {"open_app", "close_app", "browser_open", "browser_close_tab", "browser_switch_tab", "open_website", "browser_search", "maps_directions", "music_play", "draft_document", "draft_slides", "generate_code", "cancel_call", "list_calls", "screen_control_plan", "browser_task", "screen_control", "todo_add", "todo_complete", "todo_clear", "todo_list"}:
            if result.success:
                return self._ensure_named_response(result.message, context="task_complete")
            return self._ensure_named_response(result.message)
        return self._ensure_named_response(result.message)

    def _stabilize_ollama_intent(self, intent: Dict[str, Any], filtered_input: str) -> Dict[str, Any]:
        command = str(intent.get("command", "none")).strip()
        no_tool_commands = {"", "none", "ask_follow_up", "report_status", "set_tone"}
        if self._explicit_web_search_requested(filtered_input) and command in {"", "none"}:
            return self._web_search_intent(filtered_input, "User requested web search.")
        if command == "browser_search" and not self._explicit_web_search_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed web search because no search keyword was used.")
        if command in {"browser_task", "screen_control"} and not self._explicit_control_action_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed automation because no control/action keyword was used.")
        if command == "music_play" and not self._explicit_music_action_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed music playback because no explicit play keyword was used.")
        if command in {"draft_document", "draft_slides"} and not self._explicit_productivity_action_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed productivity drafting because no explicit document or slides request was used.")
        if command == "generate_code" and not self._explicit_code_action_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed code generation because no explicit code-writing keyword was used.")
        if command == "place_call" and not self._explicit_phone_action_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed phone call because no explicit dial/phone/ring keyword was used.")
        if command in {"browser_open", "browser_close_tab", "browser_switch_tab", "open_website", "open_app", "close_app"} and not self._explicit_browser_or_app_action_requested(filtered_input):
            return self._conversation_intent(filtered_input, "Suppressed browser/app action because no action keyword was used.")
        if command in no_tool_commands:
            return intent
        if command not in self.tools.TOOL_COMMANDS:
            return self._conversation_intent(filtered_input, f"Suppressed unknown tool command: {command}")
        return intent

    def _attach_raw_task_context(self, intent: Dict[str, Any], raw_input: str) -> None:
        if intent.get("command") not in {"browser_task", "screen_control"}:
            return
        parameters = intent.setdefault("parameters", {})
        if isinstance(parameters, dict):
            parameters.setdefault("raw_input", raw_input)

    def _attach_agent_context(self, intent: Dict[str, Any], agent: AgentSelection) -> None:
        parameters = intent.setdefault("parameters", {})
        if isinstance(parameters, dict):
            parameters.setdefault("agent", agent.metadata())

    def _validate_intent(self, raw_input: str, filtered_input: str, intent: Dict[str, Any]) -> Dict[str, Any]:
        return self.intent_parser.validate_legacy_intent(raw_input, filtered_input, intent)

    def _is_pending_confirmation(self, lowered_input: str) -> bool:
        clean = " ".join(lowered_input.strip().split())
        return clean in {
            "confirm",
            "yes",
            "yes please",
            "yeah",
            "yep",
            "sure",
            "do it",
            "proceed",
            "go ahead",
            "search",
            "search it",
            "search the web",
            "yes search",
            "look it up",
        }

    def _explicit_web_search_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        polite_prefix = r"^(?:can you\s+|could you\s+|would you\s+|please\s+|friday\s+)?"
        command_patterns = [
            polite_prefix + r"(?:search|look up|browse|google)\b",
            polite_prefix + r"(?:search\s+(?:the\s+)?web|search\s+online|internet\s+search)\b",
        ]
        return any(re.search(pattern, text) for pattern in command_patterns)

    def _explicit_browser_or_app_action_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        action_prefix = r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:open|launch|start|pull up|go to|close|quit|exit)\b"
        return bool(re.search(action_prefix, text) or self._explicit_web_search_requested(filtered_input))

    def _explicit_music_action_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        return bool(
            re.search(
                r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:play|put on|start playing)\b",
                text,
            )
            or re.search(
                r"\b(?:open|launch|start|pull up|go to)\s+(?:spotify|spotufy|spotfy|spotifiy|youtube|you\s+tube|yt|soundcloud|sound\s+cloud|tiktok|tik\s+tok|twitch)\s+and\s+(?:play|put on|start playing)\b",
                text,
            )
        )

    def _explicit_code_action_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        polite_prefix = r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?"
        code_verbs = r"(?:write|generate|create|make|build|draft|produce|code(?:\s+up)?|give\s+me)"
        code_nouns = (
            r"(?:code|script|function|method|class|module|program|snippet|component|hook"
            r"|cli|util(?:ity)?|library|api|endpoint|regex|algorithm|implementation"
            r"|unit\s+test|test\s+case)"
        )
        return bool(re.search(polite_prefix + code_verbs + r"\b.*\b" + code_nouns + r"\b", text))

    def _explicit_phone_action_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        # Bail on programming/callback idioms first so they never pass the guard.
        if re.search(r"\bcall\s+(?:this\s+|the\s+)?(?:function|method|api|endpoint|module|hook)\b", text):
            return False
        if re.search(r"\bcall\s+(?:it|this|that)\b", text):
            return False
        if re.match(r"^call\s+me\s+(?:later|back|when|tonight|tomorrow|in\s+the\s+morning)\b", text):
            return False
        polite_prefix = r"^(?:hey\s+friday[,\s]+|friday[,\s]+|please\s+|can\s+you\s+|could\s+you\s+)?"
        phone_verbs = r"(?:call|phone|ring(?:\s+up)?|dial)"
        return bool(re.match(polite_prefix + phone_verbs + r"\b\s+\S", text))

    def _explicit_productivity_action_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        polite_prefix = r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?"
        return bool(
            re.search(polite_prefix + r"(?:write|draft|create|make|build|generate)\b.*\b(?:report|essay|paper|document|slides?|slide\s+deck|deck|presentation|slideshow)\b", text)
            or re.search(r"\b(?:google\s+docs?|docs?|gamma|google\s+slides?|slides?)\b.*\b(?:write|draft|create|make|build|generate)\b", text)
        )

    def _explicit_control_action_requested(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        control_terms = [
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?use\s+(?:the\s+)?browser\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?control\s+(?:the\s+)?browser\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?automate\s+(?:the\s+)?browser\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?browser\s+task\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?control\s+(?:my\s+)?screen\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?screen\s+control\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:click|type|fill|press|scroll|navigate|find|locate|paste|copy|select all)\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:describe|read|analyze|look at)\s+(?:my\s+)?(?:screen|display|window|page)\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:what'?s|what is)\s+on\s+(?:my\s+)?(?:screen|display)\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:take\s+)?(?:screenshot|screen shot|capture screen)\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?open\b.+\band\b.+",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?complete\b.*\bform\b",
            r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?fill\s+out\b",
        ]
        return self._explicit_browser_or_app_action_requested(filtered_input) or any(re.search(pattern, text) for pattern in control_terms)

    def _can_answer_without_intent_pass(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        if not text:
            return False
        if self._needs_current_info(text):
            return False
        if self._explicit_web_search_requested(text) or self._explicit_browser_or_app_action_requested(text) or self._explicit_control_action_requested(text):
            return False
        tool_terms = [
            "install",
            "download",
            "delete",
            "remove",
            "move",
            "rename",
            "copy",
            "paste",
            "click",
            "type",
            "scroll",
            "submit",
            "send",
            "draft",
            "turn in",
            "assignment",
            "classroom",
            "run",
            "execute",
            "start server",
            "stop server",
        ]
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in tool_terms):
            return False
        conversation_patterns = [
            r"^(?:what|why|how|who|where|when)\b",
            r"^(?:explain|describe|define|compare|brainstorm|help me understand)\b",
            r"^(?:tell me about|give me ideas|give me advice|can you explain)\b",
            r"^(?:is|are|do|does|did|can|could|would|should)\b",
        ]
        return any(re.search(pattern, text) for pattern in conversation_patterns)

    def _can_agent_answer_directly(self, filtered_input: str, agent: AgentSelection) -> bool:
        text = filtered_input.lower().strip()
        if not text:
            return False
        if self._needs_current_info(text):
            return False
        if (
            self._explicit_web_search_requested(text)
            or self._explicit_browser_or_app_action_requested(text)
            or self._explicit_control_action_requested(text)
        ):
            return False
        if self._can_answer_without_intent_pass(text):
            return True
        if agent.agent_id in {"math", "conversational", "study"}:
            return True
        if agent.agent_id == "coding":
            toolish_coding_request = re.search(
                r"\b(repo|project|terminal|command|install|run|execute|server|file|folder|edit|patch|fix this repo|apply)\b",
                text,
            )
            return not bool(toolish_coding_request)
        return False

    def _should_use_freshness_search(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        if not self._needs_current_info(text):
            return False
        if self._explicit_web_search_requested(text):
            return False
        if self._explicit_control_action_requested(text) or self._explicit_browser_or_app_action_requested(text):
            return False
        return True

    def _is_operational_freshness_request(self, filtered_input: str) -> bool:
        text = filtered_input.lower().strip()
        patterns = [
            r"\bknowledge\s+cut\s*off\b",
            r"\btraining\s+cut\s*off\b",
            r"\bcut\s*off\s+date\b",
            r"\bare\s+you\s+(?:up\s+to\s+date|current|updated)\b",
            r"\bhow\s+(?:current|updated|up\s+to\s+date)\s+are\s+you\b",
            r"\bwhat\s+date\s+do\s+you\s+know\b",
            r"\bdo\s+you\s+know\s+(?:today|current|recent|latest)\b",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _freshness_status_response(self) -> str:
        now = datetime.now().astimezone()
        hour = now.strftime("%I").lstrip("0") or "0"
        current_time = f"{now.strftime('%A, %B')} {now.day}, {now.year} at {hour}:{now.strftime('%M %p %Z')}"
        return self._ensure_named_response(
            "Operationally, I am current as of "
            f"{current_time}. My local Ollama model can still have an older training cutoff, "
            "but FRIDAY now checks the web for current facts before answering questions about news, today, latest info, prices, weather, schedules, and anything time-sensitive."
        )

    def _fresh_current_response(
        self,
        raw_input: str,
        filtered_input: str,
        agent: AgentSelection | None = None,
        model: str | None = None,
    ) -> str:
        try:
            results = self.web_search.search(filtered_input, max_results=4)
            web_context = self.web_search.format_for_prompt(results)
        except Exception as exc:
            return self._ensure_named_response(f"I could not reach web search right now: {exc}")
        try:
            return self._ensure_named_response(
                self.ollama.build_fresh_response(
                    user_input=raw_input,
                    filtered_input=filtered_input,
                    tone=self.state.snapshot().tone,
                    web_context=web_context,
                    agent_context=agent.prompt_context if agent else "",
                    model=model,
                )
            )
        except OllamaUnavailable as exc:
            if results:
                titles = "; ".join(result.title for result in results[:3])
                return self._ensure_named_response(f"Ollama is not ready, but I found current web results: {titles}")
            return self._ensure_named_response(f"{exc} I could not summarize current web results without Ollama.")

    def _needs_current_info(self, filtered_input: str) -> bool:
        text = filtered_input.lower()
        if re.search(r"^(?:how are you|how'?s it going|what'?s up|thanks|thank you)\b", text):
            return False
        current_patterns = [
            r"\blatest\b",
            r"\brecent\b",
            r"\btoday\b",
            r"\bright now\b",
            r"\bcurrent\b",
            r"\bnews\b",
            r"\bweather\b",
            r"\bscore\b",
            r"\bschedule\b",
            r"\bprice\b",
            r"\bstock\b",
            r"\bnear me\b",
            r"\bthis week\b",
            r"\bthis month\b",
            r"\bwho is the\b",
        ]
        return any(re.search(pattern, text) for pattern in current_patterns)

    def _web_search_intent(self, query: str, reason: str) -> Dict[str, Any]:
        clean_query = " ".join(query.strip().split())
        return {
            "intent": "web_search_fallback",
            "command": "browser_search",
            "parameters": {"engine": "google", "query": clean_query, "reason": reason},
        }

    def _conversation_intent(self, query: str, reason: str) -> Dict[str, Any]:
        clean_query = " ".join(query.strip().split())
        return {
            "intent": "conversation",
            "command": "none",
            "parameters": {"query": clean_query, "reason": reason},
        }

    def _web_search_offer_intent(self, query: str, reason: str) -> Dict[str, Any]:
        clean_query = " ".join(query.strip().split())
        return {
            "intent": "offer_web_search",
            "command": "ask_follow_up",
            "parameters": {
                "offer_web_search": True,
                "engine": "google",
                "query": clean_query,
                "reason": reason,
                "question": f"I can answer best by checking the web for '{clean_query}'. Do you want me to search?",
            },
        }

    def _follow_up_output(self, intent: Dict[str, Any], filtered_input: str) -> str:
        parameters = intent.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        question = str(parameters.get("question") or "").strip()
        if bool(parameters.get("offer_web_search", False)):
            query = str(parameters.get("query") or filtered_input).strip()
            reason = str(parameters.get("reason") or "User approved web search.").strip()
            if query:
                self._pending_intent = self._web_search_intent(query, reason)
            if not question:
                question = f"I can search the web for '{query}'. Do you want me to?"
        if not question:
            question = "I need one detail before I can continue. What should I use?"
        return self._ensure_named_response(question, context="question")

    def _needs_open_app_web_fallback(self, intent: Dict[str, Any], tool_results: List[ToolResult]) -> bool:
        if str(intent.get("command", "")) != "open_app":
            return False
        if not tool_results:
            return False
        return not tool_results[0].success

    def _open_app_web_fallback(self, intent: Dict[str, Any], failed_result: ToolResult) -> tuple[List[ToolResult], str]:
        parameters = intent.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        app_name = str(parameters.get("app_name") or failed_result.data.get("requested") or failed_result.data.get("app_name") or "").strip()
        if not app_name:
            return [], self._ensure_named_response(failed_result.message)

        suggestion: Dict[str, Any] = {}
        try:
            suggestion = self.ollama.suggest_website(app_name)
        except OllamaUnavailable:
            suggestion = {}

        url = str(suggestion.get("url", "")).strip()
        confidence = float(suggestion.get("confidence", 0.0) or 0.0)
        if url and confidence >= 0.72:
            fallback_intent = {
                "intent": "open_app_web_fallback",
                "command": "browser_open",
                "parameters": {"url": url, "visible": True},
            }
            results = self.tools.execute(fallback_intent)
            if results and results[0].success:
                service = str(suggestion.get("service") or app_name).strip()
                message = f"{failed_result.message} I opened {service} on the web instead."
                return results, self._ensure_named_response(message)
            if results:
                return results, self._ensure_named_response(f"{failed_result.message} I also could not open the web fallback: {results[0].message}")

        query = f"{app_name} official website"
        fallback_intent = {
            "intent": "open_app_google_fallback",
            "command": "browser_search",
            "parameters": {"engine": "google", "query": query},
        }
        results = self.tools.execute(fallback_intent)
        if results and results[0].success:
            return results, self._ensure_named_response(f"{failed_result.message} I opened a Google search for {query}.")
        if results:
            return results, self._ensure_named_response(f"{failed_result.message} I tried a Google search too, but {results[0].message}")
        return [], self._ensure_named_response(failed_result.message)

    def _tool_summary(self, tool_results: List[ToolResult]) -> str:
        if not tool_results:
            return "No tools executed."
        parts: List[str] = []
        for result in tool_results:
            state = "succeeded" if result.success else "needs attention"
            parts.append(f"{result.tool_name} {state}: {result.message}")
        return " ".join(parts)

    def _ensure_named_response(self, text: str, context: str = "default") -> str:
        clean = " ".join(text.split())
        if clean.lower().startswith("friday:"):
            clean = clean.split(":", 1)[1].strip()
        clean = self.personality_engine.polish(clean, context=context)
        return self._apply_tone(clean, context=context)

    def _apply_tone(self, text: str, context: str = "default") -> str:
        clean = " ".join(text.split()).strip()
        if not clean:
            return clean
        tone = self.state.snapshot().tone
        lowered = clean.lower()
        if tone == "neutral":
            return self._apply_default_personality(clean, context)
        if tone == "formal":
            if lowered.startswith(("certainly.", "please note.")):
                return clean
            return f"Certainly, sir. {clean}"
        if tone == "professional":
            if lowered.startswith(("done.", "handled.", "action required.", "status:")):
                return clean
            if "confirm" in lowered or "requires confirmation" in lowered:
                return f"Action required, sir. {clean}"
            return f"Handled, boss. {clean}"
        if tone == "light-hearted":
            if lowered.startswith(("got it.", "all set.")):
                return clean
            if "confirm" in lowered or "requires confirmation" in lowered:
                return f"Got it, boss. {clean}"
            return f"All set, boss. {clean}"
        return self._apply_default_personality(clean, context)

    def _apply_default_personality(self, text: str, context: str) -> str:
        clean = " ".join(text.split()).strip()
        lowered = clean.lower()
        if not clean or self._already_personal(clean):
            return clean
        if "say confirm" in lowered or "confirm" in lowered or "requires confirmation" in lowered:
            return f"Just to confirm, sir - {clean}"
        if context == "question" or lowered.endswith("?"):
            return self.personality_engine.pick([f"One thing, sir: {clean}", f"Quick check, boss: {clean}", f"Need your call on this, sir: {clean}"])
        if context == "task_complete":
            return f"Done, boss. {clean}"
        if lowered.startswith(("i'm online", "i am online")):
            return self.personality_engine.pick([f"{clean} Ready when you are, boss.", f"{clean} Standing by, sir.", f"{clean} Systems are warm, boss."])
        if lowered.startswith(("opened", "closed", "searched", "browser task completed", "google classroom workflow completed")):
            return self.personality_engine.pick([f"Done, boss. {clean}", f"Handled, sir. {clean}", f"All set, boss. {clean}"])
        if lowered.startswith(("canceled", "anytime", "good night")):
            return clean
        return self._append_address(clean, "boss")

    def _already_personal(self, text: str) -> bool:
        lowered = text.lower()
        return bool(re.search(r"\b(sir|boss)\b", lowered))

    def _append_address(self, text: str, address: str) -> str:
        clean = text.strip()
        if clean.endswith("."):
            return f"{clean[:-1]}, {address}."
        if clean.endswith("!"):
            return f"{clean[:-1]}, {address}!"
        if clean.endswith("?"):
            return f"{clean[:-1]}, {address}?"
        return f"{clean}, {address}."
