from __future__ import annotations

import unittest

import numpy

from friday.voice.vad_manager import VADManager


class VADManagerTests(unittest.TestCase):
    def test_energy_threshold_detects_speech(self) -> None:
        vad = VADManager({"energy_threshold": 0.008})
        audio = numpy.ones(1600, dtype="float32") * 0.02

        self.assertTrue(vad.is_speech(audio, numpy))

    def test_energy_threshold_ignores_silence(self) -> None:
        vad = VADManager({"energy_threshold": 0.008})
        audio = numpy.zeros(1600, dtype="float32")

        self.assertFalse(vad.is_speech(audio, numpy))


if __name__ == "__main__":
    unittest.main()
