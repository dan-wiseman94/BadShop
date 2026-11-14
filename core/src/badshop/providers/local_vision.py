"""HTTP transport for the optional on-device assistant; editing policy lives in agent."""

from collections.abc import Awaitable, Callable
import httpx
from badshop.agent.provider import ProviderError

PROFILE_ID = "badshop-on-device"
LABEL = "On-device AI"


class LocalVisionProvider:
    actor = f"agent:{PROFILE_ID}"
    warnings: list[str] = []

    def __init__(self, endpoint: Callable[[], Awaitable[tuple[str, str]]],
                 available: Callable[[], bool]) -> None:
        self._endpoint = endpoint
        self._available = available

    def check_capabilities(self) -> dict[str, bool]:
        if not self._available():
            raise ProviderError("Set up On-device AI in Settings → Assets before using it.")
        return {"vision": True, "tool_calls": True}

    async def request(self, client: httpx.AsyncClient, body: dict) -> dict:
        url, key = await self._endpoint()
        try:
            response = await client.post(url + "/v1/chat/completions", json=body,
                                         headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            return response.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            raise ProviderError("On-device AI could not finish the request. Try again with a shorter request "
                                "or start a new session.") from None
