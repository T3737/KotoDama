import asyncio
import json
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main
from app.orchestration.conversation_state import (
    ConversationState,
    ConversationStateMachine,
    InvalidStateTransition,
)


class FakeOllamaClient:
    async def chat(self, messages: list[dict[str, str]]) -> str:
        return f"Reply to: {messages[-1]['content']}"

    async def is_available(self) -> bool:
        return True


class SlowOllamaClient:
    async def chat(self, messages: list[dict[str, str]]) -> str:
        await asyncio.sleep(0.05)
        return f"Slow reply to: {messages[-1]['content']}"


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
        main.app.state.ollama_client = FakeOllamaClient()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.app.state.ollama_client = self.original_client

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
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "ollama": True,
                "stt_mode": "mock",
                "voice_websocket": True,
            },
        )

    def test_malformed_json_returns_structured_error(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            websocket.send_text("{not-json")
            response = websocket.receive_json()
            self.assertEqual(response["type"], "error")
            self.assertEqual(response["payload"]["code"], "malformed_json")

    def test_unsupported_event_type_returns_structured_error(self) -> None:
        with self.client.websocket_connect("/voice/session") as websocket:
            websocket.send_json(event("audio.start"))
            response = websocket.receive_json()
            self.assertEqual(response["payload"]["code"], "unsupported_event")

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


if __name__ == "__main__":
    unittest.main()
