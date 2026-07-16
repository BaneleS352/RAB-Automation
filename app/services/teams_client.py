import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class TeamsClientError(Exception):
    pass


@dataclass
class ConversationReference:
    conversation_id: str
    service_url: str
    tenant_id: str = ""
    bot_id: str = ""
    user_id: str = ""
    channel_id: str = ""


# Simple in-memory store for conversation references
_conversation_store: dict[str, ConversationReference] = {}


def register_conversation(key: str, ref: ConversationReference) -> None:
    _conversation_store[key] = ref


def get_conversation(key: str) -> ConversationReference | None:
    return _conversation_store.get(key)


class TeamsClient:
    """Client for sending proactive messages via Azure Bot Service."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.app_id = self.settings.TEAMS_BOT_APP_ID
        self.client_secret = self.settings.TEAMS_BOT_CLIENT_SECRET
        self._token: str | None = None
        self._token_expiry: float = 0

    def _is_configured(self) -> bool:
        return bool(self.app_id and self.client_secret)

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.app_id,
            "client_secret": self.client_secret,
            "scope": "https://api.botframework.com/.default",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                result = resp.json()
                self._token = result["access_token"]
                self._token_expiry = time.time() + result.get("expires_in", 3600)
                return self._token
        except httpx.RequestError as e:
            raise TeamsClientError(f"Failed to get Bot Framework token: {e}") from e

    async def send_activity(
        self,
        conversation_id: str,
        service_url: str,
        activity: dict,
    ) -> dict:
        token = await self._get_token()
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=activity, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            raise TeamsClientError(f"Failed to send activity: HTTP {e.response.status_code}: {e.response.text[:200]}") from e
        except httpx.RequestError as e:
            raise TeamsClientError(f"Network error sending activity: {e}") from e

    async def send_message(self, conversation: ConversationReference, text: str) -> dict:
        activity = {
            "type": "message",
            "text": text,
        }
        return await self.send_activity(conversation.conversation_id, conversation.service_url, activity)

    async def send_adaptive_card(self, conversation: ConversationReference, card: dict) -> dict:
        activity = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }
        return await self.send_activity(conversation.conversation_id, conversation.service_url, activity)

    async def send_message_to_channel(self, channel_id: str, text: str) -> dict:
        if not self.settings.TEAMS_CHANNEL_ID:
            raise TeamsClientError("TEAMS_CHANNEL_ID is not configured")
        ref = ConversationReference(
            conversation_id=channel_id,
            service_url="https://smba.trafficmanager.net/amer/",
        )
        return await self.send_message(ref, text)

    async def send_card_to_channel(self, channel_id: str, card: dict) -> dict:
        if not self.settings.TEAMS_CHANNEL_ID:
            raise TeamsClientError("TEAMS_CHANNEL_ID is not configured")
        ref = ConversationReference(
            conversation_id=channel_id,
            service_url="https://smba.trafficmanager.net/amer/",
        )
        return await self.send_adaptive_card(ref, card)

    async def check_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "details": "Teams / Azure Bot is not configured."}
        try:
            await self._get_token()
            return {"connected": True, "details": "Azure Bot authentication succeeded."}
        except TeamsClientError as e:
            return {"connected": False, "details": str(e)}
