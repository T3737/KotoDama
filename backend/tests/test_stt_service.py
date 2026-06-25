import tempfile
import time
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.speech.stt_service import (
    FasterWhisperSTTService,
    STTAudioTooShortError,
    STTMalformedAudioError,
    STTNoSpeechError,
    STTUnavailableError,
    clear_stt_service_cache,
    create_stt_service,
)
from tools.benchmark_stt import compare_text


class STTServiceLifecycleTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_stt_service_cache()

    def test_factory_reuses_service_for_same_configuration(self) -> None:
        first = create_stt_service("local", "base.en")
        second = create_stt_service("local", "base.en")
        self.assertIs(first, second)
        self.assertEqual(first.readiness()["state"], "not_loaded")

    def test_concurrent_factory_returns_one_service_instance(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            services = list(
                executor.map(
                    lambda _index: create_stt_service("local", "tiny.en"), range(16)
                )
            )
        self.assertTrue(all(service is services[0] for service in services))

    def test_concurrent_prepare_loads_model_once(self) -> None:
        load_count = 0

        class FakeModel:
            def __init__(self, *_args, **_kwargs) -> None:
                nonlocal load_count
                load_count += 1
                time.sleep(0.02)

        service = FasterWhisperSTTService("small.en")
        module = SimpleNamespace(WhisperModel=FakeModel)
        with patch("importlib.import_module", return_value=module):
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda _index: service.prepare(), range(4)))

        self.assertEqual(load_count, 1)
        self.assertEqual(service.readiness()["state"], "ready")
        self.assertIsNotNone(service.readiness()["load_ms"])

    def test_missing_local_model_is_cached_as_readiness_error(self) -> None:
        service = FasterWhisperSTTService("missing.en")
        with patch(
            "importlib.import_module",
            side_effect=ModuleNotFoundError("faster_whisper"),
        ) as importer:
            with self.assertRaises(STTUnavailableError):
                service.prepare()
            with self.assertRaises(STTUnavailableError):
                service.prepare()
        self.assertEqual(importer.call_count, 1)
        self.assertEqual(service.readiness()["state"], "error")
        self.assertIn("faster-whisper", str(service.readiness()["error"]))

    def test_silent_wav_is_rejected_before_model_loading(self) -> None:
        service = FasterWhisperSTTService("tiny.en")
        with temporary_wav(b"\x00\x00" * 1600) as path:
            with self.assertRaises(STTNoSpeechError):
                service.transcribe_detailed(path)
        self.assertEqual(service.readiness()["state"], "not_loaded")

    def test_short_wav_has_distinct_error(self) -> None:
        service = FasterWhisperSTTService("tiny.en")
        with temporary_wav(b"\xff\x7f" * 800) as path:
            with self.assertRaises(STTAudioTooShortError):
                service.transcribe_detailed(path)

    def test_malformed_wav_has_distinct_error(self) -> None:
        service = FasterWhisperSTTService("tiny.en")
        audio_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio_file.close()
        path = Path(audio_file.name)
        try:
            path.write_bytes(b"not a wav")
            with self.assertRaises(STTMalformedAudioError):
                service.transcribe_detailed(path)
        finally:
            path.unlink(missing_ok=True)

    def test_manifest_comparison_is_normalized(self) -> None:
        comparison = compare_text("Hello, how are you?", "hello how are you")
        self.assertTrue(comparison["exact_match"])
        self.assertEqual(comparison["word_differences"], 0)
        self.assertEqual(comparison["word_error_rate"], 0.0)


class temporary_wav:
    def __init__(self, frames: bytes, sample_rate: int = 16000) -> None:
        self.frames = frames
        self.sample_rate = sample_rate
        self.path: Path | None = None

    def __enter__(self) -> Path:
        temporary_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temporary_file.close()
        self.path = Path(temporary_file.name)
        with wave.open(str(self.path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.frames)
        return self.path

    def __exit__(self, *_args) -> None:
        if self.path is not None:
            self.path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
