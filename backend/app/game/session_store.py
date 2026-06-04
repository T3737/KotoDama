from collections import defaultdict


class SessionStore:
    def __init__(self, max_messages: int = 12) -> None:
        self.max_messages = max_messages
        self._sessions: defaultdict[str, list[dict[str, str]]] = defaultdict(list)

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._sessions[session_id])

    def add_message(self, session_id: str, role: str, content: str) -> None:
        messages = self._sessions[session_id]
        messages.append({"role": role, "content": content})

        if len(messages) > self.max_messages:
            self._sessions[session_id] = messages[-self.max_messages :]
