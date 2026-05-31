from __future__ import annotations

from friday.assistant import FridayAssistant
from friday.config import FridayConfig
from friday.events import EventBus
from friday.model_manager import ModelManager
from friday.ollama_engine import OllamaClient
from friday.state import StateManager
from friday.tools import ToolRouter
from friday.transcript import TranscriptLogger
from friday.tts import MacOSTTS


def run_self_test(config: FridayConfig) -> int:
    events = EventBus()
    state = StateManager()
    tts = MacOSTTS(silent=True)
    transcript = TranscriptLogger(config.transcript_dir)
    ollama = OllamaClient(
        config.ollama_host,
        config.ollama_model,
        assistant_name=config.personality.assistant_name,
        assistant_acronym=config.personality.acronym,
    )
    tools = ToolRouter(
        config.root_dir,
        config.resend_api_key,
        default_model=config.ollama_default_model,
        vision_model=config.ollama_vision_model,
        code_model=config.ollama_code_model,
        ollama_host=config.ollama_host,
        ollama=ollama,
    )
    model_manager = ModelManager(
        ollama,
        config.ollama_default_model,
        config.ollama_fast_model,
        config.ollama_vision_model,
        code_model=config.ollama_code_model,
    )
    assistant = FridayAssistant(
        state,
        tts,
        transcript,
        events,
        ollama,
        tools,
        assistant_name=config.personality.assistant_name,
        assistant_acronym=config.personality.acronym,
        personality=config.personality,
        model_manager=model_manager,
        timezone=config.location.timezone,
    )
    result = assistant.submit_text("status", source="self-test")
    if result.final_output.startswith("FRIDAY:"):
        print("FRIDAY self-test failed: normal responses should not be prefixed with FRIDAY.")
        return 1
    if "Ollama" not in result.final_output:
        print("FRIDAY self-test failed: status response did not include Ollama state.")
        return 1
    tool_result = tools.execute({"intent": "self_test", "command": "run_command", "parameters": {"command": "printf friday"}})
    if not tool_result or not tool_result[0].success or tool_result[0].data.get("stdout") != "friday":
        print("FRIDAY self-test failed: run_command tool did not execute safely.")
        return 1
    if not config.frontend_dir.joinpath("index.html").exists():
        print("FRIDAY self-test failed: frontend/index.html is missing.")
        return 1
    print("FRIDAY self-test passed.")
    print(result.final_output)
    return 0
