# FRIDAY Local Assistant

FRIDAY is a local-first assistant that runs from `python main.py`, serves a browser UI at `http://127.0.0.1:8765`, uses Ollama for reasoning, uses local STT for voice input, and uses macOS `say` for TTS.

FRIDAY stands for **Fast Responsive Intelligent Digital Assistant, Year-round**. The acronym and personality live in `friday/config/personality_config.json`.

## What It Can Do

- Voice and text input through the same command pipeline.
- Wake-word listening for "Friday" and supported alternates.
- Local Ollama reasoning with `qwen3:4b` by default.
- Browser opening, searching, tab switching, tab closing, site-specific searches, and media play flows.
- Desktop app opening/focus for known Mac apps.
- Apple Maps directions and fastest-route summaries.
- Todo list add, complete, clear, and list commands.
- File upload analysis for screenshots and video metadata paths.
- Multi-agent routing for conversation, coding, math, information, productivity, and visual tasks.
- Transcript and screen-control action logging with redaction.

## Requirements

- macOS, tested for local Mac workflows.
- Python 3.10 or newer.
- Ollama installed and running.
- Chrome or Safari for browser control.
- Microphone permission for the terminal/Python process that starts FRIDAY.

## First-Time Setup

From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Install the default Ollama model:

```bash
ollama pull qwen3:4b
```

Optional models:

```bash
ollama pull qwen3:1.7b
ollama pull qwen2.5-coder:7b
ollama pull llama3.2-vision:11b
```

Create local environment settings:

```bash
cp .env.example .env
```

Then edit `.env` with local-only values. Do not commit `.env`.

## Run FRIDAY

Direct run:

```bash
python main.py
```

Scripted run:

```bash
scripts/friday.sh start
scripts/friday.sh status
scripts/friday.sh stop
scripts/friday.sh restart
```

On macOS, the script starts FRIDAY in a detached `screen` session when `screen` is available. That keeps the local server alive after the startup command returns.

Open the UI:

```text
http://127.0.0.1:8765
```

Health check:

```bash
curl -s http://127.0.0.1:8765/api/status | python3 -m json.tool
```

## macOS Microphone Setup

FRIDAY's backend listens through Python, so macOS may show `Python`, `Terminal`, or `Xcode Python` as the microphone user. It will not show "FRIDAY" unless the project is packaged as a native app.

1. Open System Settings.
2. Go to Privacy & Security.
3. Open Microphone.
4. Enable microphone access for the app that starts FRIDAY, usually Terminal, iTerm, Python, or Xcode Python.
5. Restart FRIDAY with `scripts/friday.sh restart`.
6. Check `/api/status` and confirm:
   - `voice.running` is `true`
   - `voice.microphone_stream_open` is `true`
   - `voice.audio_level` changes while you speak

If the localhost page is open but the mic indicator is off, the backend process is not running or macOS permission is missing. The browser tab alone does not keep FRIDAY alive.

## Auto-Start Note

`scripts/friday.sh install` creates a LaunchAgent, but macOS can block background agents from projects inside `~/Documents`. For reliable auto-start, move this folder somewhere outside protected Documents, such as `~/Friday`, then run:

```bash
scripts/friday.sh install
```

## Useful Voice Tests

Try these after startup:

```text
Friday open YouTube
Friday search YouTube for AP Calculus derivatives
Friday open Spotify and play Sum 2 Prove by Lil Baby
Friday add finish math homework to my todo list by 6 PM
Friday I'm done with math homework
Friday clear my todo list
Friday directions to Crystal Bridges by driving
Friday stop
```

## Troubleshooting

### Localhost refuses to connect

Run:

```bash
scripts/friday.sh status
scripts/friday.sh restart
```

If it still fails, inspect:

```bash
tail -n 80 "${TMPDIR:-/tmp}/friday-local-assistant.log"
```

### Ollama is not responding

Start Ollama and check the model:

```bash
ollama serve
ollama list
ollama pull qwen3:4b
```

### Browser automation acts signed out

FRIDAY uses your real browser where possible for major site workflows. Make sure Chrome or Safari is signed into the account you want before asking FRIDAY to open account-specific pages.

### Playwright browser install is missing

Run:

```bash
python -m playwright install chromium
```

### TTS sounds wrong

FRIDAY uses macOS `say`. You can test outside FRIDAY:

```bash
say "FRIDAY voice check."
```

Change the system voice in macOS System Settings, or set `voice_name` in `friday/config/voice_config.json`.

## Tests

Install pytest if your environment does not already have it:

```bash
python -m pip install pytest
```

Run the suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider
```

Run focused voice checks:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_tts_manager.py tests/test_wake_word.py tests/test_voice_pipeline.py tests/test_vad_manager.py tests/test_stop_phrases.py
```

## Repository Hygiene

These stay local and are ignored by Git:

- `.env`
- `.venv/`
- `.friday/`
- `transcripts/`
- `logs/`
- cache folders
- browser test artifacts

Before pushing:

```bash
git status --short
```

Only source, tests, docs, config examples, and setup scripts should be committed.
