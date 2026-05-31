from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TurnState(str, Enum):
    IDLE_WAKE_LISTENING = "IDLE_WAKE_LISTENING"
    WAKE_DETECTED = "WAKE_DETECTED"
    COMMAND_LISTENING = "COMMAND_LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    FOLLOW_UP_LISTENING = "FOLLOW_UP_LISTENING"
    SESSION_LISTENING = "SESSION_LISTENING"
    RETURNING_TO_IDLE = "RETURNING_TO_IDLE"
    SLEEP_MODE = "SLEEP_MODE"


@dataclass
class TurnManager:
    state: TurnState = TurnState.IDLE_WAKE_LISTENING
    session_mode: bool = False

    def set_state(self, state: str | TurnState) -> None:
        self.state = TurnState(state)

    def return_to_idle(self) -> None:
        self.session_mode = False
        self.state = TurnState.IDLE_WAKE_LISTENING

    def enter_command_listening(self) -> None:
        self.state = TurnState.COMMAND_LISTENING

    def enter_follow_up_listening(self) -> None:
        self.state = TurnState.FOLLOW_UP_LISTENING

    def enter_session_listening(self) -> None:
        self.session_mode = True
        self.state = TurnState.SESSION_LISTENING

    def enter_sleep_mode(self) -> None:
        self.session_mode = False
        self.state = TurnState.SLEEP_MODE
