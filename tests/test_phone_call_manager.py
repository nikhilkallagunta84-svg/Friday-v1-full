from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from friday.events import EventBus
from friday.phone.drivers import PhoneDriver, TwilioPhoneDriver
from friday.phone.manager import PhoneCallManager
from friday.schemas.phone_call import CallBrief, CallResult, CallStatus, CallTurn


def _make_brief(call_id: str = "call-1", number: str = "+15551234567") -> CallBrief:
    return CallBrief(
        call_id=call_id,
        recipient_name="United",
        recipient_number=number,
        objective="ask about refund",
        talking_points=["booking ABC123"],
        success_criteria=["got refund"],
        source_command="call united",
    )


class _StubPlanner:
    def __init__(self, brief: CallBrief, confidence: float = 0.9) -> None:
        self.brief = brief
        self.confidence = confidence
        self.calls: list[str] = []

    def plan(self, request: str):
        self.calls.append(request)
        return self.brief, self.confidence


class _SyncDriver(PhoneDriver):
    """A driver that completes synchronously and records calls."""

    name = "stub"

    def __init__(self, result: CallResult) -> None:
        self.result = result
        self.placed: list[CallBrief] = []
        self.cancelled: list[str] = []

    def place_call(self, brief, on_event):  # noqa: D401
        self.placed.append(brief)
        on_event("phone_call_status", {"call_id": brief.call_id, "status": "talking"})
        return self.result

    def cancel(self, call_id):
        self.cancelled.append(call_id)
        return True


def _make_result(call_id: str, status: CallStatus = CallStatus.COMPLETED) -> CallResult:
    return CallResult(
        call_id=call_id,
        status=status,
        transcript=[CallTurn(speaker="friday", text="Hi, calling about refund.")],
        summary="Quick refund call",
        outcome="success",
        follow_ups=["Watch for email"],
    )


def _make_manager_synchronous(
    planner,
    driver,
    events,
    logger_path=None,
    max_concurrent=5,
):
    """Build a manager whose 'background thread' actually runs inline.

    Tests need deterministic completion before assertions; the call thread is
    just `target(*args)` to avoid sleep-and-poll patterns.
    """

    class _InlineThread:
        def __init__(self, target, args=(), name="", daemon=True):
            self._target = target
            self._args = args
            self.name = name
            self.daemon = daemon
            self._started = False

        def start(self):
            self._started = True
            self._target(*self._args)

        def is_alive(self):  # pragma: no cover - shape only
            return False

    return PhoneCallManager(
        planner=planner,
        driver=driver,
        events=events,
        logger_path=logger_path,
        max_concurrent=max_concurrent,
        thread_factory=lambda brief: _InlineThread(
            target=PhoneCallManager._run_call.__get__(None, PhoneCallManager),  # placeholder
            args=(brief,),
        ),
    )


# The synchronous helper above is brittle because of bound-method gymnastics;
# we use a simpler approach: a thread_factory that returns a thread whose start()
# runs target() inline. The manager itself doesn't care what kind of thread it gets.


class _InlineThread:
    def __init__(self, target, args=(), name="", daemon=True):
        self._target = target
        self._args = args
        self.name = name
        self.daemon = daemon

    def start(self):
        self._target(*self._args)


class PhoneCallManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmpdir.name) / "phone-calls.jsonl"
        self.events = EventBus()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _manager(self, driver, planner=None, max_concurrent=5):
        brief = _make_brief()
        planner = planner or _StubPlanner(brief)
        return PhoneCallManager(
            planner=planner,
            driver=driver,
            events=self.events,
            logger_path=self.log_path,
            max_concurrent=max_concurrent,
            thread_factory=lambda b: _InlineThread(target=self._inline_run_factory(planner, driver).__call__, args=(b,)),
        )

    def _inline_run_factory(self, planner, driver):
        # Compose what _run_call would do inline so the manager's behavior under
        # test mirrors real-world flow without spawning a real thread.
        manager_ref: list[PhoneCallManager] = []

        def inner(brief: CallBrief) -> None:
            manager_ref[0]._run_call(brief)  # noqa: SLF001

        # Bind in the manager after construction
        self._inline_run_inner = inner
        self._inline_run_manager_ref = manager_ref
        return inner

    def _build_manager_with_inline_threads(self, driver, planner=None, max_concurrent=5):
        planner = planner or _StubPlanner(_make_brief())
        ref: list[PhoneCallManager] = []

        def factory(brief: CallBrief):
            return _InlineThread(target=ref[0]._run_call, args=(brief,))  # noqa: SLF001

        mgr = PhoneCallManager(
            planner=planner,
            driver=driver,
            events=self.events,
            logger_path=self.log_path,
            max_concurrent=max_concurrent,
            thread_factory=factory,
        )
        ref.append(mgr)
        return mgr

    def test_place_call_with_simulator_runs_and_logs(self) -> None:
        driver = _SyncDriver(_make_result("call-1"))
        planner = _StubPlanner(_make_brief("call-1"))
        mgr = self._build_manager_with_inline_threads(driver, planner)

        result = mgr.place_call("call united about my refund")

        self.assertTrue(result["success"])
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(driver.placed[0].call_id, "call-1")
        # Log file written with REDACTED number
        log_lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(log_lines), 1)
        entry = json.loads(log_lines[0])
        self.assertEqual(entry["brief"]["recipient_number"], "***-***-4567")
        # No active call once the inline thread finished
        self.assertEqual(mgr.active_call_ids(), [])
        # History updated
        history = mgr.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, CallStatus.COMPLETED)

    def test_twilio_driver_requires_confirmation(self) -> None:
        driver = TwilioPhoneDriver(account_sid="AC_x", auth_token="t", from_number="+15550000000")
        planner = _StubPlanner(_make_brief("call-2"))
        mgr = self._build_manager_with_inline_threads(driver, planner)

        result = mgr.place_call("call united about my refund")

        self.assertFalse(result["success"])
        self.assertTrue(result["requires_confirmation"])
        # No log entry yet
        self.assertFalse(self.log_path.exists() and self.log_path.read_text())

    def test_twilio_driver_with_confirmation_runs_call(self) -> None:
        driver = TwilioPhoneDriver(account_sid="AC_x", auth_token="t", from_number="+15550000000")
        planner = _StubPlanner(_make_brief("call-3"))
        mgr = self._build_manager_with_inline_threads(driver, planner)

        result = mgr.place_call("call united about my refund", confirmed=True)

        # Driver scaffold returns FAILED, but the manager should still accept the call.
        self.assertTrue(result["success"])
        history = mgr.history()
        self.assertEqual(history[0].status, CallStatus.FAILED)
        self.assertEqual(history[0].outcome, "not_implemented")

    def test_concurrency_cap_enforced(self) -> None:
        # Build a driver that DOES NOT complete (so active stays populated).
        class _BlockingDriver(PhoneDriver):
            name = "blocking"

            def __init__(self) -> None:
                self.gate = threading.Event()
                self.placed: list[CallBrief] = []

            def place_call(self, brief, on_event):
                self.placed.append(brief)
                self.gate.wait(timeout=2)
                return _make_result(brief.call_id)

            def cancel(self, call_id):
                self.gate.set()
                return True

        driver = _BlockingDriver()
        plans = [_make_brief(f"call-{i}") for i in range(5)]
        planner = MagicMock()
        planner.plan.side_effect = [(brief, 0.9) for brief in plans]
        mgr = PhoneCallManager(
            planner=planner,
            driver=driver,
            events=self.events,
            logger_path=self.log_path,
            max_concurrent=2,
        )

        # Fill the queue with two real background threads.
        first = mgr.place_call("call 1")
        second = mgr.place_call("call 2")
        third = mgr.place_call("call 3")
        try:
            self.assertTrue(first["success"])
            self.assertTrue(second["success"])
            self.assertFalse(third["success"])
            self.assertIn("capacity", third["message"].lower())
        finally:
            driver.gate.set()
            # Allow the daemon threads to drain so the test process exits cleanly.
            for _ in range(20):
                if not mgr.active_call_ids():
                    break
                threading.Event().wait(0.05)

    def test_cancel_call_by_recipient_hint(self) -> None:
        # Build a driver whose call completes only after we cancel.
        class _Driver(PhoneDriver):
            name = "stub"

            def __init__(self) -> None:
                self.cancelled: list[str] = []
                self.gate = threading.Event()

            def place_call(self, brief, on_event):
                self.gate.wait(timeout=2)
                return _make_result(brief.call_id, status=CallStatus.CANCELLED)

            def cancel(self, call_id):
                self.cancelled.append(call_id)
                self.gate.set()
                return True

        driver = _Driver()
        planner = _StubPlanner(_make_brief("call-x"))
        mgr = PhoneCallManager(
            planner=planner,
            driver=driver,
            events=self.events,
            logger_path=self.log_path,
            max_concurrent=2,
        )

        try:
            mgr.place_call("call united")
            result = mgr.cancel_call(recipient_hint="united")
            self.assertTrue(result["success"])
            self.assertEqual(driver.cancelled, ["call-x"])
        finally:
            driver.gate.set()
            for _ in range(20):
                if not mgr.active_call_ids():
                    break
                threading.Event().wait(0.05)

    def test_summarize_last_call_returns_friendly_when_empty(self) -> None:
        driver = _SyncDriver(_make_result("call-1"))
        planner = _StubPlanner(_make_brief("call-1"))
        mgr = self._build_manager_with_inline_threads(driver, planner)

        result = mgr.summarize_last_call()

        self.assertFalse(result["success"])
        self.assertIn("haven't", result["message"])

    def test_summarize_last_call_returns_history_summary(self) -> None:
        driver = _SyncDriver(_make_result("call-1"))
        planner = _StubPlanner(_make_brief("call-1"))
        mgr = self._build_manager_with_inline_threads(driver, planner)

        mgr.place_call("call united")

        result = mgr.summarize_last_call()
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["call_id"], "call-1")
        self.assertEqual(result["data"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
