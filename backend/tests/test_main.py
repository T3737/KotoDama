import asyncio
import unittest

from fastapi import HTTPException

from app.game.npc_profiles import NpcProfileError, load_npc_profile
from app import main


class FakeOllamaClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "Profile-specific test reply."


class NpcRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        main.session_store._sessions.clear()
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

    def test_session_keys_are_forced_into_npc_namespaces(self) -> None:
        self.assertEqual(
            main._npc_session_key("default_save:aiko", "aiko"),
            "default_save:aiko",
        )
        self.assertEqual(
            main._npc_session_key("default_save:aiko", "haru"),
            "default_save:aiko:haru",
        )


if __name__ == "__main__":
    unittest.main()
