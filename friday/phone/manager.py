"""Coordinator that turns a phone-call request into status events + a logged result.

Flow:

1. ``CallPlanner`` extracts a structured :class:`CallBrief` from the request.
2. If the driver is the Twilio one AND the caller hasn't confirmed yet, return
   a ``requires_confirmation=True`` envelope so the assistant surfaces a preview.
3. Otherwise spawn a daemon thread that calls ``driver.place_call``, registers
   the call in ``_active`` under a lock, and publishes events through ``EventBus``.
4. On completion, append a sanitised entry to ``logs/phone-calls.jsonl`` and
   keep the result in memory so ``last_summary`` / ``list_calls`` work.

The manager itself never blocks the request thread (the call runs in a daemon).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from friday.control.sensitive_text import redact_phone_number, redact_sensitive_text
from friday.events import EventBus
from friday.phone.call_planner import CallPlanner
from friday.phone.drivers import PhoneDriver, TwilioNotConfiguredError, TwilioPhoneDriver
from friday.schemas.phone_call import CallBrief, CallResult, CallStatus


@dataclass
class _ActiveCall:
    brief: CallBrief
    started_at: datetime
    result: Optional[CallResult] = None
    thread: Optional[threading.Thread] = None
    cancelled: bool = False


@dataclass
class CallSummaryRow:
    """Lightweight projection for ``list_calls`` UI output."""

    call_id: str
    recipient_name: str
    recipient_number_masked: str
    objective: str
    status: str
    started_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "recipient_name": self.recipient_name,
            "recipient_number": self.recipient_number_masked,
            "objective": self.objective,
            "status": self.status,
            "started_at": self.started_at,
        }


class PhoneCallManager:
    """Owns the lifecycle of every outbound call FRIDAY places."""

    def __init__(
        self,
        planner: CallPlanner,
        driver: PhoneDriver,
        events: EventBus,
        logger_path: Optional[Path] = None,
        max_concurrent: int = 5,
        thread_factory: Optional[Callable[..., threading.Thread]] = None,
    ) -> None:
        self.planner = planner
        self.driver = driver
        self.events = events
        self.logger_path = Path(logger_path) if logger_path else None
        self.max_concurrent = max(1, int(max_concurrent))
        self._thread_factory = thread_factory or self._default_thread_factory
        self._lock = threading.RLock()
        self._active: Dict[str, _ActiveCall] = {}
        self._history: List[CallResult] = []
        if self.logger_path is not None:
            self.logger_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def place_call(
        self,
        request: str,
        *,
        confirmed: bool = False,
        persona_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(request, str) or not request.strip():
            return self._failure("Tell me who to call and why, boss.", {})

        try:
            brief, confidence = self.planner.plan(request)
        except ValueError as exc:
            return self._failure(str(exc), {})

        if persona_override:
            # Frozen dataclass — rebuild with the override applied.
            brief = CallBrief.from_dict({**brief.to_dict(), "persona": persona_override.strip()})

        # Twilio path requires explicit confirmation per the user-chosen safety policy.
        if isinstance(self.driver, TwilioPhoneDriver) and not confirmed:
            masked = redact_phone_number(brief.recipient_number) if brief.recipient_number else "(no number)"
            preview = {
                "call_id": brief.call_id,
                "recipient_name": brief.recipient_name,
                "recipient_number_masked": masked,
                "objective": brief.objective,
                "talking_points": list(brief.talking_points),
                "max_minutes": brief.max_minutes,
                "persona": brief.persona,
                "driver": self.driver.name,
                "confidence": confidence,
            }
            return {
                "success": False,
                "requires_confirmation": True,
                "message": (
                    f"Ready to call {brief.recipient_name} at {masked} to {brief.objective}. "
                    "Say 'confirm' to actually dial. Recording/consent disclosure is your responsibility."
                ),
                "data": {"brief_preview": preview},
            }

        if not brief.recipient_number and isinstance(self.driver, TwilioPhoneDriver):
            return self._failure(
                f"I need a phone number to call {brief.recipient_name}, boss.",
                {"brief_preview": brief.to_dict(), "confidence": confidence},
            )

        with self._lock:
            if len(self._active) >= self.max_concurrent:
                return self._failure(
                    f"At capacity ({self.max_concurrent} active calls), boss. Wait for one to finish.",
                    {"active_count": len(self._active), "max_concurrent": self.max_concurrent},
                )
            active = _ActiveCall(brief=brief, started_at=datetime.now(timezone.utc))
            self._active[brief.call_id] = active

        self.events.publish(
            "phone_call_planned",
            {
                "call_id": brief.call_id,
                "recipient_name": brief.recipient_name,
                "recipient_number_masked": redact_phone_number(brief.recipient_number) if brief.recipient_number else "(no number)",
                "objective": brief.objective,
                "talking_points": list(brief.talking_points),
                "driver": self.driver.name,
                "confidence": confidence,
            },
        )

        thread = self._thread_factory(brief)
        active.thread = thread
        thread.start()

        return {
            "success": True,
            "requires_confirmation": False,
            "message": f"Placing the call to {brief.recipient_name}...",
            "data": {
                "call_id": brief.call_id,
                "driver": self.driver.name,
                "confidence": confidence,
                "brief_preview": {
                    "recipient_name": brief.recipient_name,
                    "objective": brief.objective,
                    "talking_points": list(brief.talking_points),
                    "max_minutes": brief.max_minutes,
                    "persona": brief.persona,
                },
            },
        }

    def cancel_call(self, call_id: str = "", recipient_hint: str = "") -> Dict[str, Any]:
        with self._lock:
            target = self._resolve_active(call_id, recipient_hint)
            if not target:
                return self._failure("I don't see an active call matching that, boss.", {})
            target.cancelled = True
        cancelled = self.driver.cancel(target.brief.call_id)
        if cancelled:
            self.events.publish(
                "phone_call_status",
                {"call_id": target.brief.call_id, "status": CallStatus.CANCELLED.value},
            )
            return {
                "success": True,
                "requires_confirmation": False,
                "message": f"Cancelling the call to {target.brief.recipient_name}.",
                "data": {"call_id": target.brief.call_id},
            }
        return self._failure(
            f"The {self.driver.name} driver could not cancel that call.",
            {"call_id": target.brief.call_id},
        )

    def list_calls(self) -> Dict[str, Any]:
        with self._lock:
            active_rows = [
                CallSummaryRow(
                    call_id=call_id,
                    recipient_name=active.brief.recipient_name,
                    recipient_number_masked=redact_phone_number(active.brief.recipient_number)
                    if active.brief.recipient_number
                    else "(no number)",
                    objective=active.brief.objective,
                    status=(active.result.status.value if active.result else CallStatus.TALKING.value),
                    started_at=active.started_at.isoformat(),
                )
                for call_id, active in self._active.items()
            ]
            recent = [
                CallSummaryRow(
                    call_id=result.call_id,
                    recipient_name="(history)",
                    recipient_number_masked="(history)",
                    objective="",
                    status=result.status.value if isinstance(result.status, CallStatus) else str(result.status),
                    started_at=result.started_at.isoformat(),
                )
                for result in self._history[-5:]
            ]
        if not active_rows and not recent:
            return {
                "success": True,
                "requires_confirmation": False,
                "message": "No active or recent calls, boss.",
                "data": {"active": [], "recent": []},
            }
        return {
            "success": True,
            "requires_confirmation": False,
            "message": f"{len(active_rows)} active, {len(recent)} recent.",
            "data": {
                "active": [row.to_dict() for row in active_rows],
                "recent": [row.to_dict() for row in recent],
            },
        }

    def summarize_last_call(self) -> Dict[str, Any]:
        with self._lock:
            if not self._history:
                return {
                    "success": False,
                    "requires_confirmation": False,
                    "message": "I haven't placed any calls yet, boss.",
                    "data": {},
                }
            last = self._history[-1]
        return {
            "success": True,
            "requires_confirmation": False,
            "message": last.summary or "Call completed (no summary).",
            "data": {
                "call_id": last.call_id,
                "status": last.status.value if isinstance(last.status, CallStatus) else str(last.status),
                "outcome": last.outcome,
                "follow_ups": list(last.follow_ups),
                "transcript": [turn.to_dict() for turn in last.transcript],
            },
        }

    def active_call_ids(self) -> List[str]:
        with self._lock:
            return list(self._active.keys())

    def history(self) -> List[CallResult]:
        with self._lock:
            return list(self._history)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_active(self, call_id: str, recipient_hint: str) -> Optional[_ActiveCall]:
        if call_id and call_id in self._active:
            return self._active[call_id]
        if recipient_hint:
            needle = recipient_hint.strip().lower()
            for active in self._active.values():
                if needle and needle in active.brief.recipient_name.lower():
                    return active
        # Fall back to the only active call when there's exactly one.
        if len(self._active) == 1:
            return next(iter(self._active.values()))
        return None

    def _default_thread_factory(self, brief: CallBrief) -> threading.Thread:
        return threading.Thread(
            target=self._run_call,
            args=(brief,),
            name=f"friday-phone-{brief.call_id}",
            daemon=True,
        )

    def _run_call(self, brief: CallBrief) -> None:
        try:
            self.events.publish(
                "phone_call_started",
                {"call_id": brief.call_id, "driver": self.driver.name},
            )
            try:
                result = self.driver.place_call(brief, on_event=self._publish_driver_event)
            except TwilioNotConfiguredError as exc:
                result = CallResult(
                    call_id=brief.call_id,
                    status=CallStatus.FAILED,
                    summary=str(exc),
                    outcome="twilio_not_configured",
                    error=str(exc),
                )
            except Exception as exc:  # noqa: BLE001 - we never want this thread to die silently
                result = CallResult(
                    call_id=brief.call_id,
                    status=CallStatus.FAILED,
                    summary=f"Phone driver crashed: {exc}",
                    outcome="driver_crashed",
                    error=str(exc),
                )

            self._finalise(brief, result)
        except Exception as exc:  # noqa: BLE001 - last-resort safety net for the daemon thread
            self.events.publish(
                "phone_call_failed",
                {"call_id": brief.call_id, "error": str(exc)},
            )

    def _publish_driver_event(self, kind: str, payload: Dict[str, Any]) -> None:
        # Whitelist the small set of event kinds the driver may emit so a buggy
        # driver can't flood the bus with arbitrary kinds.
        allowed = {"phone_call_status", "phone_call_turn"}
        if kind not in allowed:
            return
        self.events.publish(kind, dict(payload))

    def _finalise(self, brief: CallBrief, result: CallResult) -> None:
        with self._lock:
            active = self._active.pop(brief.call_id, None)
            self._history.append(result)
        if active and active.cancelled and result.status != CallStatus.CANCELLED:
            # Caller requested cancel after the driver had already finished.
            result = CallResult.from_dict({**result.to_dict(), "status": CallStatus.CANCELLED.value})

        sanitised = self._sanitise_for_log(brief, result)
        if self.logger_path is not None:
            try:
                with self.logger_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(sanitised, sort_keys=True) + "\n")
            except OSError:
                pass  # Log failure must not crash the daemon.

        kind = "phone_call_completed"
        if result.status == CallStatus.FAILED:
            kind = "phone_call_failed"
        elif result.status == CallStatus.CANCELLED:
            kind = "phone_call_status"

        self.events.publish(
            kind,
            {
                "call_id": result.call_id,
                "status": result.status.value if isinstance(result.status, CallStatus) else str(result.status),
                "summary": result.summary,
                "outcome": result.outcome,
                "follow_ups": list(result.follow_ups),
                "error": result.error,
            },
        )

    def _sanitise_for_log(self, brief: CallBrief, result: CallResult) -> Dict[str, Any]:
        masked_number = redact_phone_number(brief.recipient_number) if brief.recipient_number else ""
        sanitised_brief = {
            **brief.to_dict(),
            "recipient_number": masked_number,
            "source_command": redact_sensitive_text(brief.source_command),
            "objective": redact_sensitive_text(brief.objective),
            "talking_points": [redact_sensitive_text(point) for point in brief.talking_points],
            "success_criteria": [redact_sensitive_text(point) for point in brief.success_criteria],
        }
        sanitised_result = {
            **result.to_dict(),
            "summary": redact_sensitive_text(result.summary),
            "transcript": [
                {**turn.to_dict(), "text": redact_sensitive_text(turn.text)} for turn in result.transcript
            ],
            "follow_ups": [redact_sensitive_text(item) for item in result.follow_ups],
        }
        return {"brief": sanitised_brief, "result": sanitised_result}

    @staticmethod
    def _failure(message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}
