from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from time import monotonic


SUPPORTED_ENCODING = "pcm_s16le"
SUPPORTED_SAMPLE_RATES = frozenset(
    {8_000, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000, 88_200, 96_000}
)


class AudioTurnError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class AudioTurnBuffer:
    sample_rate: int
    channels: int
    encoding: str
    max_duration_seconds: float
    max_bytes: int
    started_at: float = field(default_factory=monotonic)
    last_frame_at: float = field(default_factory=monotonic)
    data: bytearray = field(default_factory=bytearray)

    def __post_init__(self) -> None:
        if self.encoding != SUPPORTED_ENCODING:
            raise AudioTurnError("unsupported_audio_format", "Only pcm_s16le audio is supported.")
        if self.channels != 1:
            raise AudioTurnError("unsupported_audio_format", "Streamed audio must be mono.")
        if self.sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise AudioTurnError(
                "unsupported_sample_rate",
                f"Unsupported sample rate {self.sample_rate}. Use a standard rate up to 96000 Hz.",
            )

    @property
    def received_bytes(self) -> int:
        return len(self.data)

    @property
    def duration_ms(self) -> int:
        bytes_per_second = self.sample_rate * self.channels * 2
        return round(self.received_bytes / bytes_per_second * 1000)

    def append(self, frame: bytes) -> None:
        if not frame:
            return
        if len(frame) % 2:
            raise AudioTurnError(
                "invalid_audio_frame", "PCM16 audio frames must contain an even number of bytes."
            )
        new_size = self.received_bytes + len(frame)
        duration_limit = int(self.sample_rate * self.channels * 2 * self.max_duration_seconds)
        if new_size > self.max_bytes or new_size > duration_limit:
            raise AudioTurnError(
                "audio_too_large",
                f"Audio turn exceeds the {self.max_duration_seconds:g} second safety limit.",
            )
        self.data.extend(frame)
        self.last_frame_at = monotonic()

    def to_wav_bytes(self) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.data)
        return output.getvalue()

    def clear(self) -> None:
        self.data.clear()
