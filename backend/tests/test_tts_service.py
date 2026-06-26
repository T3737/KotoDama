import io
import unittest
import wave

from app.speech.tts_service import PiperTTSService


class FakePiperVoice:
    def synthesize(self, text: str, wav_file) -> None:
        wav_file.writeframes(b"\x00\x00")

    def synthesize_wav(self, text: str, wav_file) -> None:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 160)


class PiperTTSServiceTests(unittest.TestCase):
    def test_local_piper_uses_synthesize_wav_and_returns_valid_wav(self) -> None:
        service = PiperTTSService()
        service._voice = FakePiperVoice()
        service._state = "ready"

        result = service.synthesize("Hello from Piper.")

        self.assertGreater(len(result.audio_bytes), 0)
        self.assertTrue(result.audio_bytes.startswith(b"RIFF"))
        self.assertEqual(result.audio_bytes[8:12], b"WAVE")
        self.assertGreater(result.duration_ms, 0)
        self.assertEqual(result.mode, "local")

        with wave.open(io.BytesIO(result.audio_bytes), "rb") as wav_file:
            self.assertGreaterEqual(wav_file.getnchannels(), 1)
            self.assertGreater(wav_file.getsampwidth(), 0)
            self.assertGreater(wav_file.getframerate(), 0)
            self.assertGreater(wav_file.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
