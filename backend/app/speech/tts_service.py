from __future__ import annotations

import importlib
import importlib.util
import io
import math
import os
import re
import secrets
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TTSError(RuntimeError):
    code = "tts_failed"


class TTSUnavailableError(TTSError):
    code = "tts_unavailable"


class TTSModelMissingError(TTSUnavailableError):
    code = "tts_model_missing"


class TTSConfigMissingError(TTSUnavailableError):
    code = "tts_config_missing"


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    duration_ms: int
    mode: str
    voice: str


@dataclass(frozen=True)
class TTSAudioEntry:
    audio_id: str
    session_id: str
    audio_bytes: bytes
    duration_ms: int
    created_at: float
    expires_at: float


class TemporaryTTSAudioStore:
    def __init__(self, ttl_seconds: float = 120.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, TTSAudioEntry] = {}
        self._lock = threading.Lock()

    def put(self, session_id: str, audio_bytes: bytes, duration_ms: int) -> TTSAudioEntry:
        self.cleanup_expired()
        now = time.monotonic()
        audio_id = secrets.token_urlsafe(24)
        entry = TTSAudioEntry(
            audio_id=audio_id,
            session_id=session_id,
            audio_bytes=audio_bytes,
            duration_ms=duration_ms,
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._entries[audio_id] = entry
        return entry

    def pop(self, audio_id: str) -> TTSAudioEntry | None:
        self.cleanup_expired()
        with self._lock:
            return self._entries.pop(audio_id, None)

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            stale_ids = [
                audio_id
                for audio_id, entry in self._entries.items()
                if entry.session_id == session_id
            ]
            for audio_id in stale_ids:
                self._entries.pop(audio_id, None)

    def cleanup_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            stale_ids = [
                audio_id
                for audio_id, entry in self._entries.items()
                if entry.expires_at <= now
            ]
            for audio_id in stale_ids:
                self._entries.pop(audio_id, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class TextToSpeechService:
    mode = "disabled"
    voice = "disabled"

    def prepare(self) -> None:
        pass

    def synthesize(self, text: str) -> TTSResult:
        raise TTSUnavailableError("NPC voice is unavailable. Text response shown instead.")

    def readiness(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "state": "disabled",
            "voice": self.voice,
            "error": None,
        }


class DisabledTTSService(TextToSpeechService):
    mode = "disabled"
    voice = "disabled"


class MockTTSService(TextToSpeechService):
    mode = "mock"
    voice = "mock-tone"

    def synthesize(self, text: str) -> TTSResult:
        clean_text = sanitize_tts_text(text)
        duration_ms = max(350, min(1800, 350 + len(clean_text) * 18))
        audio_bytes = _tone_wav(duration_ms=duration_ms)
        return TTSResult(audio_bytes, duration_ms, self.mode, self.voice)

    def readiness(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "state": "ready",
            "voice": self.voice,
            "error": None,
        }


class PiperTTSService(TextToSpeechService):
    mode = "local"

    def __init__(
        self,
        model_path: str | None = None,
        config_path: str | None = None,
    ) -> None:
        self.model_path = resolve_backend_path(
            model_path or os.getenv("TTS_VOICE_MODEL", "")
        )
        self.config_path = resolve_backend_path(
            config_path or os.getenv("TTS_VOICE_CONFIG", "")
        )
        self.voice = self.model_path.stem if self.model_path.name else "unknown"
        self._voice: Any | None = None
        self._state = "not_loaded"
        self._error: str | None = None
        self._lock = threading.Lock()

    def prepare(self) -> None:
        with self._lock:
            if self._voice is not None:
                self._state = "ready"
                return
            self._state = "loading"
            self._error = None
            try:
                self._voice = self._load_voice()
            except TTSUnavailableError as exc:
                self._state = "error"
                self._error = str(exc)
                raise
            except Exception as exc:
                self._state = "error"
                self._error = str(exc)
                raise TTSUnavailableError(f"Local Piper voice failed to load: {exc}") from exc
            self._state = "ready"

    def synthesize(self, text: str) -> TTSResult:
        clean_text = sanitize_tts_text(text)
        if not clean_text:
            raise TTSError("NPC response had no speakable text.")
        self.prepare()
        assert self._voice is not None
        try:
            audio_bytes = synthesize_piper_wav(self._voice, clean_text)
            validate_wav_audio(audio_bytes)
        except Exception as exc:
            raise TTSError(f"Local Piper synthesis failed: {exc}") from exc
        return TTSResult(
            audio_bytes=audio_bytes,
            duration_ms=wav_duration_ms(audio_bytes),
            mode=self.mode,
            voice=self.voice,
        )

    def readiness(self) -> dict[str, Any]:
        state = self._state
        error = self._error
        if state == "not_loaded":
            if not self.model_path.is_file():
                state = "error"
                error = f"Local voice model is not installed: {self.model_path}"
            elif not self.config_path.is_file():
                state = "error"
                error = f"Local voice config is not installed: {self.config_path}"
            elif not _piper_dependency_available():
                state = "error"
                error = (
                    "Piper is not installed. Install optional TTS dependencies with "
                    "python -m pip install -r requirements-tts.txt"
                )
        return {
            "mode": self.mode,
            "state": state,
            "voice": self.voice,
            "model_path": str(self.model_path),
            "config_path": str(self.config_path),
            "error": error,
        }

    def _load_voice(self) -> Any:
        if not self.model_path.is_file():
            raise TTSModelMissingError(
                f"Local voice model is not installed: {self.model_path}"
            )
        if not self.config_path.is_file():
            raise TTSConfigMissingError(
                f"Local voice config is not installed: {self.config_path}"
            )
        try:
            piper_voice = importlib.import_module("piper.voice")
        except ModuleNotFoundError as exc:
            raise TTSUnavailableError(
                "Piper is not installed. Install optional TTS dependencies with "
                "python -m pip install -r requirements-tts.txt"
            ) from exc
        return piper_voice.PiperVoice.load(
            str(self.model_path),
            config_path=str(self.config_path),
        )


_cached_tts_service: TextToSpeechService | None = None
_tts_cache_lock = threading.Lock()


def create_tts_service() -> TextToSpeechService:
    global _cached_tts_service
    with _tts_cache_lock:
        if _cached_tts_service is not None:
            return _cached_tts_service
        mode = get_tts_mode()
        if mode == "disabled":
            _cached_tts_service = DisabledTTSService()
        elif mode == "mock":
            _cached_tts_service = MockTTSService()
        elif mode == "local":
            _cached_tts_service = PiperTTSService()
        else:
            _cached_tts_service = DisabledTTSService()
        return _cached_tts_service


def clear_tts_service_cache() -> None:
    global _cached_tts_service
    with _tts_cache_lock:
        _cached_tts_service = None


def get_tts_mode() -> str:
    mode = os.getenv("TTS_MODE", "disabled").strip().lower()
    return mode if mode in {"disabled", "mock", "local"} else "disabled"


def get_tts_readiness() -> dict[str, Any]:
    return create_tts_service().readiness()


def tts_debug_enabled() -> bool:
    return os.getenv("TTS_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}


def _piper_dependency_available() -> bool:
    try:
        return importlib.util.find_spec("piper.voice") is not None
    except ModuleNotFoundError:
        return False


def tts_startup_summary(service: TextToSpeechService) -> dict[str, Any]:
    readiness = service.readiness()
    model_path = Path(str(readiness.get("model_path", "")))
    config_path = Path(str(readiness.get("config_path", "")))
    return {
        "mode": readiness.get("mode", service.mode),
        "model_path": str(model_path) if str(model_path) != "." else "",
        "config_path": str(config_path) if str(config_path) != "." else "",
        "model_exists": model_path.is_file() if str(model_path) != "." else False,
        "config_exists": config_path.is_file() if str(config_path) != "." else False,
        "state": readiness.get("state", "disabled"),
    }


def sanitize_tts_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"```(?:\w+)?\s*|\s*```", "", cleaned)
    cleaned = re.sub(r"^\s*[\[{].*?(?:text|dialogue|response)\"?\s*:\s*\"([^\"]+)\".*[\]}]\s*$", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\[[^\]]+\]", "", cleaned)
    cleaned = re.sub(r"\{[^{}]+\}", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = cleaned.replace("\\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().strip('"')


def resolve_backend_path(raw_path: str) -> Path:
    if not raw_path:
        return Path("")
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent
    candidates = [
        Path.cwd() / path,
        backend_root / path,
        repo_root / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if raw_path.replace("\\", "/").startswith("backend/"):
        return (repo_root / path).resolve()
    return (backend_root / path).resolve()


def wav_duration_ms(audio_bytes: bytes) -> int:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
        if rate <= 0:
            return 0
        return round(frames / rate * 1000)


def synthesize_piper_wav(voice: Any, text: str) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        if hasattr(voice, "synthesize_wav"):
            voice.synthesize_wav(text, wav_file)
        else:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(_piper_sample_rate(voice))
            voice.synthesize(text, wav_file)
    return output.getvalue()


def validate_wav_audio(audio_bytes: bytes) -> None:
    if not audio_bytes:
        raise TTSError("Piper returned empty audio.")
    if not audio_bytes.startswith(b"RIFF") or audio_bytes[8:12] != b"WAVE":
        raise TTSError("Piper returned audio without a RIFF/WAVE header.")
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        if wav_file.getnchannels() < 1:
            raise TTSError("Piper returned WAV audio without channels.")
        if wav_file.getsampwidth() < 1:
            raise TTSError("Piper returned WAV audio without a valid sample width.")
        if wav_file.getframerate() <= 0:
            raise TTSError("Piper returned WAV audio without a valid sample rate.")
        if wav_file.getnframes() <= 0:
            raise TTSError("Piper returned WAV audio without frames.")


def _piper_sample_rate(voice: Any) -> int:
    config = getattr(voice, "config", None)
    sample_rate = getattr(config, "sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate
    return 22050


def _tone_wav(duration_ms: int, sample_rate: int = 16000) -> bytes:
    total_frames = max(1, round(sample_rate * duration_ms / 1000))
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total_frames):
            sample = int(1200 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate))
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(frames))
    return output.getvalue()
