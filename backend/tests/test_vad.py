import unittest
from pathlib import Path

from app.orchestration.vad_turn import VADTurnDetector
from app.speech.vad_service import (
    PCM16MonoResampler,
    DisabledVADService,
    SileroOnnxVADService,
    VADConfig,
    VADUnavailableError,
)


WINDOW = b"\x00\x00" * 512


class SequenceVADStream:
    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = iter(probabilities)

    def probability(self, _pcm16_mono: bytes) -> float:
        return next(self.probabilities)


def config(**overrides) -> VADConfig:
    values = {
        "enabled": True,
        "model_path": Path("unused.onnx"),
        "threshold": 0.5,
        "min_speech_ms": 64,
        "end_silence_ms": 96,
        "no_speech_timeout_ms": 320,
        "max_turn_ms": 640,
        "pre_roll_ms": 32,
        "post_roll_ms": 32,
        "verbose_probabilities": False,
    }
    values.update(overrides)
    return VADConfig(**values)


def feed(detector: VADTurnDetector, count: int = 1):
    signals = []
    outcome = None
    for _index in range(count):
        current_signals, current_outcome = detector.process(WINDOW)
        signals.extend(current_signals)
        if current_outcome is not None:
            outcome = current_outcome
            break
    return signals, outcome


class VADTurnDetectorTests(unittest.TestCase):
    def test_brief_noise_does_not_start_speech(self) -> None:
        detector = VADTurnDetector(
            config(), SequenceVADStream([0.0, 0.9, 0.0, 0.0]), 16000
        )
        signals, outcome = feed(detector, 4)
        self.assertFalse(detector.speech_started)
        self.assertEqual(signals, [])
        self.assertIsNone(outcome)

    def test_confirmed_speech_emits_started_event(self) -> None:
        detector = VADTurnDetector(config(), SequenceVADStream([0.0, 0.9, 0.9]), 16000)
        signals, outcome = feed(detector, 3)
        self.assertIsNone(outcome)
        self.assertTrue(detector.speech_started)
        self.assertEqual([signal.event_type for signal in signals], ["vad.speech_started"])
        self.assertEqual(signals[0].payload["elapsed_ms"], 32)

    def test_short_pause_does_not_end_and_speech_resets_silence(self) -> None:
        detector = VADTurnDetector(
            config(), SequenceVADStream([0.9, 0.9, 0.0, 0.9, 0.0, 0.0, 0.0]), 16000
        )
        signals, outcome = feed(detector, 7)
        self.assertEqual(
            [signal.event_type for signal in signals],
            ["vad.speech_started", "vad.speech_ended"],
        )
        self.assertEqual(outcome.reason, "end_of_speech")
        self.assertEqual(outcome.silence_duration_ms, 96)

    def test_no_speech_timeout(self) -> None:
        detector = VADTurnDetector(
            config(no_speech_timeout_ms=96), SequenceVADStream([0.0, 0.0, 0.0]), 16000
        )
        _signals, outcome = feed(detector, 3)
        self.assertEqual(outcome.reason, "no_speech_timeout")
        self.assertFalse(outcome.should_transcribe)

    def test_maximum_turn_duration_completes_active_speech(self) -> None:
        detector = VADTurnDetector(
            config(max_turn_ms=128, no_speech_timeout_ms=1000),
            SequenceVADStream([0.9, 0.9, 0.9, 0.9]),
            16000,
        )
        signals, outcome = feed(detector, 4)
        self.assertEqual(outcome.reason, "maximum_turn_duration")
        self.assertTrue(outcome.should_transcribe)
        self.assertEqual(signals[-1].event_type, "vad.speech_ended")

    def test_manual_stop_before_and_after_speech(self) -> None:
        waiting = VADTurnDetector(config(), SequenceVADStream([0.0]), 16000)
        feed(waiting)
        self.assertFalse(waiting.manual_outcome().should_transcribe)

        speaking = VADTurnDetector(config(), SequenceVADStream([0.9, 0.9]), 16000)
        feed(speaking, 2)
        outcome = speaking.manual_outcome()
        self.assertTrue(outcome.should_transcribe)
        self.assertEqual(outcome.reason, "manual_stop")

    def test_pre_and_post_roll_trim_original_rate_audio(self) -> None:
        detector = VADTurnDetector(
            config(pre_roll_ms=32, post_roll_ms=32),
            SequenceVADStream([0.0, 0.9, 0.9, 0.0, 0.0, 0.0]),
            16000,
        )
        _signals, outcome = feed(detector, 6)
        original = b"\x01\x00" * (512 * 6)
        retained = detector.retained_pcm(original)
        self.assertEqual(outcome.reason, "end_of_speech")
        self.assertLess(len(retained), len(original))
        self.assertGreaterEqual(len(retained), 512 * 2 * 3)


class VADServiceTests(unittest.TestCase):
    def test_disabled_service_reports_manual_fallback(self) -> None:
        service = DisabledVADService(config(enabled=False))
        self.assertEqual(service.readiness()["state"], "disabled")
        with self.assertRaises(VADUnavailableError):
            service.create_stream()

    def test_missing_model_reports_error_without_download(self) -> None:
        service = SileroOnnxVADService(config(model_path=Path("missing.onnx")))
        with self.assertRaises(VADUnavailableError):
            service.prepare()
        self.assertEqual(service.readiness()["state"], "error")

    def test_resampler_keeps_original_pcm_and_converts_rate(self) -> None:
        original = (b"\x01\x00\xff\x7f" * 2400)
        untouched = bytes(original)
        output = PCM16MonoResampler(48000).process(original)
        self.assertEqual(original, untouched)
        output_samples = len(output) // 2
        self.assertGreater(output_samples, 1500)
        self.assertLessEqual(output_samples, 1600)


if __name__ == "__main__":
    unittest.main()
