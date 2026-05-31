from __future__ import annotations


class ResponseGenerator:
    def task_started(self) -> str:
        return "On it, boss."

    def task_completed(self) -> str:
        return "Done, boss."

    def confirmation_question(self, reason: str) -> str:
        if reason:
            return f"Just to confirm, sir - this involves {reason}. Should I continue?"
        return "Just to confirm, sir - should I continue?"

    def canceled(self) -> str:
        return "Canceled, boss."
