from enum import StrEnum


class ConversationState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    GENERATING = "GENERATING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class InvalidStateTransition(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.DISCONNECTED: {ConversationState.CONNECTING},
    ConversationState.CONNECTING: {
        ConversationState.READY,
        ConversationState.ERROR,
        ConversationState.DISCONNECTED,
    },
    ConversationState.READY: {
        ConversationState.LISTENING,
        ConversationState.GENERATING,
        ConversationState.ERROR,
        ConversationState.DISCONNECTED,
    },
    ConversationState.LISTENING: {
        ConversationState.TRANSCRIBING,
        ConversationState.READY,
        ConversationState.ERROR,
        ConversationState.DISCONNECTED,
    },
    ConversationState.TRANSCRIBING: {
        ConversationState.GENERATING,
        ConversationState.READY,
        ConversationState.ERROR,
        ConversationState.DISCONNECTED,
    },
    ConversationState.GENERATING: {
        ConversationState.READY,
        ConversationState.SPEAKING,
        ConversationState.ERROR,
        ConversationState.DISCONNECTED,
    },
    ConversationState.SPEAKING: {
        ConversationState.READY,
        ConversationState.ERROR,
        ConversationState.DISCONNECTED,
    },
    ConversationState.ERROR: {ConversationState.DISCONNECTED},
}


class ConversationStateMachine:
    def __init__(self) -> None:
        self._state = ConversationState.DISCONNECTED

    @property
    def state(self) -> ConversationState:
        return self._state

    def transition(self, next_state: ConversationState) -> tuple[ConversationState, ConversationState]:
        previous = self._state
        if next_state not in _ALLOWED_TRANSITIONS[previous]:
            raise InvalidStateTransition(
                f"Invalid conversation state transition: {previous} -> {next_state}"
            )
        self._state = next_state
        return previous, next_state
