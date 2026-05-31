from __future__ import annotations

import unittest

from friday.voice.transcript_cleaner import TranscriptCleaner


class TranscriptCleanerTests(unittest.TestCase):
    def test_messy_wake_command_is_cleaned(self) -> None:
        cleaner = TranscriptCleaner()

        self.assertEqual(cleaner.clean("Friday uh can you like open YouTube and search AI agents"), "open youtube and search ai agents")

    def test_correction_keeps_latest_command(self) -> None:
        cleaner = TranscriptCleaner()

        self.assertEqual(cleaner.clean("Friday search Drake actually no search Lil Baby"), "search lil baby")

    def test_thinking_words_are_removed_without_losing_command(self) -> None:
        cleaner = TranscriptCleaner()

        self.assertEqual(
            cleaner.clean("Friday okay so umm I mean can you like open Spotify for me"),
            "open spotify for me",
        )

    def test_verbatim_mode_preserves_text(self) -> None:
        cleaner = TranscriptCleaner()

        self.assertEqual(cleaner.clean("Paste this EXACTLY, please.", verbatim=True), "Paste this EXACTLY, please.")


if __name__ == "__main__":
    unittest.main()
