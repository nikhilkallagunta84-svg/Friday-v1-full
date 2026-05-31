from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote_plus, urlparse

from friday.known_sites import PLAYABLE_SITE_ALIASES, SITE_SEARCH_ALIASES, WEBSITE_ALIASES
from friday.tools.app_control import APP_ALIASES


@dataclass(frozen=True)
class LocalIntent:
    intent: Dict[str, Any]
    final_output: str = ""


class LocalIntentResolver:
    def __init__(self, timezone: str = "") -> None:
        self._timezone = timezone
        self._installed_apps = self._scan_installed_apps()

    def resolve(self, cleaned_input: str) -> LocalIntent | None:
        text = " ".join(cleaned_input.lower().strip().split())
        if not text:
            return None
        if text in {"friday", "hey friday", "yo friday", "okay friday", "ok friday", "jarvis", "hey jarvis"}:
            return LocalIntent({"intent": "wake_greeting", "command": "none", "parameters": {}}, "Yes boss?")
        if self._is_time_request(text):
            return LocalIntent({"intent": "get_time", "command": "get_time", "parameters": {"timezone": self._timezone or "America/Chicago"}})
        if self._is_tts_on(text):
            return LocalIntent({"intent": "enable_tts", "command": "set_tts", "parameters": {"silent": False}})
        if self._is_tts_off(text):
            return LocalIntent({"intent": "disable_tts", "command": "set_tts", "parameters": {"silent": True}})
        if text in {"test tts", "test speech", "say something"}:
            return LocalIntent({"intent": "test_tts", "command": "test_tts", "parameters": {}})
        if self._is_task_history_request(text):
            return LocalIntent({"intent": "task_history_summary", "command": "task_history_summary", "parameters": {}})
        todo_intent = self._todo_intent(text)
        if todo_intent:
            return todo_intent
        maps_intent = self._maps_directions_intent(text)
        if maps_intent:
            return maps_intent
        close_intent = self._close_intent(text)
        if close_intent:
            return close_intent
        switch_tab_intent = self._switch_browser_tab_intent(text)
        if switch_tab_intent:
            return switch_tab_intent
        music_intent = self._music_play_intent(text)
        if music_intent:
            return music_intent
        code_intent = self._code_generate_intent(text)
        if code_intent:
            return code_intent
        phone_intent = self._phone_call_intent(text)
        if phone_intent:
            return phone_intent
        productivity_intent = self._productivity_draft_intent(text)
        if productivity_intent:
            return productivity_intent
        website_click_intent = self._website_click_intent(text)
        if website_click_intent:
            return website_click_intent
        compound_search_intent = self._compound_open_search_intent(text)
        if compound_search_intent:
            return compound_search_intent
        search_intent = self._search_intent(text)
        if search_intent:
            return search_intent
        screen_control_plan = self._screen_control_plan_intent(text)
        if screen_control_plan:
            return screen_control_plan
        browser_task = self._browser_task_intent(text)
        if browser_task:
            return browser_task
        screen_task = self._screen_task_intent(text)
        if screen_task:
            return screen_task
        open_intent = self._open_intent(text)
        if open_intent:
            return open_intent
        return None

    def _is_time_request(self, text: str) -> bool:
        if re.search(r"\btime\s+limit\b", text):
            return False
        return bool(re.search(r"\b(what'?s|what is|tell me|current|check|show)?\s*(the\s*)?(time|date)\b", text))

    def _is_tts_on(self, text: str) -> bool:
        return text in {"turn on tts", "enable tts", "unmute tts", "turn speech on", "enable speech", "voice on"} or "turn on speech" in text

    def _is_tts_off(self, text: str) -> bool:
        return text in {"turn off tts", "disable tts", "mute tts", "silent mode", "turn speech off", "disable speech"} or "turn off speech" in text

    def _is_task_history_request(self, text: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:friday\s+)?(?:what\s+did\s+you\s+just\s+do|what\s+did\s+you\s+do|what\s+happened|summarize\s+(?:the\s+)?last\s+task|show\s+(?:the\s+)?last\s+action)",
                text,
            )
        )

    def _todo_intent(self, text: str) -> LocalIntent | None:
        list_patterns = [
            r"^(?:show|open|check|read|list)\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list$",
            r"^(?:what'?s|what is|whats)\s+(?:on|in)\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list$",
            r"^(?:my\s+)?(?:to\s+do|todo)\s+list$",
        ]
        if any(re.match(pattern, text) for pattern in list_patterns):
            return LocalIntent({"intent": "todo_list", "command": "todo_list", "parameters": {}})

        clear_patterns = [
            (r"^(?:clear|empty|reset)\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list$", "active"),
            (r"^(?:clear|remove|delete)\s+all\s+(?:active\s+)?(?:tasks|todos|to\s+dos)(?:\s+from\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list)?$", "active"),
            (r"^(?:clear|remove|delete)\s+completed\s+(?:tasks|todos|to\s+dos)(?:\s+history)?$", "completed"),
            (r"^(?:clear|delete|reset)\s+all\s+(?:todo|to\s+do|task)\s+history$", "all"),
        ]
        for pattern, mode in clear_patterns:
            if re.match(pattern, text):
                return LocalIntent({"intent": "todo_clear", "command": "todo_clear", "parameters": {"mode": mode}})

        complete_patterns = [
            r"^(?:i'?m|i am|im)\s+(?:done|finished)\s+with\s+(.+?)(?:\s+(?:task|todo))?$",
            r"^(?:mark|set)\s+(.+?)\s+(?:as\s+)?(?:done|complete|completed|finished)$",
            r"^(?:complete|finish)\s+(.+?)\s+(?:task|todo)$",
            r"^(?:remove|delete|clear)\s+(.+?)\s+from\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list$",
            r"^(?:take|cross)\s+(.+?)\s+off\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list$",
        ]
        for pattern in complete_patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            task = self._clean_todo_task(match.group(1))
            if task:
                return LocalIntent({"intent": "todo_complete", "command": "todo_complete", "parameters": {"task": task}})

        add_patterns = [
            r"^(?:add|put|create)\s+(.+?)\s+(?:to|on|onto|in)\s+(?:my\s+|the\s+)?(?:to\s+do|todo|task)\s+list(?:\s+(.+))?$",
            r"^(?:add|create)\s+(?:a\s+|the\s+)?(?:task|todo)\s+(?:to\s+)?(.+)$",
            r"^(?:to\s+do|todo)\s+(?:add|create)\s+(.+)$",
            r"^(?:remind\s+me\s+to)\s+(.+)$",
        ]
        for pattern in add_patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            task = self._clean_todo_task(" ".join(group for group in match.groups() if group))
            if task:
                return LocalIntent({"intent": "todo_add", "command": "todo_add", "parameters": {"task": task}})
        return None

    def _clean_todo_task(self, value: str) -> str:
        clean = " ".join(value.strip(" .?!'\"").split())
        clean = re.sub(r"^(?:task|todo)\s+", "", clean)
        clean = re.sub(r"\s+(?:task|todo)$", "", clean)
        return clean.strip()

    def _maps_directions_intent(self, text: str) -> LocalIntent | None:
        clean_text = re.sub(r"\b(?:using|with|in|on)\s+apple\s+maps\b", "", text).strip()
        mode, without_mode = self._extract_transport_mode(clean_text)
        from_to_match = re.match(r"^(directions|route|distance|eta)\s+from\s+(.+?)\s+to\s+(.+)$", without_mode)
        if from_to_match:
            origin = self._clean_maps_destination(from_to_match.group(2))
            destination = self._clean_maps_destination(from_to_match.group(3))
            if origin and destination:
                return LocalIntent(
                    {
                        "intent": "maps_directions",
                        "command": "maps_directions",
                        "parameters": {
                            "destination": destination,
                            "origin": origin,
                            "transport_mode": mode,
                            "open_maps": from_to_match.group(1) in {"directions", "route"},
                        },
                    }
                )
        patterns = [
            (r"^(?:give me|show me|open|set|start|get)?\s*(?:(?:the|some)\s+)?directions\s+(?:to|for)\s+(.+)$", True),
            (r"^(?:navigate|route|map)\s+(?:me\s+)?(?:to|for)\s+(.+)$", True),
            (r"^(?:take me|bring me|get me)\s+to\s+(.+)$", True),
            (r"^(?:open|set|start)\s+apple\s+maps\s+(?:to|for)\s+(.+)$", True),
            (r"^(?:how far(?: away)? is|what'?s the distance to|what is the distance to)\s+(.+)$", False),
            (r"^(?:distance|eta)\s+(?:to|for)\s+(.+)$", False),
        ]
        for pattern, should_open in patterns:
            match = re.match(pattern, without_mode)
            if not match:
                continue
            destination = self._clean_maps_destination(match.group(1))
            if not destination:
                return None
            return LocalIntent(
                {
                    "intent": "maps_directions",
                    "command": "maps_directions",
                    "parameters": {
                        "destination": destination,
                        "transport_mode": mode,
                        "open_maps": should_open,
                    },
                }
            )
        return None

    def _extract_transport_mode(self, text: str) -> tuple[str, str]:
        clean = " ".join(text.strip().split())
        mode_patterns = [
            ("transit", r"\b(?:by|via|using|with)\s+(?:public\s+transit|transit|bus|train)\b", ""),
            ("walking", r"\b(?:by|via|using|with)\s+(?:walking|walk|foot)\b", ""),
            ("cycling", r"\b(?:by|via|using|with)\s+(?:cycling|biking|bike|bicycle)\b", ""),
            ("driving", r"\b(?:by|via|using|with)\s+(?:driving|drive|car)\b", ""),
            ("transit", r"\b(?:public\s+transit|transit|bus|train)\s+directions\b", "directions"),
            ("walking", r"\b(?:walking|walk)\s+directions\b", "directions"),
            ("cycling", r"\b(?:cycling|biking|bike)\s+directions\b", "directions"),
            ("driving", r"\b(?:driving|drive)\s+directions\b", "directions"),
        ]
        for mode, pattern, replacement in mode_patterns:
            if re.search(pattern, clean):
                return mode, " ".join(re.sub(pattern, replacement, clean).split())
        return "driving", clean

    def _clean_maps_destination(self, destination: str) -> str:
        clean = " ".join(destination.strip(" .?!'\"").split())
        clean = re.sub(r"^(?:to|for)\s+", "", clean).strip()
        clean = re.sub(r"\b(?:from|near)\s+my\s+(?:current\s+)?location$", "", clean).strip()
        return clean

    def _screen_control_plan_intent(self, text: str) -> LocalIntent | None:
        if "google classroom" in text or re.search(r"\b(classroom|assignment|classwork|turn\s+in|hand\s+in)\b", text):
            return None
        if re.fullmatch(r"(?:go\s+)?back|(?:open\s+)?new\s+tab", text):
            return self._screen_plan(text)
        if re.match(r"^(?:click|tap|press|lick|type|enter|write)\b", text):
            return self._screen_plan(text)
        if re.match(r"^(?:look\s+for|find|locate)\b.*\b(?:click|tap|press|lick)\b", text):
            return self._screen_plan(text)
        if re.match(r"^(?:send|email|message|text|dm|reply|submit|buy|purchase|checkout|pay)\b", text):
            return self._screen_plan(text)
        if re.search(r"\b(password|captcha|bypass|hide\s+activity|delete\s+files?|rm\s+-rf)\b", text):
            return self._screen_plan(text)

        search_match = re.match(r"^(?:search|find|look up)\s+(.+?)\s+for\s+(.+)$", text)
        if search_match:
            target = search_match.group(1).strip()
            if self._website_url(target) or self._direct_url(target) or target in {"spotify", "youtube", "chatgpt", "chat gpt"}:
                return self._screen_plan(text)

        complex_open = re.match(r"^(?:open|launch|start|pull up|go to)\s+(.+?)\s+and\s+(.+)$", text)
        if complex_open:
            target = complex_open.group(1).strip()
            continuation = complex_open.group(2).strip()
            if re.search(r"\b(search|find|look\s+up|play|click|tap|press|lick|type|go\s+back|new\s+tab|close\s+tab)\b", continuation):
                if self._website_url(target) or self._direct_url(target) or target in {"spotify", "youtube", "chatgpt", "chat gpt", "google docs"}:
                    return self._screen_plan(text)
            return None

        return None

    def _website_click_intent(self, text: str) -> LocalIntent | None:
        if not re.search(r"\b(click|tap|press|lick)\b", text):
            return None
        patterns = [
            (r"^(?:open|launch|start|pull up|go to)\s+(.+?)\s+and\s+(?:find\s+and\s+)?(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)$", "site_first"),
            (r"^(?:on|in|inside|within)\s+(.+?)\s+(?:find\s+and\s+)?(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)$", "site_first"),
            (r"^(?:find\s+and\s+)?(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)\s+(?:on|in|inside|within)\s+(.+)$", "target_first"),
            (r"^(?:look\s+for|find|locate)\s+(?:the\s+)?(.+?)\s+(?:on|in|inside|within)\s+(.+?)\s+and\s+(?:click|tap|press|lick)(?:\s+it)?$", "target_first"),
        ]
        for pattern, order in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            site = match.group(1) if order == "site_first" else match.group(2)
            site = site.strip()
            if self._website_url(site) or self._direct_url(site):
                return self._screen_plan(text)
        return None

    def _screen_plan(self, text: str) -> LocalIntent:
        return LocalIntent(
            {
                "intent": "screen_control_plan",
                "command": "screen_control_plan",
                "parameters": {"user_command": text},
            }
        )

    def _music_play_intent(self, text: str) -> LocalIntent | None:
        clean_text, browser = self._browser_hint(text)
        if browser:
            text = clean_text
        media_intent = self._site_media_play_intent(text)
        if media_intent:
            if browser:
                media_intent.intent.setdefault("parameters", {})["browser"] = browser
            return media_intent
        spotify = r"(?:spotify|spotufy|spotfy|spotifiy)"
        if re.fullmatch(rf"(?:open|launch|start|pull up)\s+{spotify}\s+and\s+(?:play|put on|start playing)", text) or re.fullmatch(
            rf"(?:play|put on|start playing)(?:\s+(?:on|in|through|using)\s+{spotify})?", text
        ):
            return LocalIntent(
                {
                    "intent": "ask_music_follow_up",
                    "command": "ask_follow_up",
                    "parameters": {"question": "What should I play on Spotify, sir?"},
                }
            )
        patterns = [
            rf"^(?:open|launch|start|pull up)\s+{spotify}\s+and\s+(?:play|put on|start playing)(?:\s+for\s+me)?\s+(.+)$",
            rf"^(?:play|put on|start playing)\s+(.+?)\s+(?:on|in|through|using)\s+{spotify}$",
            rf"^{spotify}\s+(?:play|put on|start playing)\s+(.+)$",
            r"^(?:play|put on|start playing)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            query = self._clean_music_query(match.group(1))
            if not query:
                return LocalIntent(
                    {
                        "intent": "ask_music_follow_up",
                        "command": "ask_follow_up",
                        "parameters": {"question": "What should I play on Spotify, sir?"},
                    }
                )
            intent = LocalIntent(
                {
                    "intent": "spotify_play",
                    "command": "music_play",
                    "parameters": {"service": "spotify", "query": query},
                }
            )
            if browser:
                intent.intent["parameters"]["browser"] = browser
            return intent
        return None

    def _site_media_play_intent(self, text: str) -> LocalIntent | None:
        playable_site = r"(?:spotify|spotufy|spotfy|spotifiy|youtube|you\s+tube|yt|soundcloud|sound\s+cloud|tiktok|tik\s+tok|twitch)"
        follow_up = re.fullmatch(
            rf"(?:open|launch|start|pull up|go to)\s+({playable_site})\s+and\s+(?:play|put on|start playing)",
            text,
        ) or re.fullmatch(rf"(?:play|put on|start playing)(?:\s+(?:on|in|through|using)\s+({playable_site}))?", text)
        if follow_up:
            service = self._normalize_playable_service((follow_up.group(1) or "spotify").replace("  ", " "))
            return LocalIntent(
                {
                    "intent": "ask_media_follow_up",
                    "command": "ask_follow_up",
                    "parameters": {"question": f"What should I play on {self._display_media_service(service)}, sir?"},
                }
            )

        patterns = [
            (rf"^(?:open|launch|start|pull up|go to)\s+({playable_site})\s+and\s+(?:play|put on|start playing)(?:\s+for\s+me)?\s+(.+)$", "site_first"),
            (rf"^(?:play|put on|start playing)\s+(.+?)\s+(?:on|in|through|using)\s+({playable_site})$", "query_first"),
            (rf"^({playable_site})\s+(?:play|put on|start playing)\s+(.+)$", "site_first"),
        ]
        for pattern, order in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            if order == "site_first":
                service = self._normalize_playable_service(match.group(1))
                query = self._clean_music_query(match.group(2))
            else:
                query = self._clean_music_query(match.group(1))
                service = self._normalize_playable_service(match.group(2))
            if not service:
                continue
            if not query:
                return LocalIntent(
                    {
                        "intent": "ask_media_follow_up",
                        "command": "ask_follow_up",
                        "parameters": {"question": f"What should I play on {self._display_media_service(service)}, sir?"},
                    }
                )
            return LocalIntent(
                {
                    "intent": "media_play",
                    "command": "music_play",
                    "parameters": {"service": service, "query": query},
                }
            )
        return None

    def _productivity_draft_intent(self, text: str) -> LocalIntent | None:
        document_intent = self._document_draft_intent(text)
        if document_intent:
            return document_intent
        return self._slides_draft_intent(text)

    def _code_generate_intent(self, text: str) -> LocalIntent | None:
        # Hard guard: don't hijack document/slide drafting requests.
        if re.search(r"\b(?:report|essay|document|paper|presentation|slide(?:s| deck)|writeup|write-up)\b", text):
            return None
        # Don't hijack screen/browser control requests that happen to mention 'script'.
        if re.search(r"\b(?:run|execute|launch|open)\s+(?:a\s+|the\s+)?(?:script|command|shell)\b", text):
            return None

        code_artifact = (
            r"(?:code|script|function|method|class|module|program|snippet|component|hook"
            r"|cli|util(?:ity)?|library|api|endpoint|regex|algorithm|implementation"
            r"|unit\s+test|test\s+case)"
        )
        language_token = (
            r"(?:python|py|javascript|js|typescript|ts|tsx|jsx|rust|go(?:lang)?|c\+\+|cpp|c#|csharp"
            r"|java|kotlin|swift|ruby|php|bash|shell|zsh|sql|html|css|react|vue|svelte|node(?:\.?js)?)"
        )
        verb = r"(?:write|generate|create|make|build|draft|produce|give\s+me)"

        patterns = [
            # "write a python function that ..." / "generate javascript code to ..."
            rf"^{verb}\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?(?:({language_token})\s+)?{code_artifact}\s+(?:that|to|for|which|named|called)\s+(.+)$",
            # "write code in python to ..." / "write code to ..."
            rf"^{verb}\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?{code_artifact}\s+(?:in|using|with)\s+({language_token})(?:\s+(?:that|to|for|which))?\s+(.+)$",
            # Bare "code <something>" / "code up <something>"
            rf"^code(?:\s+up)?\s+(?:a\s+|an\s+|the\s+|me\s+)?(?:({language_token})\s+)?(?:{code_artifact}\s+)?(?:that|to|for|which)?\s*(.+)$",
        ]

        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            groups = match.groups()
            language = ""
            description = ""
            # Walk groups: first language-like group, last non-empty is description.
            for group in groups:
                if not group:
                    continue
                if re.fullmatch(language_token, group, flags=re.IGNORECASE) and not language:
                    language = group.lower()
                else:
                    description = group
            description = self._clean_code_description(description or text)
            if not description:
                return LocalIntent(
                    {
                        "intent": "ask_code_topic",
                        "command": "ask_follow_up",
                        "parameters": {"question": "What should the code do, boss?"},
                    }
                )
            parameters: Dict[str, Any] = {"prompt": description}
            if language:
                parameters["language"] = language
            return LocalIntent(
                {
                    "intent": "generate_code",
                    "command": "generate_code",
                    "parameters": parameters,
                }
            )
        return None

    def _clean_code_description(self, value: str) -> str:
        clean = " ".join(value.strip().split())
        clean = re.sub(r"^(?:that|to|for|which)\s+", "", clean, flags=re.I).strip()
        clean = re.sub(r"\s+(?:for\s+me|please)$", "", clean, flags=re.I).strip()
        return clean.strip(" .'\"?!")

    def _phone_call_intent(self, text: str) -> LocalIntent | None:
        # Hard guards — bail before matching anything if the text looks like a
        # programming or callback idiom rather than a phone-call request.
        if re.search(r"\bcall\s+(?:this\s+|the\s+)?(?:function|method|api|endpoint|module|hook)\b", text):
            return None
        if re.search(r"\bcall\s+(?:it|this|that)\b", text):
            # "call it foo", "call this method bar" — renaming/reference, not telephony.
            return None
        if re.match(r"^call\s+me\s+(?:later|back|when|tonight|tomorrow|in\s+the\s+morning)\b", text):
            return None

        # Cancel patterns first — they're the most specific.
        cancel_match = re.match(
            r"^cancel\s+(?:the\s+)?(?:phone\s+)?call(?:\s+to\s+(.+?))?$",
            text,
        )
        if cancel_match:
            target = (cancel_match.group(1) or "").strip(" .,?!'\"")
            parameters: Dict[str, Any] = {}
            if target:
                parameters["recipient"] = target
            return LocalIntent(
                {"intent": "cancel_phone_call", "command": "cancel_call", "parameters": parameters}
            )

        # Status / list of active calls.
        if re.match(
            r"^(?:what'?s\s+(?:happening|going\s+on)|status|how'?s\s+(?:it\s+going)?|update)\s+(?:with\s+)?(?:the\s+|my\s+)?(?:phone\s+)?call(?:s)?$",
            text,
        ):
            return LocalIntent(
                {"intent": "list_phone_calls", "command": "list_calls", "parameters": {}}
            )

        # Summary of last call.
        if re.match(
            r"^(?:summari[sz]e|recap|recap\s+for\s+me|tell\s+me\s+about)\s+(?:the\s+)?(?:last|previous|most\s+recent)\s+(?:phone\s+)?call$",
            text,
        ):
            return LocalIntent(
                {"intent": "summarize_last_call", "command": "summarize_last_call", "parameters": {}}
            )

        # Place call — the meatiest pattern.
        place_match = re.match(
            r"^(?:hey\s+friday[,\s]+)?(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?"
            r"(?:call|phone|ring(?:\s+up)?|dial)\s+(.+)$",
            text,
        )
        if not place_match:
            return None
        # The full request goes to the planner; we don't try to split it here.
        request = text.strip()
        # Strip leading polite/wake prefixes so the planner sees a tighter request.
        request = re.sub(
            r"^(?:hey\s+friday[,\s]+|friday[,\s]+|please\s+|can\s+you\s+|could\s+you\s+)+",
            "",
            request,
            flags=re.IGNORECASE,
        ).strip()
        confirmed = bool(re.search(r"\b(?:confirm|confirmed|go\s+ahead|do\s+it|make\s+it\s+live)\b", text))
        parameters: Dict[str, Any] = {"request": request}
        if confirmed:
            parameters["confirmed"] = True
        return LocalIntent(
            {"intent": "place_phone_call", "command": "place_call", "parameters": parameters}
        )

    def _document_draft_intent(self, text: str) -> LocalIntent | None:
        docs = r"(?:google\s+docs?|docs?)"
        document_type = r"(?:report|essay|document|paper|writeup|write-up)"
        patterns = [
            rf"^(?:open|launch|start|pull up|go to)\s+{docs}\s+and\s+(?:write|draft|create|make)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?({document_type})(?:\s+(?:about|on|for)\s+(.+))?$",
            rf"^(?:write|draft|create|make)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?({document_type})\s+(?:about|on|for)\s+(.+?)\s+(?:in|on|using|with)\s+{docs}$",
            rf"^{docs}\s+(?:write|draft|create|make)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?({document_type})(?:\s+(?:about|on|for)\s+(.+))?$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            document_kind = self._clean_document_kind(match.group(1))
            topic = self._clean_productivity_topic(match.group(2) or "")
            if not topic:
                return LocalIntent(
                    {
                        "intent": "ask_document_topic",
                        "command": "ask_follow_up",
                        "parameters": {"question": f"What should the {document_kind} be about, sir?"},
                    }
                )
            return LocalIntent(
                {
                    "intent": "google_docs_draft",
                    "command": "draft_document",
                    "parameters": {"target": "google_docs", "document_type": document_kind, "prompt": topic},
                }
            )
        return None

    def _slides_draft_intent(self, text: str) -> LocalIntent | None:
        slide_target = r"(?:gamma|google\s+slides?|slides?)"
        slide_kind = r"(?:slides?|slide\s+deck|deck|presentation|slideshow)"
        patterns = [
            rf"^(?:open|launch|start|pull up|go to)\s+({slide_target})\s+and\s+(?:make|create|draft|build|generate)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?{slide_kind}(?:\s+(?:about|on|for|based\s+(?:off|on))\s+(.+))?$",
            rf"^(?:make|create|draft|build|generate)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?{slide_kind}\s+(?:about|on|for|based\s+(?:off|on))\s+(.+?)\s+(?:in|on|using|with)\s+({slide_target})$",
            rf"^({slide_target})\s+(?:make|create|draft|build|generate)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?{slide_kind}(?:\s+(?:about|on|for|based\s+(?:off|on))\s+(.+))?$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            groups = [group or "" for group in match.groups()]
            if re.match(rf"^{slide_target}$", groups[0]):
                target = groups[0]
                topic = groups[1] if len(groups) > 1 else ""
            else:
                topic = groups[0]
                target = groups[1] if len(groups) > 1 else "gamma"
            normalized_target = self._normalize_slide_target(target)
            topic = self._clean_productivity_topic(topic)
            if not topic:
                return LocalIntent(
                    {
                        "intent": "ask_slides_topic",
                        "command": "ask_follow_up",
                        "parameters": {"question": "What should the slides be about, sir?"},
                    }
                )
            return LocalIntent(
                {
                    "intent": "slides_draft",
                    "command": "draft_slides",
                    "parameters": {"target": normalized_target, "prompt": topic},
                }
            )
        return None

    def _search_intent(self, text: str) -> LocalIntent | None:
        prefixed_browser = re.match(r"^(?:in|on|using|with)\s+(google\s+chrome|chrome|safari|microsoft\s+edge|edge)\s+(?:search|look up|google)\s+(.+)$", text)
        if prefixed_browser:
            browser = prefixed_browser.group(1)
            text = f"search for {prefixed_browser.group(2).strip()}"
        else:
            embedded_browser = re.match(r"^(?:search|look up|google)\s+(?:in|on|using|with)\s+(google\s+chrome|chrome|safari|microsoft\s+edge|edge)\s+for\s+(.+)$", text)
            if embedded_browser:
                browser = embedded_browser.group(1)
                text = f"search for {embedded_browser.group(2).strip()}"
            else:
                text, browser = self._browser_hint(text)
        site_match = re.match(r"^search\s+(.+?)\s+for\s+(.+)$", text)
        if site_match:
            site = self._search_site_engine(site_match.group(1))
            query = site_match.group(2).strip()
            if site:
                parameters: Dict[str, Any] = {"engine": site, "query": query}
                if browser:
                    parameters["browser"] = browser
                return LocalIntent(
                    {
                        "intent": "browser_search",
                        "command": "browser_search",
                        "parameters": parameters,
                    }
                )

        leading_site_match = re.match(r"^(?:search|find|look up)\s+(?:in|on|inside|within)\s+(.+?)\s+(?:for|about)\s+(.+)$", text)
        if leading_site_match:
            site = self._search_site_engine(leading_site_match.group(1))
            query = leading_site_match.group(2).strip()
            if site and query:
                parameters = {"engine": site, "query": query}
                if browser:
                    parameters["browser"] = browser
                return LocalIntent({"intent": "browser_search", "command": "browser_search", "parameters": parameters})

        trailing_site_match = re.match(
            r"^(?:search|find|look up|google)\s+(?:for\s+)?(.+?)\s+(?:in|on|inside|within)\s+(.+)$",
            text,
        )
        if trailing_site_match:
            query = trailing_site_match.group(1).strip()
            site = self._search_site_engine(trailing_site_match.group(2))
            if site and query:
                parameters = {"engine": site, "query": query}
                if browser:
                    parameters["browser"] = browser
                return LocalIntent({"intent": "browser_search", "command": "browser_search", "parameters": parameters})

        patterns = [
            (r"^search for\s+(.+)$", "google"),
            (r"^(?:search|look up|google)\s+(.+)$", "google"),
            (r"^search google for\s+(.+)$", "google"),
            (r"^search youtube for\s+(.+)$", "youtube"),
            (r"^search reddit for\s+(.+)$", "reddit"),
        ]
        for pattern, engine in patterns:
            match = re.match(pattern, text)
            if match:
                query = match.group(1).strip()
                query = re.sub(r"^for\s+", "", query).strip()
                if query:
                    parameters: Dict[str, Any] = {"engine": engine, "query": query}
                    if browser:
                        parameters["browser"] = browser
                    return LocalIntent(
                        {"intent": "browser_search", "command": "browser_search", "parameters": parameters}
                    )
        return None

    def _compound_open_search_intent(self, text: str) -> LocalIntent | None:
        clean_text, browser = self._browser_hint(text)
        match = re.match(r"^(?:open|launch|start|pull up|go to)\s+(.+?)\s+and\s+(?:search|look\s+up|find)(?:\s+for)?\s+(.+)$", clean_text)
        if not match:
            return None
        site = " ".join(match.group(1).strip().split())
        query = match.group(2).strip()
        if not query:
            return None
        site = self._search_site_engine(site)
        if not site:
            return None
        parameters: Dict[str, Any] = {"engine": site, "query": query}
        if browser:
            parameters["browser"] = browser
        return LocalIntent({"intent": "browser_search", "command": "browser_search", "parameters": parameters})

    def _browser_task_intent(self, text: str) -> LocalIntent | None:
        classroom = self._classroom_task_intent(text)
        if classroom:
            return classroom
        complex_open = re.match(
            r"^(?:open|launch|start|pull up|go to)\s+(.+?)\s+and\s+(.+)$",
            text,
        )
        if complex_open and self._looks_like_browser_continuation(complex_open.group(2)):
            app_name = self._known_app(complex_open.group(1).strip())
            if app_name:
                actions = [{"action": "open_app", "app_name": app_name}, {"action": "wait", "seconds": 1.5}]
                actions.extend(self._screen_actions_from_task(complex_open.group(2).strip()))
                return LocalIntent({"intent": "screen_control", "command": "screen_control", "parameters": {"task": text, "actions": actions}})
            return LocalIntent({"intent": "browser_task", "command": "browser_task", "parameters": {"task": text, "visible": True}})
        patterns = [
            r"^(?:use|control|automate)\s+(?:the\s+)?browser\s+(?:to\s+)?(.+)$",
            r"^(?:browser|browser task)\s+(.+)$",
            r"^(?:in|on)\s+(?:the\s+)?browser\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                task = match.group(1).strip()
                if task:
                    return LocalIntent({"intent": "browser_task", "command": "browser_task", "parameters": {"task": task, "visible": True}})
        return None

    def _classroom_task_intent(self, text: str) -> LocalIntent | None:
        if re.match(r"^(?:open|launch|start|pull up|go to)\s+(?:google\s+)?classroom$", text):
            return LocalIntent(
                {"intent": "google_classroom_task", "command": "browser_task", "parameters": {"task": text, "visible": True, "workflow": "google_classroom"}}
            )
        if "google classroom" in text and re.search(r"\band\b.*\bassignment\b", text):
            return LocalIntent(
                {"intent": "google_classroom_task", "command": "browser_task", "parameters": {"task": text, "visible": True, "workflow": "google_classroom"}}
            )
        if re.match(r"^(?:turn\s+(?:it\s+)?in|submit(?:\s+it)?|hand\s+(?:it\s+)?in|mark\s+(?:it\s+)?as\s+done)\b", text):
            parameters: Dict[str, Any] = {"task": text, "visible": True, "workflow": "google_classroom"}
            class_match = re.search(r"\b(?:assignment|it)\s+(?:in|for)\s+(.+?)(?:\s+class)?$", text)
            assignment_match = re.search(r"^(?:turn\s+in|submit|hand\s+in|mark\s+as\s+done)\s+(.+?)\s+assignment\b", text)
            if class_match:
                parameters["class_name"] = class_match.group(1).strip()
            if assignment_match:
                assignment_name = assignment_match.group(1).strip()
                if assignment_name not in {"the", "my", "latest", "newest", "most recent"}:
                    parameters["assignment_name"] = assignment_name
            if re.search(r"\b(latest|newest|most recent)\b", text):
                parameters["latest"] = True
            return LocalIntent({"intent": "google_classroom_task", "command": "browser_task", "parameters": parameters})
        patterns = [
            r"^(?:organize|scan|index|sync)\s+(?:my\s+)?(?:google\s+)?classroom(?:\s+assignments?)?$",
            r"^(?:list|show|get)\s+(?:my\s+)?(?:google\s+)?classroom\s+(?:classes|assignments|classwork|to do|todo)$",
            r"^(?:list|show|get|organize)\s+(?:my\s+)?assignments(?:\s+(?:in|for)\s+(.+?)(?:\s+class)?)?$",
            r"^(?:open|start|work on|do|complete)\s+(?:the\s+)?(?:latest|newest|most recent)\s+assignment(?:\s+(?:in|for)\s+(.+?)(?:\s+class)?)?$",
            r"^(?:open|start|work on|do|complete)\s+(.+?)\s+assignment(?:\s+(?:in|for)\s+(.+?)(?:\s+class)?)?$",
            r"^(?:open|start|work on|do|complete)\s+(.+?)(?:\s+(?:in|for)\s+(.+?)\s+class)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            parameters: Dict[str, Any] = {"task": text, "visible": True, "workflow": "google_classroom"}
            groups = [group for group in match.groups() if group]
            if groups:
                if re.match(r"^(?:list|show|get|organize)\s+(?:my\s+)?assignments", text):
                    parameters["class_name"] = groups[0]
                elif re.match(r"^(?:open|start|work on|do|complete)\s+(?:the\s+)?(?:latest|newest|most recent)\s+assignment", text):
                    parameters["class_name"] = groups[0]
                elif re.match(r"^(?:open|start|work on|do|complete)\s+(.+?)\s+assignment", text) and len(groups) >= 1:
                    parameters["assignment_name"] = groups[0]
                    if len(groups) >= 2:
                        parameters["class_name"] = groups[1]
                elif re.match(r"^(?:open|start|work on|do|complete)\s+(.+?)(?:\s+(?:in|for)\s+(.+?)\s+class)$", text) and len(groups) >= 2:
                    parameters["assignment_name"] = groups[0]
                    parameters["class_name"] = groups[1]
                else:
                    parameters["class_name"] = groups[0]
            return LocalIntent({"intent": "google_classroom_task", "command": "browser_task", "parameters": parameters})
        if "google classroom" in text and re.search(r"\b(class|assignment|assignments|classwork|to do|todo|latest|organize|scan|index)\b", text):
            return LocalIntent(
                {"intent": "google_classroom_task", "command": "browser_task", "parameters": {"task": text, "visible": True, "workflow": "google_classroom"}}
            )
        return None

    def _looks_like_browser_continuation(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(click|fill|type|press|search|find|do|complete|answer|submit|turn\s+in|assignment|form|quiz|classroom|navigate)\b",
                text,
            )
        )

    def _screen_task_intent(self, text: str) -> LocalIntent | None:
        patterns = [
            r"^(?:use|control)\s+(?:my\s+)?screen\s+(?:to\s+)?(.+)$",
            r"^(?:screen control)\s+(.+)$",
            r"^((?:click|tap|double click|right click|type|paste|press|hit|scroll|move|drag|find|locate|select all|copy|new tab|close tab)\b.+)$",
            r"^((?:describe|read|analyze|look at)\s+(?:my\s+)?(?:screen|display|window|page).*)$",
            r"^((?:what'?s|what is)\s+on\s+(?:my\s+)?(?:screen|display).*)$",
            r"^((?:take\s+)?screenshot|screen shot|capture screen)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                task = match.group(1).strip()
                if task:
                    actions = self._screen_actions_from_task(task)
                    parameters: Dict[str, Any] = {"task": task}
                    if actions:
                        parameters["actions"] = actions
                    return LocalIntent({"intent": "screen_control", "command": "screen_control", "parameters": parameters})
        return None

    def _screen_actions_from_task(self, task: str) -> list[Dict[str, Any]]:
        if re.search(r"\b(describe|read|analyze|what'?s on|what is on|look at)\b.*\b(screen|display|window|page)\b", task):
            return [{"action": "analyze", "name": "vision-screen.png"}]
        if re.search(r"\b(position|where is the mouse|mouse position|cursor position)\b", task):
            return [{"action": "position"}]
        if re.search(r"\b(size|resolution|screen dimensions)\b", task):
            return [{"action": "size"}]
        if re.search(r"\b(screenshot|screen shot|capture screen)\b", task):
            return [{"action": "screenshot", "name": "friday-screen.png"}]
        if re.search(r"\bselect all\b", task):
            return [{"action": "hotkey", "keys": ["command", "a"]}]
        if re.fullmatch(r"copy", task.strip()):
            return [{"action": "hotkey", "keys": ["command", "c"]}]
        if re.fullmatch(r"(?:new tab|open new tab)", task.strip()):
            return [{"action": "hotkey", "keys": ["command", "t"]}]
        if re.fullmatch(r"close tab", task.strip()):
            return [{"action": "hotkey", "keys": ["command", "w"]}]
        actions: list[Dict[str, Any]] = []
        for part in re.split(r"\s+(?:and then|then|and)\s+", task):
            action = self._screen_action_from_phrase(part.strip())
            if action:
                actions.append(action)
        if actions:
            return actions
        return []

    def _screen_action_from_phrase(self, phrase: str) -> Dict[str, Any] | None:
        lowered = phrase.lower()
        coord = re.search(r"\b(?:at|to)?\s*(-?\d{1,5})\s*,\s*(-?\d{1,5})\b", lowered)
        coords: Dict[str, Any] = {}
        if coord:
            coords = {"x": int(coord.group(1)), "y": int(coord.group(2))}

        def target_after(pattern: str) -> str:
            target = re.sub(rf"^{pattern}", "", phrase, flags=re.I).strip()
            target = re.sub(r"\s+(?:button|field|link|menu|icon)$", "", target, flags=re.I).strip()
            return target.strip(" '\"")

        if lowered.startswith(("double click", "double-click")):
            target = target_after(r"double[-\s]?click(?:\s+(?:on|the))?")
            return {"action": "double_click", **(coords or {"target": target})}
        if lowered.startswith(("right click", "right-click")):
            target = target_after(r"right[-\s]?click(?:\s+(?:on|the))?")
            return {"action": "right_click", **(coords or {"target": target})}
        if lowered.startswith(("click", "tap")):
            target = target_after(r"(?:click|tap)(?:\s+(?:on|the))?")
            return {"action": "click", **(coords or {"target": target})}
        if lowered.startswith("move"):
            target = target_after(r"move(?:\s+(?:mouse|cursor))?(?:\s+(?:to|over|on))?")
            return {"action": "move", **(coords or {"target": target})}
        if lowered.startswith("type"):
            text = re.sub(r"^type\s+", "", phrase, flags=re.I).strip(" '\"")
            return {"action": "type", "text": text}
        if lowered.startswith("paste"):
            text = re.sub(r"^paste\s*", "", phrase, flags=re.I).strip(" '\"")
            return {"action": "paste_text", "text": text} if text else {"action": "hotkey", "keys": ["command", "v"]}
        if lowered.startswith(("press", "hit")):
            key = re.sub(r"^(?:press|hit)\s+", "", phrase, flags=re.I).strip()
            return {"action": "hotkey", "keys": key} if "+" in key or " " in key else {"action": "press", "key": key}
        if lowered.startswith("scroll"):
            return {"action": "scroll", "direction": "up" if "up" in lowered else "down"}
        if lowered.startswith(("find", "locate")):
            target = re.sub(r"^(?:find|locate)\s+", "", phrase, flags=re.I).strip(" '\"")
            return {"action": "find", "target": target}
        return None

    def _open_intent(self, text: str) -> LocalIntent | None:
        match = re.match(r"^(?:open|launch|start|pull up|go to)\s+(.+?)(?:\s+for me)?$", text)
        if not match:
            return None
        target = match.group(1).strip()
        target, browser = self._browser_hint(target)
        app_name = self._known_app(target)
        if app_name:
            return LocalIntent({"intent": "open_app", "command": "open_app", "parameters": {"app_name": app_name}})
        direct_url = self._direct_url(target)
        if direct_url:
            parameters: Dict[str, Any] = {"url": direct_url, "visible": True}
            if browser:
                parameters["browser"] = browser
            return LocalIntent({"intent": "open_website", "command": "browser_open", "parameters": parameters})
        website_url = self._website_url(target)
        if website_url:
            parameters = {"url": website_url, "visible": True}
            if browser:
                parameters["browser"] = browser
            return LocalIntent({"intent": "open_website", "command": "browser_open", "parameters": parameters})
        query = self._unknown_open_search_query(target)
        if query:
            parameters = {"engine": "google", "query": query, "reason": "No installed app, major website, or direct URL matched."}
            if browser:
                parameters["browser"] = browser
            return LocalIntent(
                {
                    "intent": "open_target_web_search",
                    "command": "browser_search",
                    "parameters": parameters,
                }
            )
        return None

    def _close_intent(self, text: str) -> LocalIntent | None:
        match = re.match(r"^(?:close|quit|exit|stop)\s+(.+?)(?:\s+for me)?$", text)
        if not match:
            return None
        target = match.group(1).strip()
        target, browser = self._browser_hint(target)
        close_tab_intent = self._close_browser_tab_intent(target)
        if close_tab_intent:
            if browser:
                close_tab_intent.intent.setdefault("parameters", {})["browser"] = browser
            return close_tab_intent
        app_name = self._known_app(target)
        if app_name:
            return LocalIntent({"intent": "close_app", "command": "close_app", "parameters": {"app_name": app_name}})
        tab_target = self._clean_browser_tab_target(target)
        direct_url = self._direct_url(tab_target)
        website_url = self._website_url(tab_target)
        if direct_url or website_url:
            parameters: Dict[str, Any] = {"target": tab_target, "url": direct_url or website_url}
            if browser:
                parameters["browser"] = browser
            return LocalIntent(
                {
                    "intent": "close_browser_tab",
                    "command": "browser_close_tab",
                    "parameters": parameters,
                }
            )
        return None

    def _switch_browser_tab_intent(self, text: str) -> LocalIntent | None:
        patterns = [
            r"^(?:switch|swap|change|jump)\s+(?:over\s+)?to\s+(.+?)(?:\s+for me)?$",
            r"^(?:switch|swap|change)\s+tabs?\s+(?:to|over\s+to)\s+(.+?)(?:\s+for me)?$",
            r"^(?:focus|show|bring up|pull up)\s+(.+?)\s+tab(?:\s+for me)?$",
            r"^(?:go to)\s+(.+?)\s+tab(?:\s+for me)?$",
        ]
        target = ""
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                target = match.group(1).strip()
                break
        if not target:
            return None

        clean = " ".join(target.lower().strip().split())
        browser = ""
        browser_match = re.search(r"\b(?:in|from|on)\s+(google\s+chrome|chrome|safari|microsoft\s+edge|edge)$", clean)
        if browser_match:
            browser = browser_match.group(1)
            clean = clean[: browser_match.start()].strip()

        explicit_tab = bool(re.search(r"\b(?:tab|browser\s+tab)\b", clean)) or "tabs " in text
        tab_target = self._clean_browser_tab_target(clean)
        direct_url = self._direct_url(tab_target)
        website_url = self._website_url(tab_target)
        if not explicit_tab and not direct_url and not website_url:
            return None

        parameters: Dict[str, Any] = {"target": tab_target}
        if browser:
            parameters["browser"] = browser
        if direct_url or website_url:
            parameters["url"] = direct_url or website_url
        return LocalIntent({"intent": "switch_browser_tab", "command": "browser_switch_tab", "parameters": parameters})

    def _close_browser_tab_intent(self, target: str) -> LocalIntent | None:
        clean = " ".join(target.lower().strip().split())
        browser = ""
        browser_match = re.search(r"\b(?:in|from|on)\s+(google\s+chrome|chrome|safari|microsoft\s+edge|edge)$", clean)
        if browser_match:
            browser = browser_match.group(1)
            clean = clean[: browser_match.start()].strip()
        close_all = False
        all_match = re.match(r"^(?:all|every)\s+(.+)$", clean)
        if all_match:
            close_all = True
            clean = all_match.group(1).strip()
        current = bool(
            re.fullmatch(r"(?:the\s+)?(?:current|active|this)?\s*(?:browser\s+)?tab", clean)
            or clean in {"current", "active", "this"}
        )
        explicit_tab = current or bool(re.search(r"\b(?:tabs?|browser\s+tabs?)\b", clean))
        if not explicit_tab:
            return None
        tab_target = self._clean_browser_tab_target(clean)
        parameters: Dict[str, Any] = {"target": tab_target, "current": current, "all": close_all}
        if browser:
            parameters["browser"] = browser
        if not current:
            direct_url = self._direct_url(tab_target)
            website_url = self._website_url(tab_target)
            if direct_url or website_url:
                parameters["url"] = direct_url or website_url
            if not tab_target and not parameters.get("url"):
                return None
        return LocalIntent({"intent": "close_browser_tab", "command": "browser_close_tab", "parameters": parameters})

    def _known_app(self, target: str) -> str:
        clean = " ".join(target.lower().split())
        if clean in APP_ALIASES:
            return clean
        for alias in sorted(APP_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", clean):
                return alias
        return self._installed_app_name(target)

    def _installed_app_name(self, target: str) -> str:
        clean = self._clean_unknown_app_target(target)
        normalized = self._normalize_app_lookup(clean)
        if not normalized:
            return ""
        compact = normalized.replace(" ", "")
        return self._installed_apps.get(normalized, "") or self._installed_apps.get(compact, "")

    def _scan_installed_apps(self) -> Dict[str, str]:
        apps: Dict[str, str] = {}
        roots = [Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications"]
        for root in roots:
            if not root.exists():
                continue
            for pattern in ("*.app", "*/*.app"):
                for path in root.glob(pattern):
                    name = path.stem.strip()
                    normalized = self._normalize_app_lookup(name)
                    if not normalized:
                        continue
                    apps.setdefault(normalized, name)
                    apps.setdefault(normalized.replace(" ", ""), name)
                    versionless = re.sub(r"\s+\d+(?:\s+\d+)*$", "", normalized).strip()
                    if versionless and versionless != normalized:
                        apps.setdefault(versionless, name)
                        apps.setdefault(versionless.replace(" ", ""), name)
        return apps

    def _normalize_app_lookup(self, value: str) -> str:
        clean = " ".join(value.lower().strip().split())
        clean = re.sub(r"\.app$", "", clean)
        clean = clean.replace("&", " and ")
        clean = re.sub(r"[^a-z0-9]+", " ", clean)
        return " ".join(clean.split())

    def _clean_unknown_app_target(self, target: str) -> str:
        clean = " ".join(target.lower().strip().split())
        clean = re.sub(r"^(?:a|an|the)\s+", "", clean)
        clean = re.sub(r"^(?:fake\s+)?(?:app|application|program|service)\s+(?:named|called)\s+", "", clean)
        clean = re.sub(r"^(?:app|application|program|service)\s+", "", clean)
        clean = clean.strip(" .")
        blocked = {"website", "web", "page", "tab", "browser", "settings", "status"}
        if not clean or clean in blocked:
            return ""
        return clean

    def _website_url(self, target: str) -> str:
        clean = " ".join(target.lower().strip().split())
        clean = re.sub(r"^(?:a|an|the)\s+", "", clean)
        clean = re.sub(r"\s+(?:official\s+)?(?:website|web site|site|web|page|homepage|home page)$", "", clean)
        clean = re.sub(r"^(?:official\s+)?(?:website|web site|site|web|page)\s+(?:for|of)\s+", "", clean)
        clean = clean.strip(" .")
        if clean in WEBSITE_ALIASES:
            return WEBSITE_ALIASES[clean]
        for alias in sorted(WEBSITE_ALIASES, key=len, reverse=True):
            if len(alias) > 2 and re.search(rf"\b{re.escape(alias)}\b", clean):
                return WEBSITE_ALIASES[alias]
        return ""

    def _search_site_engine(self, target: str) -> str:
        clean = " ".join(target.lower().strip().split())
        clean = re.sub(r"^(?:a|an|the)\s+", "", clean)
        clean = re.sub(r"\s+(?:official\s+)?(?:website|web site|site|web|page|homepage|home page)$", "", clean)
        clean = re.sub(r"^(?:official\s+)?(?:website|web site|site|web|page)\s+(?:for|of)\s+", "", clean)
        clean = clean.strip(" .")
        if not clean:
            return ""
        browser_names = {"google chrome", "chrome", "safari", "microsoft edge", "edge"}
        if clean in browser_names:
            return ""
        clean = SITE_SEARCH_ALIASES.get(clean, clean)
        direct_url = self._direct_url(clean)
        if direct_url:
            parsed = urlparse(direct_url)
            host = parsed.netloc.lower()
            return host[4:] if host.startswith("www.") else host
        if clean in WEBSITE_ALIASES:
            return SITE_SEARCH_ALIASES.get(clean, clean)
        for alias in sorted(WEBSITE_ALIASES, key=len, reverse=True):
            if len(alias) > 2 and re.search(rf"\b{re.escape(alias)}\b", clean):
                return SITE_SEARCH_ALIASES.get(alias, alias)
        return ""

    def _direct_url(self, target: str) -> str:
        clean = target.strip().strip(" .")
        if not clean:
            return ""
        lowered = clean.lower()
        if lowered.startswith(("http://", "https://")):
            return clean
        if " " in clean:
            return ""
        if re.match(r"^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\:\d+)?(?:/[^\s]*)?$", lowered):
            return f"https://{clean}"
        return ""

    def _clean_browser_tab_target(self, target: str) -> str:
        clean = " ".join(target.lower().strip().split())
        clean = re.sub(r"^(?:a|an|the)\s+", "", clean)
        clean = re.sub(r"\b(?:browser\s+)?tabs?\b", " ", clean)
        clean = re.sub(r"\b(?:website|web site|site|web|page)\b", " ", clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip(" .")

    def _browser_hint(self, text: str) -> tuple[str, str]:
        clean = " ".join(text.strip().split())
        match = re.search(r"\b(?:in|from|on|using|with)\s+(google\s+chrome|chrome|safari|microsoft\s+edge|edge)$", clean, flags=re.I)
        if not match:
            return clean, ""
        browser = match.group(1).lower()
        target = clean[: match.start()].strip(" ,.")
        return target, browser

    def _unknown_open_search_query(self, target: str) -> str:
        clean = self._clean_unknown_app_target(target)
        if not clean:
            return ""
        return f"{clean} official website"

    def _clean_music_query(self, value: str) -> str:
        clean = " ".join(value.strip().split())
        clean = re.sub(r"\s+(?:for\s+me|please)$", "", clean, flags=re.I).strip()
        clean = re.sub(r"^(?:the\s+song\s+|song\s+|track\s+)", "", clean, flags=re.I).strip()
        return clean.strip(" .'\"")

    def _normalize_playable_service(self, value: str) -> str:
        clean = " ".join(value.lower().strip().split())
        return PLAYABLE_SITE_ALIASES.get(clean, "")

    def _display_media_service(self, service: str) -> str:
        return {
            "spotify": "Spotify",
            "youtube": "YouTube",
            "soundcloud": "SoundCloud",
            "tiktok": "TikTok",
            "twitch": "Twitch",
        }.get(service, service.title())

    def _clean_productivity_topic(self, value: str) -> str:
        clean = " ".join(value.strip().split())
        clean = re.sub(r"\s+(?:for\s+me|please)$", "", clean, flags=re.I).strip()
        return clean.strip(" .'\"")

    def _clean_document_kind(self, value: str) -> str:
        clean = " ".join(value.lower().strip().split())
        if clean in {"writeup", "write-up", "paper", "essay"}:
            return clean
        if clean in {"document"}:
            return "report"
        return clean or "report"

    def _normalize_slide_target(self, value: str) -> str:
        clean = " ".join(value.lower().strip().split())
        if "google" in clean or clean == "slides":
            return "google_slides"
        return "gamma"


def search_url(engine: str, query: str) -> str:
    engine = SITE_SEARCH_ALIASES.get(" ".join(engine.lower().strip().split()), engine.lower().strip())
    encoded = quote_plus(query)
    if engine == "youtube":
        return f"https://www.youtube.com/results?search_query={encoded}"
    if engine == "reddit":
        return f"https://www.reddit.com/search/?q={encoded}"
    if engine == "instagram":
        return f"https://www.instagram.com/explore/search/keyword/?q={encoded}"
    if engine == "spotify":
        return f"https://open.spotify.com/search/{encoded}"
    if engine == "github":
        return f"https://github.com/search?q={encoded}"
    if engine == "amazon":
        return f"https://www.amazon.com/s?k={encoded}"
    if engine == "khan academy":
        return f"https://www.khanacademy.org/search?page_search_query={encoded}"
    if engine == "tiktok":
        return f"https://www.tiktok.com/search?q={encoded}"
    if engine == "wikipedia":
        return f"https://www.wikipedia.org/search-redirect.php?search={encoded}"
    return f"https://www.google.com/search?q={encoded}"
