import httpx

from app.config import settings


class StripeClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.stripe_base_url,
            headers={"Authorization": f"Bearer {settings.stripe_api_key}"},
            timeout=10.0,
        )

    async def healthcheck(self) -> bool:
        # Lightweight call shape for future external API integration.
        # In a real project this should hit a provider status endpoint.
        return True

    async def close(self) -> None:
        await self._client.aclose()
