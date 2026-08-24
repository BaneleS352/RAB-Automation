"""Teams client - removed.

This integration has been removed as the team is shifting to a different
issue management and monitoring platform.

All references to Teams have been removed from the codebase.
"""


class TeamsClient:
    """Minimal stub - Teams integration disabled."""

    def __init__(self) -> None:
        self.settings = type("obj", (object,), {"TEAMS_WEBHOOK_URL": "", "TEAMS_CALLBACK_URL": ""})()

    def is_configured(self) -> bool:
        return False

    def is_webhook_configured(self) -> bool:
        return False

    async def send_activity(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def send_message(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def send_adaptive_card(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def send_card_to_channel(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def _post_webhook(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def send_message_via_webhook(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def send_adaptive_card_via_webhook(self, *args, **kwargs) -> dict:
        raise RuntimeError("Teams client is disabled")

    async def check_connection(self) -> dict:
        return {"connected": False, "details": "Teams integration is not configured."}