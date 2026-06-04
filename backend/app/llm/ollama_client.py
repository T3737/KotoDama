from typing import Any

import httpx



class OllamaError(Exception):
    """Raised when the local Ollama API cannot provide a chat response."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaError(
                "Could not connect to Ollama at http://localhost:11434. "
                "Start Ollama and try again."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            raise OllamaError(
                f"Ollama returned an error for model '{self.model}': {detail}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaError("Ollama took too long to respond.") from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama returned an empty or unexpected response.")

        return content.strip()


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text or response.reason_phrase

    error = data.get("error")
    if isinstance(error, str) and error:
        return error
    return response.reason_phrase
