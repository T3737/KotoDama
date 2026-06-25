import asyncio
import importlib
import io
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.game.npc_profiles import NpcProfileError, load_npc_profile
from app import main
from app.speech.stt_service import (
    FasterWhisperSTTService,
    STTUnavailableError,
    clear_stt_service_cache,
)


class FakeOllamaClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "Profile-specific test reply."


class NpcRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        main.session_store._sessions.clear()
        self.client = TestClient(main.app)
        self.original_client = main.ollama_client
        self.fake_client = FakeOllamaClient()
        main.ollama_client = self.fake_client

    def tearDown(self) -> None:
        main.ollama_client = self.original_client

    def test_profiles_are_distinct(self) -> None:
        aiko = load_npc_profile("aiko")
        haru = load_npc_profile("haru")
        emi = load_npc_profile("emi")
        self.assertNotEqual(aiko["role"], haru["role"])
        self.assertNotEqual(haru["role"], emi["role"])

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(NpcProfileError):
            load_npc_profile("unknown")

    def test_structured_response_and_private_prompt(self) -> None:
        request = main.NpcChatRequest(
            npc_id="haru",
            session_id="default_save:haru",
            player_message="How much is this?",
            level_id="level_02",
            npc_state={
                "known_player_facts": [
                    {"fact": "Player asked Haru about apples.", "visibility": "private"}
                ]
            },
            visible_world_facts=[
                {"fact": "The player has entered Level 2.", "visibility": "world"}
            ],
        )
        response = asyncio.run(main.npc_chat(request))
        self.assertEqual(response.npc_id, "haru")
        self.assertEqual(response.dialogue, response.npc_text)
        system_prompt = self.fake_client.messages[0]["content"]
        self.assertIn("busy market shopkeeper", system_prompt)
        self.assertIn("Player asked Haru about apples", system_prompt)
        self.assertNotIn("Aiko lives", system_prompt)

    def test_unknown_npc_returns_404(self) -> None:
        request = main.NpcChatRequest(
            npc_id="unknown",
            session_id="default_save:unknown",
            player_message="Hello",
        )
        with self.assertRaises(HTTPException) as context:
            asyncio.run(main.npc_chat(request))
        self.assertEqual(context.exception.status_code, 404)

    def test_legacy_request_remains_supported(self) -> None:
        request = main.NpcChatRequest(
            session_id="legacy_aiko",
            player_text="Hello",
            target_language="Japanese",
            npc_name="Aiko",
            scene_context="Legacy test.",
        )
        response = asyncio.run(main.npc_chat(request))
        self.assertEqual(response.npc_id, "aiko")
        self.assertEqual(response.npc_text, "Profile-specific test reply.")

    def test_http_npc_chat_route_remains_supported(self) -> None:
        response = self.client.post(
            "/npc/chat",
            json={
                "session_id": "http_test:haru",
                "npc_id": "haru",
                "player_message": "Hello over HTTP",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dialogue"], "Profile-specific test reply.")

    def test_session_keys_are_forced_into_npc_namespaces(self) -> None:
        self.assertEqual(
            main._npc_session_key("default_save:aiko", "aiko"),
            "default_save:aiko",
        )
        self.assertEqual(
            main._npc_session_key("default_save:aiko", "haru"),
            "default_save:aiko:haru",
        )


class SpeechTranscriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)
        self.original_mode = os.environ.get("STT_MODE")
        self.original_model = os.environ.get("STT_MODEL")
        os.environ["STT_MODE"] = "mock"
        os.environ.pop("STT_MODEL", None)

    def tearDown(self) -> None:
        if self.original_mode is None:
            os.environ.pop("STT_MODE", None)
        else:
            os.environ["STT_MODE"] = self.original_mode
        if self.original_model is None:
            os.environ.pop("STT_MODEL", None)
        else:
            os.environ["STT_MODEL"] = self.original_model

    def test_mock_transcription(self) -> None:
        response = self.client.post(
            "/speech/transcribe",
            files={"file": ("voice.wav", b"not-real-audio", "audio/wav")},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["transcript"], "i would like to learn japanese")
        self.assertEqual(body["language"], "en")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["metadata"]["model"], "mock")
        self.assertEqual(body["metadata"]["mode"], "mock")
        self.assertTrue(body["metadata"]["speech_detected"])
        self.assertIsInstance(body["metadata"]["transcription_ms"], int)

    def test_empty_audio_is_rejected(self) -> None:
        response = self.client.post(
            "/speech/transcribe",
            files={"file": ("voice.ogg", b"", "audio/ogg")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "no_audio")
        self.assertIn("empty", response.json()["detail"]["message"].lower())

    def test_silent_local_wav_has_structured_no_speech_error(self) -> None:
        wav_bytes = io.BytesIO()
        with wave.open(wav_bytes, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 1600)
        old_mode = os.environ.get("STT_MODE")
        os.environ["STT_MODE"] = "local"
        clear_stt_service_cache()
        try:
            response = self.client.post(
                "/speech/transcribe",
                files={"file": ("silence.wav", wav_bytes.getvalue(), "audio/wav")},
            )
        finally:
            if old_mode is None:
                os.environ.pop("STT_MODE", None)
            else:
                os.environ["STT_MODE"] = old_mode
            clear_stt_service_cache()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "no_speech_detected")

    def test_malformed_local_wav_has_structured_error(self) -> None:
        old_mode = os.environ.get("STT_MODE")
        os.environ["STT_MODE"] = "local"
        clear_stt_service_cache()
        try:
            response = self.client.post(
                "/speech/transcribe",
                files={"file": ("broken.wav", b"not a wav", "audio/wav")},
            )
        finally:
            if old_mode is None:
                os.environ.pop("STT_MODE", None)
            else:
                os.environ["STT_MODE"] = old_mode
            clear_stt_service_cache()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "malformed_audio")

    def test_unsupported_audio_extension_is_rejected(self) -> None:
        response = self.client.post(
            "/speech/transcribe",
            files={"file": ("voice.txt", b"audio", "text/plain")},
        )
        self.assertEqual(response.status_code, 415)

    def test_local_mode_missing_dependency_is_clear(self) -> None:
        service = FasterWhisperSTTService("tiny.en")
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            with patch.object(
                importlib,
                "import_module",
                side_effect=ModuleNotFoundError("faster_whisper"),
            ):
                with self.assertRaises(STTUnavailableError) as context:
                    service.transcribe(Path(audio_file.name))
        self.assertIn("requirements-stt.txt", str(context.exception))


if __name__ == "__main__":
    unittest.main()
