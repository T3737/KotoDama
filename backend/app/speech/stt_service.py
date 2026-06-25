from __future__ import annotations

import importlib
import logging
import os
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_STT_MODE = "mock"
DEFAULT_STT_MODEL = "tiny.en"
MOCK_TRANSCRIPT = "i would like to learn japanese"
DEFAULT_SILENCE_THRESHOLD = 0.001
DEFAULT_MIN_AUDIO_MS = 100
_SERVICE_CACHE: dict[tuple[str, str], "SpeechToTextService"] = {}
_SERVICE_CACHE_LOCK = Lock()


class STTError(RuntimeError):
    """Base error raised by speech-to-text providers."""

    code = "transcription_failed"


class STTUnavailableError(STTError):
    """Raised when a configured speech-to-text provider cannot run."""

    code = "stt_unavailable"


class STTNoSpeechError(STTError):
    """Raised when valid audio contains no detectable speech signal or text."""

    code = "no_speech_detected"


class STTAudioTooShortError(STTError):
    """Raised when valid audio is too short for useful transcription."""

    code = "audio_too_short"


class STTMalformedAudioError(STTError):
    """Raised when a WAV file cannot be decoded."""

    code = "malformed_audio"


@dataclass(frozen=True, slots=True)
class AudioInspection:
    duration_ms: int | None
    speech_detected: bool | None


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    transcript: str
    language: str
    model: str
    audio_duration_ms: int | None
    transcription_ms: int
    speech_detected: bool
    mode: str


class SpeechToTextService(ABC):
    mode = "unknown"
    model_name = "unknown"

    @abstractmethod
    def transcribe(self, audio_path: Path) -> str:
        """Return an English transcript for an audio file."""

    def prepare(self) -> None:
        """Load reusable provider state. Stateless providers are already ready."""

    def readiness(self) -> dict[str, str | float | None]:
        return {
            "mode": self.mode,
            "model": self.model_name,
            "state": "ready",
            "load_ms": 0.0,
            "error": None,
        }

    def transcribe_detailed(self, audio_path: Path) -> TranscriptionResult:
        if self.mode == "local":
            inspection = inspect_audio(audio_path)
        elif self.mode == "mock" and audio_path.suffix.lower() == ".wav":
            try:
                measured = inspect_audio(audio_path)
                inspection = AudioInspection(
                    duration_ms=measured.duration_ms, speech_detected=True
                )
            except STTMalformedAudioError:
                inspection = AudioInspection(duration_ms=None, speech_detected=True)
        else:
            inspection = AudioInspection(duration_ms=None, speech_detected=True)
        minimum_audio_ms = int(os.getenv("STT_MIN_AUDIO_MS", str(DEFAULT_MIN_AUDIO_MS)))
        if (
            self.mode == "local"
            and inspection.duration_ms is not None
            and inspection.duration_ms < minimum_audio_ms
        ):
            raise STTAudioTooShortError(
                f"Recording is too short; speak for at least {minimum_audio_ms} ms."
            )
        if inspection.speech_detected is False:
            raise STTNoSpeechError(
                "No speech was detected. Check your microphone or try again."
            )

        started_at = perf_counter()
        transcript = self.transcribe(audio_path).strip()
        transcription_ms = round((perf_counter() - started_at) * 1000)
        if not transcript:
            raise STTNoSpeechError("Local STT returned no spoken text.")
        return TranscriptionResult(
            transcript=transcript,
            language="en",
            model=self.model_name,
            audio_duration_ms=inspection.duration_ms,
            transcription_ms=transcription_ms,
            speech_detected=True,
            mode=self.mode,
        )


class MockSTTService(SpeechToTextService):
    mode = "mock"
    model_name = "mock"

    def transcribe(self, audio_path: Path) -> str:
        logger.debug("Using mock STT for temporary file %s", audio_path.name)
        return MOCK_TRANSCRIPT


class FasterWhisperSTTService(SpeechToTextService):
    mode = "local"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any | None = None
        self._model_lock = Lock()
        self._state = "not_loaded"
        self._load_ms: float | None = None
        self._load_error: str | None = None

    def prepare(self) -> None:
        if self._model is not None:
            return
        if self._state == "error":
            raise STTUnavailableError(self._load_error or "Local STT is unavailable.")
        with self._model_lock:
            if self._model is not None:
                return
            if self._state == "error":
                raise STTUnavailableError(self._load_error or "Local STT is unavailable.")
            self._state = "loading"
            self._load_error = None
            started_at = perf_counter()
            try:
                faster_whisper = importlib.import_module("faster_whisper")
                model = faster_whisper.WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
            except ImportError as exc:
                self._mark_load_error(
                    "Local STT mode requires faster-whisper. "
                    "Install backend/requirements-stt.txt or use STT_MODE=mock."
                )
                raise STTUnavailableError(self._load_error) from exc
            except Exception as exc:
                self._mark_load_error(
                    f"Could not load local STT model {self.model_name!r}: {exc}"
                )
                raise STTUnavailableError(self._load_error) from exc

            self._model = model
            self._load_ms = (perf_counter() - started_at) * 1000
            self._state = "ready"
            logger.info(
                "stt_model_loaded mode=local model=%s load_ms=%.1f",
                self.model_name,
                self._load_ms,
            )

    def transcribe(self, audio_path: Path) -> str:
        self.prepare()
        assert self._model is not None
        try:
            segments, _info = self._model.transcribe(
                str(audio_path),
                language="en",
                beam_size=1,
            )
            return " ".join(
                segment.text.strip()
                for segment in segments
                if segment.text.strip()
            )
        except Exception as exc:
            raise STTError(f"Local speech transcription failed: {exc}") from exc

    def readiness(self) -> dict[str, str | float | None]:
        return {
            "mode": self.mode,
            "model": self.model_name,
            "state": self._state,
            "load_ms": round(self._load_ms, 1) if self._load_ms is not None else None,
            "error": self._load_error,
        }

    def _mark_load_error(self, message: str) -> None:
        self._state = "error"
        self._load_ms = None
        self._load_error = message


def inspect_audio(audio_path: Path) -> AudioInspection:
    if audio_path.suffix.lower() != ".wav":
        return AudioInspection(duration_ms=None, speech_detected=None)
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            sample_width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise STTMalformedAudioError("The WAV recording is malformed.") from exc

    if frame_rate <= 0 or channels <= 0 or sample_width not in {1, 2, 3, 4}:
        raise STTMalformedAudioError("The WAV recording has invalid audio metadata.")
    duration_ms = round(frame_count / frame_rate * 1000)
    threshold = float(os.getenv("STT_SILENCE_THRESHOLD", str(DEFAULT_SILENCE_THRESHOLD)))
    return AudioInspection(
        duration_ms=duration_ms,
        speech_detected=_peak_amplitude(frames, sample_width) > threshold,
    )


def _peak_amplitude(frames: bytes, sample_width: int) -> float:
    if not frames:
        return 0.0
    peak = 0
    if sample_width == 1:
        peak = max(abs(value - 128) for value in frames)
        maximum = 127
    else:
        maximum = (1 << (sample_width * 8 - 1)) - 1
        for offset in range(0, len(frames) - sample_width + 1, sample_width):
            value = int.from_bytes(
                frames[offset : offset + sample_width], "little", signed=True
            )
            peak = max(peak, abs(value))
    return peak / maximum if maximum else 0.0


def get_stt_mode() -> str:
    return os.getenv("STT_MODE", DEFAULT_STT_MODE).strip().lower()


def get_stt_model() -> str:
    return os.getenv("STT_MODEL", DEFAULT_STT_MODEL).strip() or DEFAULT_STT_MODEL


def create_stt_service(
    mode: str | None = None, model_name: str | None = None
) -> SpeechToTextService:
    return _create_stt_service(mode or get_stt_mode(), model_name or get_stt_model())


def get_stt_readiness() -> dict[str, str | float | None]:
    try:
        return create_stt_service().readiness()
    except STTUnavailableError as exc:
        return {
            "mode": get_stt_mode(),
            "model": get_stt_model(),
            "state": "error",
            "load_ms": None,
            "error": str(exc),
        }


def clear_stt_service_cache() -> None:
    """Test/development helper for applying a new process configuration."""

    with _SERVICE_CACHE_LOCK:
        _SERVICE_CACHE.clear()


def _create_stt_service(mode: str, model_name: str) -> SpeechToTextService:
    key = (mode, model_name)
    with _SERVICE_CACHE_LOCK:
        cached = _SERVICE_CACHE.get(key)
        if cached is not None:
            return cached
        logger.info("Creating speech-to-text service: mode=%s model=%s", mode, model_name)
        if mode == "mock":
            service: SpeechToTextService = MockSTTService()
        elif mode == "local":
            service = FasterWhisperSTTService(model_name)
        else:
            raise STTUnavailableError(
                f"Unsupported STT_MODE {mode!r}. Expected 'mock' or 'local'."
            )
        _SERVICE_CACHE[key] = service
        return service
