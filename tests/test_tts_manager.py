from __future__ import annotations

import unittest

from friday.voice.tts_manager import TTSManager


class TTSManagerTests(unittest.TestCase):
    def test_silent_mode_does_not_start_process(self) -> None:
        tts = TTSManager(silent=True)
        tts.speak("Hello boss.")

        self.assertFalse(tts.status().speaking)

    def test_json_is_not_spoken(self) -> None:
        tts = TTSManager(silent=True)

        self.assertEqual(tts._clean_spoken_text('{"intent":"open"}'), "")

    def test_secrets_are_redacted_before_speech(self) -> None:
        tts = TTSManager(silent=True)

        self.assertIn("redacted", tts._clean_spoken_text("password=abc123"))

    def test_markdown_links_are_spoken_cleanly(self) -> None:
        tts = TTSManager(silent=True)

        self.assertEqual(tts._clean_spoken_text("Open [YouTube](https://www.youtube.com/watch?v=123)."), "Open YouTube.")

    def test_code_blocks_are_not_read_verbatim(self) -> None:
        tts = TTSManager(silent=True)

        spoken = tts._clean_spoken_text("Done.\n```python\nprint('hello')\n```")
        self.assertEqual(spoken, "Done. I included the code in the transcript.")

    def test_system_terms_are_naturalized(self) -> None:
        tts = TTSManager(silent=True)

        self.assertEqual(tts._clean_spoken_text("FRIDAY TTS is ready at localhost."), "Friday text to speech is ready at local host.")

    def test_recent_spoken_text_expires(self) -> None:
        tts = TTSManager(silent=True)
        tts._recent_text = "Friday startup greeting"
        tts._recent_text_at = 0.0

        self.assertIsNone(tts.get_recent_spoken_text(max_age_seconds=0.1))

    def test_markdown_formatting_is_spoken_cleanly(self) -> None:
        tts = TTSManager(silent=True)

        spoken = tts._clean_spoken_text("# Plan\n\n**Fast path**\n- Open app\n- Click `Play`")
        self.assertEqual(spoken, "Plan Fast path. Open app. Click Play")

    def test_markdown_tables_do_not_speak_separator_pipes(self) -> None:
        tts = TTSManager(silent=True)

        spoken = tts._clean_spoken_text("| Item | Status |\n| --- | --- |\n| Spotify | Ready |")
        self.assertEqual(spoken, "Item, Status. Spotify, Ready")


if __name__ == "__main__":
    unittest.main()
