from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.speech.vad_service import (
    PCM16MonoResampler,
    VADConfig,
    VADStream,
    VAD_WINDOW_SAMPLES,
)


logger = logging.getLogger(__name__)
WINDOW_MS = round(VAD_WINDOW_SAMPLES / 16_000 * 1000)


@dataclass(frozen=True, slots=True)
class VADSignal:
    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VADOutcome:
    reason: str
    should_transcribe: bool
    speech_duration_ms: int
    silence_duration_ms: int


class VADTurnDetector:
    WAITING_FOR_SPEECH = "WAITING_FOR_SPEECH"
    SPEECH_ACTIVE = "SPEECH_ACTIVE"
    ENDING_SPEECH = "ENDING_SPEECH"
    TURN_COMPLETE = "TURN_COMPLETE"

    def __init__(
        self,
        config: VADConfig,
        stream: VADStream,
        incoming_sample_rate: int,
    ) -> None:
        self.config = config
        self._stream = stream
        self._resampler = PCM16MonoResampler(incoming_sample_rate)
        self.incoming_sample_rate = incoming_sample_rate
        self.state = self.WAITING_FOR_SPEECH
        self._vad_bytes = bytearray()
        self._processed_ms = 0
        self._candidate_speech_ms = 0
        self._candidate_start_ms = 0
        self._speech_start_ms: int | None = None
        self._last_speech_end_ms: int | None = None
        self._silence_ms = 0
        self._received_input_bytes = 0

    @property
    def speech_started(self) -> bool:
        return self._speech_start_ms is not None

    @property
    def elapsed_input_ms(self) -> int:
        return round(self._received_input_bytes / (self.incoming_sample_rate * 2) * 1000)

    def process(self, pcm16_mono: bytes) -> tuple[list[VADSignal], VADOutcome | None]:
        if self.state == self.TURN_COMPLETE:
            return [], None
        self._received_input_bytes += len(pcm16_mono)
        self._vad_bytes.extend(self._resampler.process(pcm16_mono))
        signals: list[VADSignal] = []
        window_bytes = VAD_WINDOW_SAMPLES * 2

        while len(self._vad_bytes) >= window_bytes and self.state != self.TURN_COMPLETE:
            window = bytes(self._vad_bytes[:window_bytes])
            del self._vad_bytes[:window_bytes]
            probability = self._stream.probability(window)
            window_start_ms = self._processed_ms
            self._processed_ms += WINDOW_MS
            if self.config.verbose_probabilities:
                logger.debug(
                    "vad_probability elapsed_ms=%d probability=%.4f",
                    self._processed_ms,
                    probability,
                )
            is_speech = probability >= self.config.threshold
            signal = self._update_speech_state(is_speech, window_start_ms)
            if signal is not None:
                signals.append(signal)

            outcome = self._timeout_outcome()
            if outcome is not None:
                self.state = self.TURN_COMPLETE
                if outcome.should_transcribe and outcome.reason != "end_of_speech":
                    signals.append(self._speech_ended_signal(outcome))
                return signals, outcome

        return signals, None

    def manual_outcome(self) -> VADOutcome:
        self.state = self.TURN_COMPLETE
        if not self.speech_started:
            return VADOutcome("manual_no_speech", False, 0, self._silence_ms)
        return VADOutcome(
            "manual_stop",
            True,
            self.speech_duration_ms,
            self._silence_ms,
        )

    def retained_pcm(self, original_pcm: bytes) -> bytes:
        if not self.speech_started:
            return original_pcm
        start_ms = max(0, (self._speech_start_ms or 0) - self.config.pre_roll_ms)
        speech_end_ms = self._last_speech_end_ms or self.elapsed_input_ms
        end_ms = min(self.elapsed_input_ms, speech_end_ms + self.config.post_roll_ms)
        bytes_per_ms = self.incoming_sample_rate * 2 / 1000
        start_byte = int(start_ms * bytes_per_ms) // 2 * 2
        end_byte = int(end_ms * bytes_per_ms) // 2 * 2
        return original_pcm[start_byte:end_byte]

    @property
    def speech_duration_ms(self) -> int:
        if self._speech_start_ms is None or self._last_speech_end_ms is None:
            return 0
        return max(0, self._last_speech_end_ms - self._speech_start_ms)

    @property
    def metrics(self) -> dict[str, int | float | str | None]:
        return {
            "state": self.state,
            "speech_start_ms": self._speech_start_ms,
            "speech_end_ms": self._last_speech_end_ms,
            "speech_duration_ms": self.speech_duration_ms,
            "silence_duration_ms": self._silence_ms,
            "threshold": self.config.threshold,
        }

    def _update_speech_state(
        self, is_speech: bool, window_start_ms: int
    ) -> VADSignal | None:
        if not self.speech_started:
            if is_speech:
                if self._candidate_speech_ms == 0:
                    self._candidate_start_ms = window_start_ms
                self._candidate_speech_ms += WINDOW_MS
                if self._candidate_speech_ms >= self.config.min_speech_ms:
                    self._speech_start_ms = self._candidate_start_ms
                    self._last_speech_end_ms = self._processed_ms
                    self._silence_ms = 0
                    self.state = self.SPEECH_ACTIVE
                    return VADSignal(
                        "vad.speech_started",
                        {"elapsed_ms": self._speech_start_ms},
                    )
            else:
                self._candidate_speech_ms = 0
            return None

        if is_speech:
            self._last_speech_end_ms = self._processed_ms
            self._silence_ms = 0
            self.state = self.SPEECH_ACTIVE
            return None

        self._silence_ms += WINDOW_MS
        self.state = self.ENDING_SPEECH
        if self._silence_ms >= self.config.end_silence_ms:
            outcome = VADOutcome(
                "end_of_speech",
                True,
                self.speech_duration_ms,
                self._silence_ms,
            )
            self.state = self.TURN_COMPLETE
            return self._speech_ended_signal(outcome)
        return None

    def _timeout_outcome(self) -> VADOutcome | None:
        if self.state == self.TURN_COMPLETE:
            return VADOutcome(
                "end_of_speech",
                True,
                self.speech_duration_ms,
                self._silence_ms,
            )
        if not self.speech_started and self._processed_ms >= self.config.no_speech_timeout_ms:
            return VADOutcome("no_speech_timeout", False, 0, self._processed_ms)
        if self._processed_ms >= self.config.max_turn_ms:
            return VADOutcome(
                "maximum_turn_duration",
                self.speech_started,
                self.speech_duration_ms,
                self._silence_ms,
            )
        return None

    def _speech_ended_signal(self, outcome: VADOutcome) -> VADSignal:
        return VADSignal(
            "vad.speech_ended",
            {
                "speech_duration_ms": outcome.speech_duration_ms,
                "silence_duration_ms": outcome.silence_duration_ms,
                "reason": outcome.reason,
            },
        )
