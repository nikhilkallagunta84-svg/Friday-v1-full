from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    name: str
    expertise: str
    response_style: str

    def prompt_context(self) -> str:
        return (
            f"{self.name}: act like an expert with 20 years of experience in {self.expertise}. "
            f"Style: {self.response_style}"
        )


@dataclass(frozen=True)
class AgentSelection:
    agent_id: str
    name: str
    confidence: float
    reason: str
    prompt_context: str

    def metadata(self) -> Dict[str, object]:
        return {
            "id": self.agent_id,
            "name": self.name,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
        }


class MultiAgentOrchestrator:
    def __init__(self) -> None:
        self.profiles: Dict[str, AgentProfile] = {
            "coding": AgentProfile(
                "coding",
                "Coding Agent",
                "software engineering, debugging, architecture, code review, and production implementation",
                "be precise, practical, test-minded, and explain code decisions clearly",
            ),
            "math": AgentProfile(
                "math",
                "Math Agent",
                "mathematics, statistics, quantitative reasoning, and step-by-step tutoring",
                "show the cleanest reasoning path, verify arithmetic, and avoid skipping important steps",
            ),
            "conversational": AgentProfile(
                "conversational",
                "Conversational Agent",
                "natural conversation, emotional nuance, concise explanations, and tone control",
                "sound warm, respectful, and human without becoming verbose",
            ),
            "information": AgentProfile(
                "information",
                "Information Agent",
                "research, current events, source synthesis, comparison, and fact checking",
                "separate verified facts from uncertainty and prefer current web context when freshness matters",
            ),
            "automation": AgentProfile(
                "automation",
                "Automation Agent",
                "browser control, app control, file actions, workflow automation, and safe tool execution",
                "choose concrete actions, preserve safety boundaries, and ask only when a risky action needs confirmation",
            ),
            "study": AgentProfile(
                "study",
                "Study Coach Agent",
                "learning strategy, homework support, study guides, flashcards, school planning, and concept coaching",
                "teach clearly, guide without doing dishonest submission, and make work easier to understand",
            ),
        }

    def select(self, text: str) -> AgentSelection:
        clean = " ".join(text.lower().strip().split())
        if not clean:
            return self._selection("conversational", 0.5, "empty prompt fallback")
        scores = {
            "automation": self._score(clean, AUTOMATION_PATTERNS),
            "coding": self._score(clean, CODING_PATTERNS),
            "math": self._score(clean, MATH_PATTERNS),
            "information": self._score(clean, INFORMATION_PATTERNS),
            "study": self._score(clean, STUDY_PATTERNS),
            "conversational": self._score(clean, CONVERSATIONAL_PATTERNS),
        }
        if self._looks_like_math_expression(clean):
            scores["math"] += 5
        if self._has_action_keyword(clean):
            scores["automation"] += 3
        if self._has_current_info_keyword(clean):
            scores["information"] += 4
        if scores["conversational"] == 0:
            scores["conversational"] = 1
        agent_id, score = max(scores.items(), key=lambda item: (item[1], self._priority(item[0])))
        total = sum(scores.values()) or 1
        confidence = min(0.98, max(0.52, score / total + 0.35))
        reason = self._reason(agent_id, clean)
        return self._selection(agent_id, confidence, reason)

    def _selection(self, agent_id: str, confidence: float, reason: str) -> AgentSelection:
        profile = self.profiles[agent_id]
        return AgentSelection(
            agent_id=profile.agent_id,
            name=profile.name,
            confidence=confidence,
            reason=reason,
            prompt_context=profile.prompt_context(),
        )

    def _score(self, text: str, patterns: Iterable[str]) -> int:
        return sum(1 for pattern in patterns if re.search(pattern, text))

    def _priority(self, agent_id: str) -> int:
        return {
            "automation": 6,
            "coding": 5,
            "math": 4,
            "information": 3,
            "study": 2,
            "conversational": 1,
        }[agent_id]

    def _reason(self, agent_id: str, text: str) -> str:
        if agent_id == "automation":
            return "tool or control language was detected"
        if agent_id == "coding":
            return "software or debugging language was detected"
        if agent_id == "math":
            return "math or quantitative reasoning language was detected"
        if agent_id == "information":
            return "research or current-information language was detected"
        if agent_id == "study":
            return "school, learning, or study-support language was detected"
        return "general conversation was the best match"

    def _looks_like_math_expression(self, text: str) -> bool:
        return bool(re.search(r"\d+\s*(?:[+\-*/^=]|percent|%|divided by|times|x)\s*\d+", text))

    def _has_action_keyword(self, text: str) -> bool:
        return bool(re.search(r"^(?:can you\s+|could you\s+|please\s+|friday\s+)?(?:open|launch|start|close|switch|search|google|look up|click|type|press|scroll|run|append|move|rename|delete|send|draft|control|automate)\b", text))

    def _has_current_info_keyword(self, text: str) -> bool:
        if re.search(r"^(?:how are you|how'?s it going|what'?s up|thanks|thank you)\b", text):
            return False
        return bool(re.search(r"\b(latest|recent|today|current|right now|news|weather|score|schedule|price|stock|this week|this month|who is the)\b", text))


AUTOMATION_PATTERNS = [
    r"^(?:can you\s+|could you\s+|would you\s+|please\s+|friday\s+)?(?:open|launch|start|close|quit|switch|search|google|look up)\b",
    r"\b(?:browser|screen|window)\s+(?:control|task|automation)\b",
    r"\b(click|type|press|scroll|paste|copy|select|fill|submit)\b",
    r"\b(file|folder|terminal|command|install|server|send|draft)\b",
]

CODING_PATTERNS = [
    r"\b(code|coding|program|script|function|class|method|variable|api|endpoint)\b",
    r"\b(python|javascript|typescript|react|node|npm|pip|html|css|swift|java|sql)\b",
    r"\b(debug|bug|error|exception|stack trace|test|refactor|repo|component|database)\b",
]

MATH_PATTERNS = [
    r"\b(solve|calculate|compute|equation|algebra|geometry|calculus|derivative|integral)\b",
    r"\b(probability|statistics|mean|median|variance|percentage|ratio|slope|matrix)\b",
    r"\b(math|quadratic|linear|graph|proof|theorem)\b",
]

INFORMATION_PATTERNS = [
    r"\b(latest|recent|today|current|right now|news|weather|score|schedule|price|stock)\b",
    r"\b(research|compare|fact check|source|summarize article|what happened)\b",
    r"\b(who is|what is|where is|when did)\b",
]

STUDY_PATTERNS = [
    r"\b(homework|assignment|class|school|teacher|quiz|test|exam|study guide)\b",
    r"\b(flashcards|notes|ap classroom|google classroom|essay|rubric|worksheet)\b",
    r"\b(help me study|explain this concept|practice problems)\b",
]

CONVERSATIONAL_PATTERNS = [
    r"\b(hello|hi|hey|thanks|thank you|how are you|what do you think)\b",
    r"\b(advice|idea|brainstorm|plan|opinion|chat|talk)\b",
    r"\b(explain|tell me|why|how)\b",
]
