"""Driver layer for outbound phone calls.

Two implementations:

- :class:`SimulatedPhoneDriver` — uses Ollama to roleplay both sides of the call.
  No real telephony; produces a believable transcript + summary you can review
  before placing the real call. This is what runs by default.

- :class:`TwilioPhoneDriver` — scaffold for real telephony. Activates when
  ``FRIDAY_TWILIO_*`` env vars are set. v1 raises a clear "not yet implemented"
  error in the call result so the abstraction is honest about what works.

Both drivers stream status via an ``on_event`` callback so the manager can
publish progress to the EventBus without coupling the driver to the bus.
"""

from __future__ import annotations

import json
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from friday.ollama_engine import OllamaClient, OllamaUnavailable
from friday.schemas.phone_call import CallBrief, CallResult, CallStatus, CallTurn

try:
    from friday.model_manager import ModelManager
except ImportError:  # pragma: no cover
    ModelManager = None  # type: ignore[assignment]


EventCallback = Callable[[str, Dict[str, Any]], None]


# ----------------------------------------------------------------------
# Abstract driver
# ----------------------------------------------------------------------


class PhoneDriver(ABC):
    """Interface implemented by every concrete phone driver."""

    name: str = "unknown"

    @abstractmethod
    def place_call(self, brief: CallBrief, on_event: EventCallback) -> CallResult:
        """Place the call. Emit progress via ``on_event(event_kind, payload)``.

        Must always return a :class:`CallResult`, even on failure. Never raise
        for normal call failures — set ``status=FAILED`` and populate ``error``.
        """

    def cancel(self, call_id: str) -> bool:
        """Best-effort cancellation. Returns True if the driver acted on the request."""
        return False


# ----------------------------------------------------------------------
# Simulated driver — Ollama roleplay
# ----------------------------------------------------------------------


# Conservative cap to keep transcripts useful and avoid Ollama runaway loops.
_MAX_SIMULATED_TURNS = 12
# Pacing so the UI can render incremental events without overwhelming the bus.
_SIMULATED_TURN_DELAY = 0.0


class SimulatedPhoneDriver(PhoneDriver):
    """Roleplay a phone call locally using Ollama, emitting live status events."""

    name = "simulated"

    def __init__(
        self,
        ollama: OllamaClient,
        model_manager: "ModelManager | None" = None,
        turn_delay: float = _SIMULATED_TURN_DELAY,
        max_turns: int = _MAX_SIMULATED_TURNS,
        sleeper: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.ollama = ollama
        self.model_manager = model_manager
        self.turn_delay = max(0.0, float(turn_delay))
        self.max_turns = max(2, int(max_turns))
        self._sleep = sleeper or time.sleep
        self._cancelled: set[str] = set()
        self._cancel_lock = threading.Lock()

    # -- public ----------------------------------------------------------

    def place_call(self, brief: CallBrief, on_event: EventCallback) -> CallResult:
        started_at = _utcnow()
        turns: List[CallTurn] = []

        if self._is_cancelled(brief.call_id):
            return self._cancelled_result(brief, started_at)

        # Progress events: DIALING → RINGING → CONNECTED → TALKING
        for status in (CallStatus.DIALING, CallStatus.RINGING, CallStatus.CONNECTED):
            on_event("phone_call_status", {"call_id": brief.call_id, "status": status.value})
            if self.turn_delay:
                self._sleep(self.turn_delay)
            if self._is_cancelled(brief.call_id):
                return self._cancelled_result(brief, started_at, transcript=turns)

        on_event("phone_call_status", {"call_id": brief.call_id, "status": CallStatus.TALKING.value})

        # Opening line from FRIDAY — generated up front so the user sees motion fast.
        opening = self._generate_friday_opening(brief)
        turn = CallTurn(speaker="friday", text=opening)
        turns.append(turn)
        on_event("phone_call_turn", _turn_payload(brief.call_id, turn))

        recipient_persona = self._derive_recipient_persona(brief)

        # Roleplay loop: recipient → friday → recipient → friday ...
        for _ in range(self.max_turns - 1):
            if self._is_cancelled(brief.call_id):
                return self._cancelled_result(brief, started_at, transcript=turns)

            speaker = "recipient" if turns[-1].speaker == "friday" else "friday"
            try:
                text = self._next_line(speaker, brief, turns, recipient_persona)
            except OllamaUnavailable as exc:
                error_turn = CallTurn(
                    speaker="system",
                    text=f"Ollama became unavailable mid-call: {exc}",
                )
                turns.append(error_turn)
                on_event("phone_call_turn", _turn_payload(brief.call_id, error_turn))
                return self._build_result(
                    brief,
                    status=CallStatus.FAILED,
                    transcript=turns,
                    summary="The simulated call could not finish because Ollama disconnected.",
                    outcome="ollama_disconnected",
                    follow_ups=["Restart Ollama and retry."],
                    started_at=started_at,
                    error=str(exc),
                )

            if not text:
                # Model gave up — treat that as a natural end of conversation.
                break

            turn = CallTurn(speaker=speaker, text=text)
            turns.append(turn)
            on_event("phone_call_turn", _turn_payload(brief.call_id, turn))

            if self.turn_delay:
                self._sleep(self.turn_delay)

            if _looks_like_call_end(text):
                break

        # Generate summary / outcome / follow-ups
        summary_payload = self._generate_summary(brief, turns)
        ended_at = _utcnow()
        return self._build_result(
            brief,
            status=CallStatus.COMPLETED,
            transcript=turns,
            summary=summary_payload.get("summary") or "Simulated call completed.",
            outcome=summary_payload.get("outcome") or "completed",
            follow_ups=summary_payload.get("follow_ups") or [],
            started_at=started_at,
            ended_at=ended_at,
        )

    def cancel(self, call_id: str) -> bool:
        with self._cancel_lock:
            if not call_id:
                return False
            self._cancelled.add(call_id)
            return True

    # -- internals -------------------------------------------------------

    def _is_cancelled(self, call_id: str) -> bool:
        with self._cancel_lock:
            return call_id in self._cancelled

    def _select_model(self) -> "str | None":
        if not self.model_manager:
            return None
        try:
            chosen = self.model_manager.select_model_for_task("normal")
        except Exception:  # noqa: BLE001
            return None
        return chosen or None

    def _generate_friday_opening(self, brief: CallBrief) -> str:
        prompt = (
            "You are FRIDAY, the user's personal phone assistant, placing a call.\n"
            f"You are calling: {brief.recipient_name}.\n"
            f"Objective: {brief.objective}.\n"
            f"Persona: {brief.persona}.\n"
            "Write ONLY the opening line you would say once they pick up. "
            "One or two short sentences. Polite, identify yourself as the user's assistant, state the reason for the call.\n"
        )
        try:
            response = self.ollama.generate_text(prompt, model=self._select_model())
        except OllamaUnavailable:
            return f"Hi, I'm calling on behalf of my user about {brief.objective}."
        text = _clean_line(response.text)
        return text or f"Hi, I'm calling on behalf of my user about {brief.objective}."

    def _derive_recipient_persona(self, brief: CallBrief) -> str:
        name = brief.recipient_name.strip()
        if not name or name == "the recipient":
            return "a generic phone respondent"
        return f"a representative who works at or for {name}"

    def _next_line(
        self,
        speaker: str,
        brief: CallBrief,
        turns: List[CallTurn],
        recipient_persona: str,
    ) -> str:
        transcript_text = _render_transcript(turns)
        if speaker == "friday":
            role_block = (
                "You are FRIDAY, calling on behalf of the user.\n"
                f"Objective: {brief.objective}.\n"
                f"Talking points (mention each at least once if relevant): {', '.join(brief.talking_points) or '(none)'}.\n"
                f"Success criteria: {', '.join(brief.success_criteria) or '(none)'}.\n"
                f"Persona: {brief.persona}.\n"
            )
        else:
            role_block = (
                f"You are {recipient_persona}.\n"
                "Respond realistically to FRIDAY. You may ask clarifying questions, "
                "put the caller on hold, transfer them, or close the conversation when finished.\n"
            )
        prompt = (
            role_block
            + "\n--- transcript so far ---\n"
            + transcript_text
            + "\n--- end transcript ---\n"
            + f"Write ONLY the next thing {speaker.upper()} says. One or two short sentences. "
            "If the conversation has naturally reached its end, reply with exactly: <END>.\n"
        )
        try:
            response = self.ollama.generate_text(prompt, model=self._select_model())
        except OllamaUnavailable:
            raise
        text = _clean_line(response.text)
        if not text or text == "<END>":
            return ""
        return text

    def _generate_summary(self, brief: CallBrief, turns: List[CallTurn]) -> Dict[str, Any]:
        if not turns:
            return {"summary": "No conversation took place.", "outcome": "no_answer", "follow_ups": []}
        transcript_text = _render_transcript(turns)
        prompt = (
            "You are FRIDAY summarising a phone call you just placed for the user.\n"
            f"Objective: {brief.objective}.\n"
            f"Success criteria: {', '.join(brief.success_criteria) or '(none specified)'}.\n\n"
            "Return strict JSON only with this shape:\n"
            '{"summary":"one-paragraph plain-English recap",'
            '"outcome":"one of: success, partial, failure, callback_scheduled, no_answer, transferred",'
            '"follow_ups":["short action items if any"]}\n'
            "Do not invent facts that the transcript does not support.\n\n"
            "--- transcript ---\n"
            + transcript_text
            + "\n--- end transcript ---\n"
        )
        try:
            response = self.ollama.generate_json(prompt, model=self._select_model())
        except OllamaUnavailable:
            return {"summary": "Call completed; summary unavailable (Ollama disconnected).", "outcome": "completed", "follow_ups": []}
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            return {"summary": response.text[:600], "outcome": "completed", "follow_ups": []}
        if not isinstance(payload, dict):
            return {"summary": "Call completed.", "outcome": "completed", "follow_ups": []}
        return {
            "summary": _clean_line(str(payload.get("summary", ""))),
            "outcome": _clean_line(str(payload.get("outcome", "completed"))),
            "follow_ups": [str(item).strip() for item in (payload.get("follow_ups") or []) if str(item).strip()],
        }

    def _cancelled_result(
        self,
        brief: CallBrief,
        started_at: datetime,
        transcript: Optional[List[CallTurn]] = None,
    ) -> CallResult:
        return self._build_result(
            brief,
            status=CallStatus.CANCELLED,
            transcript=transcript or [],
            summary="Call cancelled before completion.",
            outcome="cancelled",
            follow_ups=[],
            started_at=started_at,
        )

    def _build_result(
        self,
        brief: CallBrief,
        *,
        status: CallStatus,
        transcript: List[CallTurn],
        summary: str,
        outcome: str,
        follow_ups: List[str],
        started_at: datetime,
        ended_at: Optional[datetime] = None,
        error: str = "",
    ) -> CallResult:
        return CallResult(
            call_id=brief.call_id,
            status=status,
            transcript=list(transcript),
            summary=summary,
            outcome=outcome,
            follow_ups=list(follow_ups),
            started_at=started_at,
            ended_at=ended_at or _utcnow(),
            error=error,
        )


# ----------------------------------------------------------------------
# Twilio driver — opt-in scaffold
# ----------------------------------------------------------------------


class TwilioNotConfiguredError(RuntimeError):
    """Raised when TwilioPhoneDriver is asked to act without credentials."""


class TwilioPhoneDriver(PhoneDriver):
    """Live telephony scaffold. Requires Twilio credentials to do anything real.

    v1 does NOT implement the streaming audio loop — it intentionally returns a
    FAILED ``CallResult`` so the user knows the abstraction exists but live
    calls aren't wired yet. Future versions will plug in Twilio Voice +
    bidirectional streaming STT/TTS without changing this method signature.
    """

    name = "twilio"

    def __init__(self, account_sid: str = "", auth_token: str = "", from_number: str = "") -> None:
        self.account_sid = account_sid.strip()
        self.auth_token = auth_token.strip()
        self.from_number = from_number.strip()

    @property
    def configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    def place_call(self, brief: CallBrief, on_event: EventCallback) -> CallResult:
        started_at = _utcnow()
        if not self.configured:
            raise TwilioNotConfiguredError(
                "Twilio is not configured. Set FRIDAY_TWILIO_ACCOUNT_SID, "
                "FRIDAY_TWILIO_AUTH_TOKEN, and FRIDAY_TWILIO_FROM_NUMBER."
            )
        if not brief.recipient_number:
            on_event(
                "phone_call_status",
                {"call_id": brief.call_id, "status": CallStatus.FAILED.value},
            )
            return CallResult(
                call_id=brief.call_id,
                status=CallStatus.FAILED,
                transcript=[CallTurn(speaker="system", text="No phone number supplied for the call.")],
                summary="Cannot dial without a phone number.",
                outcome="missing_number",
                follow_ups=["Provide a phone number and retry."],
                started_at=started_at,
                ended_at=_utcnow(),
                error="missing_recipient_number",
            )

        on_event("phone_call_status", {"call_id": brief.call_id, "status": CallStatus.DIALING.value})

        # TODO: wire Twilio Voice + bidirectional streaming STT/TTS here.
        # See plan file: friday/phone/drivers.py::TwilioPhoneDriver
        message = (
            "Live Twilio telephony is configured but not yet wired in this build. "
            "The simulator can be used to preview the call. "
            "Recording/consent disclosure remains the user's responsibility."
        )
        return CallResult(
            call_id=brief.call_id,
            status=CallStatus.FAILED,
            transcript=[CallTurn(speaker="system", text=message)],
            summary=message,
            outcome="not_implemented",
            follow_ups=["Use the simulator: omit live mode or unset the Twilio env vars."],
            started_at=started_at,
            ended_at=_utcnow(),
            error="twilio_live_loop_not_implemented",
        )

    def cancel(self, call_id: str) -> bool:
        return False


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


_END_PATTERNS = re.compile(
    r"\b(goodbye|good\s+bye|have\s+a\s+nice\s+day|take\s+care|thanks\s+(?:so\s+much|again|a\s+lot))\b",
    re.IGNORECASE,
)


def _looks_like_call_end(text: str) -> bool:
    return bool(_END_PATTERNS.search(text or ""))


def _clean_line(text: str) -> str:
    if not text:
        return ""
    clean = " ".join(str(text).split()).strip()
    # Strip leading speaker labels the model sometimes prefixes.
    clean = re.sub(r"^(?:FRIDAY|RECIPIENT|ASSISTANT|CALLER)\s*[:\-]\s*", "", clean, flags=re.IGNORECASE)
    # Strip surrounding quotes.
    if clean.startswith('"') and clean.endswith('"') and len(clean) >= 2:
        clean = clean[1:-1].strip()
    return clean


def _render_transcript(turns: List[CallTurn]) -> str:
    if not turns:
        return "(empty)"
    lines = []
    for turn in turns:
        speaker = turn.speaker.upper() if turn.speaker != "system" else "SYSTEM"
        lines.append(f"{speaker}: {turn.text}")
    return "\n".join(lines)


def _turn_payload(call_id: str, turn: CallTurn) -> Dict[str, Any]:
    return {"call_id": call_id, **turn.to_dict()}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
