import importlib
import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_STT_MODE = "mock"
DEFAULT_STT_MODEL = "tiny.en"
MOCK_TRANSCRIPT = "i would like to learn japanese"


class STTError(RuntimeError):
    """Base error raised by speech-to-text providers."""


class STTUnavailableError(STTError):
    """Raised when a configured speech-to-text provider cannot run."""


class SpeechToTextService(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path) -> str:
        """Return an English transcript for an audio file."""


class MockSTTService(SpeechToTextService):
    def transcribe(self, audio_path: Path) -> str:
        logger.debug("Using mock STT for temporary file %s", audio_path.name)
        return MOCK_TRANSCRIPT


class FasterWhisperSTTService(SpeechToTextService):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any | None = None

    def transcribe(self, audio_path: Path) -> str:
        model = self._get_model()
        try:
            segments, _info = model.transcribe(
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

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            faster_whisper = importlib.import_module("faster_whisper")
        except ImportError as exc:
            raise STTUnavailableError(
                "Local STT mode requires faster-whisper. "
                "Install backend/requirements-stt.txt or use STT_MODE=mock."
            ) from exc

        try:
            self._model = faster_whisper.WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
            )
        except Exception as exc:
            raise STTUnavailableError(
                f"Could not load local STT model {self.model_name!r}: {exc}"
            ) from exc
        return self._model


def get_stt_mode() -> str:
    return os.getenv("STT_MODE", DEFAULT_STT_MODE).strip().lower()


def get_stt_model() -> str:
    return os.getenv("STT_MODEL", DEFAULT_STT_MODEL).strip() or DEFAULT_STT_MODEL


def create_stt_service() -> SpeechToTextService:
    mode = get_stt_mode()
    return _create_stt_service(mode, get_stt_model())


@lru_cache(maxsize=4)
def _create_stt_service(mode: str, model_name: str) -> SpeechToTextService:
    logger.info(
        "Creating speech-to-text service: mode=%s model=%s",
        mode,
        model_name,
    )
    if mode == "mock":
        return MockSTTService()
    if mode == "local":
        return FasterWhisperSTTService(model_name)
    raise STTUnavailableError(
        f"Unsupported STT_MODE {mode!r}. Expected 'mock' or 'local'."
    )
