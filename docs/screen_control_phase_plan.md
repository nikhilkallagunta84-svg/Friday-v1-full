# FRIDAY Screen Control Phase Plan

Phase 0 audit date: 2026-05-14

Scope: audit and planning only. No full screen-control implementation was added in this phase.

## Current Project Structure

- `main.py` is the app entry point.
- `friday/server.py` owns the local HTTP runtime, browser UI API routes, STT upload route, file-analysis route, and startup wiring.
- `frontend/` contains the browser UI.
- `friday/assistant.py` is the main voice/text command pipeline after input is transcribed or submitted.
- `friday/local_intents.py` handles fast deterministic routing before Ollama.
- `friday/ollama_engine.py` handles Ollama intent JSON, conversational responses, web freshness responses, and image generation calls.
- `friday/tools/router.py` is the central command router.
- `friday/tools/` contains current tool implementations for apps, browser, browser control, shell commands, email, filesystem, safety, screen control, and system info.
- `friday/voice/` contains the voice loop pieces, including wake word, STT, TTS, VAD, echo guard, and stop phrase handling.
- `friday/services/` contains time, weather, web search, upload vision analysis, and visual context services.
- `friday/agents/` contains the multi-agent prompt selector.
- `transcripts/` stores transcript output.
- `.friday/browser-profile`, `.friday/browser-screenshots`, `.friday/screen-screenshots`, and `.friday/test-profile` are local runtime data folders.

## Existing Files To Reuse

- `friday/tools/router.py`: keep as the command router. It already initializes `ScreenControlTool` and routes `screen_control` commands.
- `friday/tools/screen_control.py`: reuse as the current adapter during the next phase. It already supports screenshots, screen description, locating targets with an Ollama vision model, clicks, typing, paste, hotkeys, scrolling, drag, mouse position, screen size, and confirmation checks for risky actions.
- `friday/tools/browser_control.py`: reuse as the Playwright-first browser controller. It already has persistent browser profile support, website aliases, screenshot support, vision-assisted clicking, and a screen-control fallback path.
- `friday/tools/browser.py`: reuse for simple browser open/search/tab commands.
- `friday/tools/app_control.py`: reuse for app-open/app-close precedence before browser or web fallback.
- `friday/local_intents.py`: reuse its screen-task and browser-task intent detection, including explicit screen-control keywords.
- `friday/assistant.py`: reuse its queue, memory context, agent selection, confirmation flow, validation, TTS publishing, and transcript logging.
- `friday/ollama_engine.py`: reuse `generate_with_images` and the existing `screen_control` tool schema in the intent prompt.
- `friday/services/vision_manager.py`: reuse for uploaded screenshot/video analysis, but keep live screen control separate.
- `friday/services/visual_context.py`: reuse for follow-up prompts about uploaded visual context.
- `friday/transcript.py`: reuse for JSONL and Markdown transcript logging with current secret redaction.
- `friday/tools/safety.py` and `friday/brain/safety_validator.py`: reuse as the starting point for command and risky-action confirmation rules.

## Current Command/Input Pipeline

Typed input:

`frontend` -> `POST /api/message` in `friday/server.py` -> `FridayAssistant.submit_text()` -> `InputProcessor` -> memory/context -> agent selector -> local intents -> Ollama intent -> validation -> `ToolRouter.execute()` -> transcript logger -> response -> TTS.

Browser STT input:

`frontend` mic capture -> `POST /api/stt` in `friday/server.py` -> `STTManager.transcribe_audio_file()` -> returned text goes through the same assistant pipeline as typed input.

Native wake-word voice input:

`WakeWordService` keeps the microphone loop active, transcribes chunks with faster-whisper, detects wake/stop phrases, and calls `FridayAssistant.submit_text()` for commands.

Tool routing:

`ToolRouter` dispatches command names including `open_app`, `close_app`, `browser_open`, `browser_search`, `browser_close_tab`, `browser_switch_tab`, `browser_task`, `screen_control`, `run_command`, file commands, email, and system/time commands.

Logging:

`TranscriptLogger` writes session JSONL and Markdown records with raw input, filtered input, intent JSON, executed commands, and final output. It redacts common API-key patterns.

## Existing Browser/System-Control Files

- `friday/tools/app_control.py`: Mac app open/close behavior.
- `friday/tools/browser.py`: simple browser navigation/search/tab actions.
- `friday/tools/browser_control.py`: Playwright browser automation and screen fallback.
- `friday/tools/screen_control.py`: PyAutoGUI-based visible-screen actions and Ollama vision target lookup.
- `friday/tools/command.py`: sandboxed shell command execution.
- `friday/tools/filesystem.py`: project-scoped file operations.
- `friday/tools/system.py`: system/time/status utilities.
- `friday/tools/safety.py`: shell/file safety helpers.

## Where Screen-Control Modules Should Be Added

Add a new package under:

`friday/screen/`

Recommended shape for later phases:

- `friday/screen/__init__.py`
- `friday/screen/capture.py`: screenshot capture, image validation, display metadata, and multi-monitor normalization.
- `friday/screen/permissions.py`: macOS Screen Recording, Accessibility, and Automation permission checks with user-facing status messages.
- `friday/screen/vision_locator.py`: target-location prompts, Ollama vision calls, JSON parsing, confidence thresholds, and coordinate scaling.
- `friday/screen/action_executor.py`: safe wrappers around mouse, keyboard, paste, scroll, drag, and hotkey actions.
- `friday/screen/planner.py`: convert a bounded task into a short action plan without executing raw natural language directly.
- `friday/screen/safety.py`: confirmations for submit/send/delete/pay/schoolwork/password/private-data actions.
- `friday/screen/session.py`: per-task state, screenshots, retries, action audit data, and timeout limits.

Keep `friday/tools/screen_control.py` as the `ToolRouter` adapter. In Phase 1, it should delegate into `friday/screen/*` instead of being rewritten wholesale.

## Tests Found

Tests already exist in `tests/`:

- `test_agent_orchestrator.py`
- `test_barge_in.py`
- `test_browser_close_tabs.py`
- `test_browser_switch_tabs.py`
- `test_greeting_engine.py`
- `test_intent_parser.py`
- `test_personality_responses.py`
- `test_safety_validator.py`
- `test_stop_phrases.py`
- `test_transcript_cleaner.py`
- `test_tts_manager.py`
- `test_vad_manager.py`
- `test_vision_manager.py`
- `test_visual_context.py`
- `test_voice_pipeline.py`
- `test_wake_word.py`
- `test_weather_manager.py`
- `test_web_search.py`

No dedicated `test_screen_control.py` or `test_screen_*` suite exists yet.

## Dependencies Already Installed

Declared in `requirements.txt`:

- `faster-whisper`
- `numpy`
- `playwright`
- `pyautogui`
- `pyperclip`
- `sounddevice`

Detected in the local virtual environment:

- `faster_whisper`
- `numpy`
- `playwright`
- `pyautogui`
- `pyperclip`
- `sounddevice`
- `PIL`
- `Quartz`
- `AppKit`

Local Ollama models currently available:

- `qwen3:4b`
- `llava:latest`

## Dependencies That May Be Needed Later

- `mss`: faster and more predictable multi-monitor screenshots.
- `opencv-python`: template matching, image preprocessing, and simple visual verification.
- `pytesseract` or `easyocr`: OCR fallback when vision-model target lookup is uncertain.
- `pyobjc-framework-Quartz` and `pyobjc-framework-AppKit`: only if the current `Quartz` and `AppKit` availability is not enough for robust permission/window checks on a fresh setup.
- A stronger local vision model in Ollama, if the machine can run it acceptably.

Do not add these during Phase 0.

## Current Risks

- `friday/tools/screen_control.py` is already doing many jobs in one file: parsing, screenshots, vision calls, coordinate scaling, action execution, and safety checks. That makes it harder to test safely.
- PyAutoGUI coordinate actions are brittle across display scaling, browser zoom, multiple monitors, and changed window positions.
- macOS permissions can block screenshots and input control. Screen Recording and Accessibility must be checked before users rely on this.
- Browser automation and full-screen automation overlap. Browser control should stay Playwright-first, with visible-screen fallback only when Playwright cannot do the job or when the user explicitly asks for screen control.
- Vision target lookup depends on Ollama returning valid coordinates. It needs confidence thresholds, retries, and a safe failure path before broader use.
- Screen screenshots may contain private information. Transcript redaction exists, but screenshot retention and screen-text logging need tighter privacy rules before expanding this feature.
- There is no dedicated screen-control test suite yet.
- Risky task confirmations exist, but they should be centralized before autonomous multi-step actions are expanded.

## Exact Next Phase Recommendation

Phase 1 should be a safety-and-structure extraction only:

1. Create the `friday/screen/` package.
2. Move screenshot capture, permission/status checks, vision locating, action execution, and screen safety into small modules.
3. Keep `friday/tools/screen_control.py` as a thin adapter used by `ToolRouter`.
4. Add tests for routing, dry-run behavior, permission error messages, risky-action confirmation, target-location JSON parsing, and coordinate scaling.
5. Do not add autonomous multi-step screen planning until these pieces are isolated and tested.

Recommended next command after Phase 0:

`python -m unittest tests/test_screen_control.py`

That test file does not exist yet; creating it should be part of Phase 1.

## Browser Automation Principles Added

Later screen-control phases should follow the dedicated browser automation guide in `docs/browser_automation_principles.md`.

The short version:

- Convert user intent into structured `ScreenAction` objects.
- Prefer semantic Playwright locators or future DOM `ref_*` handles over coordinates.
- Use screenshot and vision only for canvas-heavy or inaccessible pages.
- Execute multi-step work through ordered plans rather than scattered one-off calls.
- Verify after every state-changing browser action.
- Return clean `ActionResult` failures instead of throwing stack traces to the user.
- Log only sanitized action history.
