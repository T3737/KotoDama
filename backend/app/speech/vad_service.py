from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Protocol


logger = logging.getLogger(__name__)
VAD_SAMPLE_RATE = 16_000
VAD_WINDOW_SAMPLES = 512


class VADUnavailableError(RuntimeError):
    pass


class VADStream(Protocol):
    def probability(self, pcm16_mono: bytes) -> float: ...


@dataclass(frozen=True, slots=True)
class VADConfig:
    enabled: bool
    model_path: Path
    threshold: float = 0.50
    min_speech_ms: int = 250
    end_silence_ms: int = 700
    no_speech_timeout_ms: int = 5000
    max_turn_ms: int = 20_000
    pre_roll_ms: int = 250
    post_roll_ms: int = 150
    verbose_probabilities: bool = False

    def public_settings(self) -> dict[str, bool | float | int]:
        return {
            "threshold": self.threshold,
            "min_speech_ms": self.min_speech_ms,
            "end_silence_ms": self.end_silence_ms,
            "no_speech_timeout_ms": self.no_speech_timeout_ms,
            "max_turn_ms": self.max_turn_ms,
            "pre_roll_ms": self.pre_roll_ms,
            "post_roll_ms": self.post_roll_ms,
        }


class VADService:
    backend = "silero_onnx"
    sample_rate = VAD_SAMPLE_RATE

    def __init__(self, config: VADConfig) -> None:
        self.config = config

    def prepare(self) -> None:
        raise NotImplementedError

    def create_stream(self) -> VADStream:
        raise NotImplementedError

    def readiness(self) -> dict[str, Any]:
        raise NotImplementedError


class DisabledVADService(VADService):
    backend = "disabled"

    def prepare(self) -> None:
        return

    def create_stream(self) -> VADStream:
        raise VADUnavailableError("Automatic speech ending is disabled; use Stop.")

    def readiness(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "state": "disabled",
            "backend": self.backend,
            "sample_rate": self.sample_rate,
            "model_path": None,
            "error": None,
            "settings": self.config.public_settings(),
        }


class SileroOnnxVADService(VADService):
    def __init__(self, config: VADConfig) -> None:
        super().__init__(config)
        self._session: Any | None = None
        self._load_lock = Lock()
        self._state = "not_loaded"
        self._error: str | None = None
        self._load_ms: float | None = None

    def prepare(self) -> None:
        if self._session is not None:
            return
        if self._state == "error":
            raise VADUnavailableError(self._error or "Local VAD is unavailable.")
        with self._load_lock:
            if self._session is not None:
                return
            if self._state == "error":
                raise VADUnavailableError(self._error or "Local VAD is unavailable.")
            self._state = "loading"
            started_at = perf_counter()
            try:
                if not self.config.model_path.is_file():
                    raise FileNotFoundError(self.config.model_path)
                import onnxruntime

                self._session = onnxruntime.InferenceSession(
                    str(self.config.model_path),
                    providers=["CPUExecutionProvider"],
                )
                _validate_silero_inputs(self._session)
            except Exception as exc:
                self._session = None
                self._state = "error"
                self._error = (
                    "Local Silero VAD model is unavailable at "
                    f"{self.config.model_path}. Install it before gameplay. ({exc})"
                )
                raise VADUnavailableError(self._error) from exc
            self._load_ms = (perf_counter() - started_at) * 1000
            self._state = "ready"
            logger.info(
                "vad_model_loaded backend=%s load_ms=%.1f",
                self.backend,
                self._load_ms,
            )

    def create_stream(self) -> VADStream:
        self.prepare()
        assert self._session is not None
        return SileroOnnxVADStream(self._session)

    def readiness(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "state": self._state,
            "backend": self.backend,
            "sample_rate": self.sample_rate,
            "model_path": str(self.config.model_path),
            "load_ms": round(self._load_ms, 1) if self._load_ms is not None else None,
            "error": self._error,
            "settings": self.config.public_settings(),
        }


class SileroOnnxVADStream:
    def __init__(self, session: Any) -> None:
        import numpy as np

        self._np = np
        self._session = session
        self._input_names = {item.name for item in session.get_inputs()}
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def probability(self, pcm16_mono: bytes) -> float:
        samples = self._np.frombuffer(pcm16_mono, dtype="<i2").astype(self._np.float32)
        samples /= 32768.0
        audio = samples.reshape(1, -1)
        sample_rate = self._np.array(VAD_SAMPLE_RATE, dtype=self._np.int64)
        if "state" in self._input_names:
            outputs = self._session.run(
                None, {"input": audio, "state": self._state, "sr": sample_rate}
            )
            probability, self._state = outputs[0], outputs[1]
        else:
            outputs = self._session.run(
                None,
                {"input": audio, "sr": sample_rate, "h": self._h, "c": self._c},
            )
            probability, self._h, self._c = outputs[0], outputs[1], outputs[2]
        return float(probability.reshape(-1)[0])


class PCM16MonoResampler:
    """Stateful FFmpeg/PyAV resampling used only for the VAD decision stream."""

    def __init__(self, source_rate: int, target_rate: int = VAD_SAMPLE_RATE) -> None:
        if source_rate <= 0:
            raise ValueError("source_rate must be positive")
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._passthrough = source_rate == target_rate
        self._resampler: Any | None = None
        if not self._passthrough:
            try:
                import av

                self._resampler = av.AudioResampler(
                    format="s16", layout="mono", rate=target_rate
                )
            except Exception as exc:
                raise VADUnavailableError(
                    "Local VAD resampling requires PyAV from requirements-vad.txt."
                ) from exc

    def process(self, pcm16_mono: bytes) -> bytes:
        if not pcm16_mono:
            return b""
        if len(pcm16_mono) % 2:
            raise ValueError("PCM16 input must contain an even number of bytes")
        if self._passthrough:
            return pcm16_mono
        import av
        import numpy as np

        samples = np.frombuffer(pcm16_mono, dtype="<i2").copy().reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = self.source_rate
        return b"".join(
            output.to_ndarray().astype("<i2", copy=False).tobytes()
            for output in self._resampler.resample(frame)
        )


def get_vad_config() -> VADConfig:
    backend_root = Path(__file__).resolve().parents[2]
    default_model = backend_root / "models" / "silero_vad.onnx"
    return VADConfig(
        enabled=_env_bool("VAD_ENABLED", True),
        model_path=Path(os.getenv("VAD_MODEL_PATH", str(default_model))).expanduser().resolve(),
        threshold=float(os.getenv("VAD_THRESHOLD", "0.50")),
        min_speech_ms=int(os.getenv("VAD_MIN_SPEECH_MS", "250")),
        end_silence_ms=int(os.getenv("VAD_END_SILENCE_MS", "700")),
        no_speech_timeout_ms=int(os.getenv("VAD_NO_SPEECH_TIMEOUT_MS", "5000")),
        max_turn_ms=int(os.getenv("VAD_MAX_TURN_MS", "20000")),
        pre_roll_ms=int(os.getenv("VAD_PRE_ROLL_MS", "250")),
        post_roll_ms=int(os.getenv("VAD_POST_ROLL_MS", "150")),
        verbose_probabilities=_env_bool("VAD_VERBOSE", False),
    )


_SERVICE_CACHE: dict[VADConfig, VADService] = {}
_SERVICE_CACHE_LOCK = Lock()


def create_vad_service(config: VADConfig | None = None) -> VADService:
    selected = config or get_vad_config()
    with _SERVICE_CACHE_LOCK:
        service = _SERVICE_CACHE.get(selected)
        if service is None:
            service = (
                SileroOnnxVADService(selected)
                if selected.enabled
                else DisabledVADService(selected)
            )
            _SERVICE_CACHE[selected] = service
        return service


def get_vad_readiness() -> dict[str, Any]:
    return create_vad_service().readiness()


def clear_vad_service_cache() -> None:
    with _SERVICE_CACHE_LOCK:
        _SERVICE_CACHE.clear()


def _validate_silero_inputs(session: Any) -> None:
    names = {item.name for item in session.get_inputs()}
    if not ({"input", "sr", "state"} <= names or {"input", "sr", "h", "c"} <= names):
        raise VADUnavailableError(f"Unsupported Silero ONNX inputs: {sorted(names)}")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
