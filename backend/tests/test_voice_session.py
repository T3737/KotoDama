import asyncio
import io
import json
import os
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main
from app.orchestration.conversation_state import (
    ConversationState,
    ConversationStateMachine,
    InvalidStateTransition,
)
from app.orchestration.audio_turn import AudioTurnBuffer
from app.speech.stt_service import MockSTTService, SpeechToTextService, STTUnavailableError
from app.speech.vad_service import VADConfig


class FakeOllamaClient:
    async def chat(self, messages: list[dict[str, str]]) -> str:
        return f"Reply to: {messages[-1]['content']}"

    async def is_available(self) -> bool:
        return True


class SlowOllamaClient:
    async def chat(self, messages: list[dict[str, str]]) -> str:
        await asyncio.sleep(0.05)
        return f"Slow reply to: {messages[-1]['content']}"


class InspectingSTTService(SpeechToTextService):
    def __init__(self, transcript: str = "streamed hello") -> None:
        self.transcript = transcript
        self.wav_metadata: tuple[int, int, int, int] | None = None
        self.path = None

    def transcribe(self, audio_path):
        self.path = audio_path
        with wave.open(str(audio_path), "rb") as wav_file:
            self.wav_metadata = (
                wav_file.getframerate(),
                wav_file.getnchannels(),
                wav_file.getsampwidth(),
                wav_file.getnframes(),
            )
        return self.transcript


class UnavailableSTTService(SpeechToTextService):
    def transcribe(self, audio_path):
        raise STTUnavailableError("model missing")


class EmptySTTService(SpeechToTextService):
    def transcribe(self, audio_path):
        return ""


class SequenceVADStream:
    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = iter(probabilities)

    def probability(self, _pcm16_mono: bytes) -> float:
        return next(self._probabilities)


class MockVADService:
    backend = "mock_vad"
    sample_rate = 16000

    def __init__(self, probabilities: list[float], **overrides) -> None:
        settings = {
            "enabled": True,
            "model_path": Path("mock.onnx"),
            "threshold": 0.5,
            "min_speech_ms": 64,
            "end_silence_ms": 64,
            "no_speech_timeout_ms": 320,
            "max_turn_ms": 640,
            "pre_roll_ms": 32,
            "post_roll_ms": 32,
            "verbose_probabilities": False,
        }
        settings.update(overrides)
        self.config = VADConfig(**settings)
        self.probabilities = probabilities

    def create_stream(self):
        return SequenceVADStream(self.probabilities)

    def readiness(self):
        return {
            "enabled": True,
            "state": "ready",
            "backend": self.backend,
            "sample_rate": self.sample_rate,
            "error": None,
            "settings": self.config.public_settings(),
        }


def event(event_type: str, session_id: str = "test_player:haru", payload=None) -> dict:
    return {
        "type": event_type,
        "session_id": session_id,
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }


class VoiceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        main.session_store._sessions.clear()
        self.original_client = main.app.state.ollama_client
        self.original_stt_factory = main.app.state.stt_service_factory
        self.original_vad_factory = main.app.state.vad_service_factory
        main.app.state.ollama_client = FakeOllamaClient()
        self.stt = InspectingSTTService()
        main.app.state.stt_service_factory = lambda: self.stt
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.app.state.ollama_client = self.original_client
        main.app.state.stt_service_factory = self.original_stt_factory
        main.app.state.vad_service_factory = self.original_vad_factory

    def start_session(self, websocket) -> None:
        websocket.send_json(event("session.start", payload={"npc_id": "haru"}))
        ready = websocket.receive_json()
        state = websocket.receive_json()
        self.assertEqual(ready["type"], "session.ready")
        self.assertEqual(ready["payload"]["npc_id"], "haru")
        self.assertEqual(state["type"], "state.changed")
        self.assertEqual(state["payload"]["state"], "READY")

    def test_connection_start_and_player_text_round_trip(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            websocket.send_json(event("player.text", payload={"text": "Hello"}))
            generating = websocket.receive_json()
            final = websocket.receive_json()
            ready = websocket.receive_json()

            self.assertEqual(generating["type"], "state.changed")
            self.assertEqual(generating["payload"]["state"], "GENERATING")
            self.assertEqual(final["type"], "npc.text.final")
            self.assertEqual(final["payload"]["text"], "Reply to: Hello")
            self.assertEqual(ready["type"], "state.changed")
            self.assertEqual(ready["payload"]["state"], "READY")

    def test_readiness_reports_session_capabilities(self) -> None:
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["ollama"])
        self.assertEqual(body["stt_mode"], "mock")
        self.assertEqual(body["stt"]["state"], "ready")
        self.assertIn(body["vad"]["state"], {"not_loaded", "ready", "error"})
        self.assertEqual(body["vad"]["backend"], "silero_onnx")
        self.assertEqual(body["vad"]["sample_rate"], 16000)
        self.assertTrue(body["voice_websocket"])

    def test_malformed_json_returns_structured_error(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            websocket.send_text("{not-json")
            response = websocket.receive_json()
            self.assertEqual(response["type"], "error")
            self.assertEqual(response["payload"]["code"], "malformed_json")

    def test_unsupported_event_type_returns_structured_error(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            websocket.send_json(event("future.event"))
            response = websocket.receive_json()
            self.assertEqual(response["payload"]["code"], "unsupported_event")

    def start_audio(
        self, websocket, *, auto_send: bool = False, sample_rate: int = 48000
    ) -> dict:
        websocket.send_json(
            event(
                "audio.start",
                payload={
                    "sample_rate": sample_rate,
                    "channels": 1,
                    "encoding": "pcm_s16le",
                    "auto_send_transcript": auto_send,
                },
            )
        )
        listening = websocket.receive_json()
        ready = websocket.receive_json()
        self.assertEqual(listening["payload"]["state"], "LISTENING")
        self.assertEqual(ready["type"], "audio.ready")
        self.assertEqual(ready["payload"]["sample_rate"], sample_rate)
        self.assertEqual(ready["payload"]["channels"], 1)
        self.assertEqual(ready["payload"]["encoding"], "pcm_s16le")
        self.assertLessEqual(ready["payload"]["max_duration_ms"], 20000)
        configured_max = int(os.environ.get("VOICE_MAX_AUDIO_BYTES", 4 * 1024 * 1024))
        format_max = sample_rate * 2 * ready["payload"]["max_duration_ms"] // 1000
        self.assertEqual(ready["payload"]["max_bytes"], min(configured_max, format_max))
        return ready

    def test_streamed_audio_is_buffered_transcribed_and_cleaned_up(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x01\x00" * 960)
            websocket.send_json(event("audio.stop", payload={"reason": "player_released"}))
            responses = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(
            [response["type"] for response in responses],
            ["state.changed", "audio.received", "transcript.final", "state.changed"],
        )
        self.assertEqual(responses[0]["payload"]["state"], "TRANSCRIBING")
        self.assertEqual(responses[2]["payload"]["text"], "streamed hello")
        self.assertEqual(responses[2]["payload"]["size_bytes"], 1920)
        self.assertEqual(responses[2]["payload"]["received_bytes"], 1920)
        self.assertEqual(responses[2]["payload"]["stt_mode"], "unknown")
        self.assertFalse(responses[2]["payload"]["is_mock"])
        self.assertEqual(responses[2]["payload"]["metadata"]["model"], "unknown")
        self.assertEqual(responses[2]["payload"]["metadata"]["audio_duration_ms"], 20)
        self.assertTrue(responses[2]["payload"]["metadata"]["speech_detected"])
        self.assertTrue(responses[2]["event_id"])
        self.assertTrue(responses[2]["timestamp"])
        self.assertEqual(responses[3]["payload"]["state"], "READY")
        self.assertEqual(self.stt.wav_metadata, (48000, 1, 2, 960))
        self.assertIsNotNone(self.stt.path)
        self.assertFalse(self.stt.path.exists())

    def test_vad_auto_stops_once_and_discards_late_frames(self) -> None:
        main.app.state.vad_service_factory = lambda: MockVADService(
            [0.0, 0.9, 0.9, 0.0, 0.0]
        )
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            ready = self.start_audio(websocket, sample_rate=16000)
            self.assertTrue(ready["payload"]["vad_enabled"])
            for _index in range(5):
                websocket.send_bytes(b"\x01\x00" * 512)
            responses = [websocket.receive_json() for _ in range(7)]
            websocket.send_bytes(b"\x01\x00" * 512)
            websocket.send_json(event("ping"))
            pong = websocket.receive_json()

        self.assertEqual(
            [response["type"] for response in responses],
            [
                "vad.speech_started",
                "vad.speech_ended",
                "audio.auto_stopped",
                "state.changed",
                "audio.received",
                "transcript.final",
                "state.changed",
            ],
        )
        self.assertEqual(responses[2]["payload"]["reason"], "end_of_speech")
        self.assertEqual(
            sum(response["type"] == "transcript.final" for response in responses), 1
        )
        self.assertEqual(pong["type"], "pong")

    def test_vad_no_speech_timeout_auto_stops_without_transcription(self) -> None:
        main.app.state.vad_service_factory = lambda: MockVADService(
            [0.0, 0.0, 0.0], no_speech_timeout_ms=96
        )
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket, sample_rate=16000)
            for _index in range(3):
                websocket.send_bytes(b"\x00\x00" * 512)
            responses = [websocket.receive_json() for _ in range(3)]
        self.assertEqual(
            [response["type"] for response in responses],
            ["audio.auto_stopped", "error", "state.changed"],
        )
        self.assertEqual(responses[1]["payload"]["code"], "no_speech_timeout")

    def test_disconnect_during_vad_listening_clears_turn_state(self) -> None:
        main.app.state.vad_service_factory = lambda: MockVADService([0.9, 0.9])
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket, sample_rate=16000)
            websocket.send_bytes(b"\x01\x00" * 512)
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            ready = self.start_audio(websocket, sample_rate=16000)
            self.assertTrue(ready["payload"]["vad_enabled"])

    def test_manual_stop_remains_available_when_vad_is_unavailable(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            ready = self.start_audio(websocket)
            self.assertFalse(ready["payload"]["vad_enabled"])
            self.assertEqual(ready["payload"]["vad_warning"], "vad_unavailable")
            websocket.send_bytes(b"\x01\x00" * 400)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[2]["type"], "transcript.final")

    def test_manual_stop_after_vad_speech_start_transcribes(self) -> None:
        main.app.state.vad_service_factory = lambda: MockVADService([0.9, 0.9])
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket, sample_rate=16000)
            websocket.send_bytes(b"\x01\x00" * 512)
            websocket.send_bytes(b"\x01\x00" * 512)
            started = websocket.receive_json()
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(started["type"], "vad.speech_started")
        self.assertEqual(responses[2]["type"], "transcript.final")

    def test_manual_stop_before_vad_speech_start_cancels_cleanly(self) -> None:
        main.app.state.vad_service_factory = lambda: MockVADService([0.0])
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket, sample_rate=16000)
            websocket.send_bytes(b"\x00\x00" * 512)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[2]["payload"]["code"], "no_speech_detected")
        self.assertEqual(responses[3]["payload"]["state"], "READY")

    def test_empty_audio_turn_is_rejected_and_recovers(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[0]["payload"]["state"], "TRANSCRIBING")
        self.assertEqual(responses[1]["type"], "audio.received")
        self.assertEqual(responses[2]["payload"]["code"], "audio_too_short")
        self.assertEqual(responses[3]["payload"]["state"], "READY")

    def test_tiny_audio_turn_is_rejected_and_recovers(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x00\x00" * 50)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[1]["payload"]["received_bytes"], 100)
        self.assertEqual(responses[2]["payload"]["code"], "audio_too_short")
        self.assertEqual(responses[3]["payload"]["state"], "READY")

    def test_mock_transcript_is_labelled_in_event_metadata(self) -> None:
        main.app.state.stt_service_factory = MockSTTService
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x01\x00" * 400)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        transcript = responses[2]
        self.assertEqual(transcript["type"], "transcript.final")
        self.assertEqual(transcript["payload"]["stt_mode"], "mock")
        self.assertTrue(transcript["payload"]["is_mock"])

    def test_cancelled_audio_turn_is_cleaned_without_transcription(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x00\x00" * 400)
            websocket.send_json(event("audio.stop", payload={"reason": "cancelled"}))
            responses = [websocket.receive_json() for _ in range(3)]
        self.assertEqual(
            [response["type"] for response in responses],
            ["state.changed", "audio.received", "state.changed"],
        )
        self.assertIsNone(self.stt.path)

    def test_binary_frame_before_audio_start_is_rejected(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            websocket.send_bytes(b"\x00\x00" * 200)
            response = websocket.receive_json()
        self.assertEqual(response["payload"]["code"], "binary_out_of_order")

    def test_overlapping_audio_turn_is_rejected(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_json(
                event(
                    "audio.start",
                    payload={"sample_rate": 48000, "channels": 1, "encoding": "pcm_s16le"},
                )
            )
            response = websocket.receive_json()
        self.assertEqual(response["payload"]["code"], "invalid_event_order")

    def test_maximum_audio_size_is_enforced_and_recovers(self) -> None:
        old_limit = os.environ.get("VOICE_MAX_AUDIO_BYTES")
        os.environ["VOICE_MAX_AUDIO_BYTES"] = "512"
        try:
            with self.client.websocket_connect("/voice/session") as websocket:
                self.start_session(websocket)
                self.start_audio(websocket)
                websocket.send_bytes(b"\x00\x00" * 257)
                state = websocket.receive_json()
                response = websocket.receive_json()
            self.assertEqual(state["payload"]["state"], "READY")
            self.assertEqual(response["payload"]["code"], "audio_too_large")
        finally:
            if old_limit is None:
                os.environ.pop("VOICE_MAX_AUDIO_BYTES", None)
            else:
                os.environ["VOICE_MAX_AUDIO_BYTES"] = old_limit

    def test_local_stt_unavailable_is_structured_and_recovers(self) -> None:
        main.app.state.stt_service_factory = lambda: UnavailableSTTService()
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x00\x00" * 400)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[2]["payload"]["code"], "stt_unavailable")
        self.assertEqual(responses[3]["payload"]["state"], "READY")

    def test_empty_stt_result_is_no_speech_and_recovers(self) -> None:
        main.app.state.stt_service_factory = EmptySTTService
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x01\x00" * 400)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[2]["payload"]["code"], "no_speech_detected")
        self.assertEqual(responses[3]["payload"]["state"], "READY")

    def test_transcript_requires_confirmation_even_if_auto_send_is_requested(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket, auto_send=True)
            websocket.send_bytes(b"\x01\x00" * 400)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(
            [response["type"] for response in responses],
            [
                "state.changed",
                "audio.received",
                "transcript.final",
                "state.changed",
            ],
        )
        self.assertFalse(responses[2]["payload"]["auto_sent"])
        self.assertEqual(responses[3]["payload"]["state"], "READY")

    def test_disconnect_during_audio_turn_does_not_poison_next_session(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x00\x00" * 400)
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            self.start_audio(websocket)
            websocket.send_bytes(b"\x00\x00" * 400)
            websocket.send_json(event("audio.stop"))
            responses = [websocket.receive_json() for _ in range(4)]
        self.assertEqual(responses[2]["type"], "transcript.final")

    def test_player_text_before_start_is_rejected(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            websocket.send_json(event("player.text", payload={"text": "Too soon"}))
            response = websocket.receive_json()
            self.assertEqual(response["payload"]["code"], "session_not_started")

    def test_overlapping_player_turn_is_rejected(self) -> None:
        main.app.state.ollama_client = SlowOllamaClient()
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            websocket.send_json(event("player.text", payload={"text": "First"}))
            websocket.send_json(event("player.text", payload={"text": "Second"}))
            responses = [websocket.receive_json() for _ in range(4)]
            codes = [
                response["payload"].get("code")
                for response in responses
                if response["type"] == "error"
            ]
            self.assertIn("turn_in_progress", codes)
            states = [
                response["payload"]["state"]
                for response in responses
                if response["type"] == "state.changed"
            ]
            self.assertEqual(states, ["GENERATING", "READY"])

    def test_ping_and_clean_disconnect(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            self.start_session(websocket)
            websocket.send_json(event("ping"))
            self.assertEqual(websocket.receive_json()["type"], "pong")
            websocket.send_json(event("session.close"))
            closed = websocket.receive_json()
            self.assertEqual(closed["payload"]["state"], "DISCONNECTED")


class ConversationStateMachineTests(unittest.TestCase):
    def test_invalid_transition_is_rejected(self) -> None:
        machine = ConversationStateMachine()
        with self.assertRaises(InvalidStateTransition):
            machine.transition(ConversationState.GENERATING)

    def test_pcm_buffer_constructs_correct_wav(self) -> None:
        turn = AudioTurnBuffer(48000, 1, "pcm_s16le", 20.0, 1024)
        turn.append(b"\x00\x00\xff\x7f")
        with wave.open(io.BytesIO(turn.to_wav_bytes()), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 48000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.readframes(2), b"\x00\x00\xff\x7f")


if __name__ == "__main__":
    unittest.main()
