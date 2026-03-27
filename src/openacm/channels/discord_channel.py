"""
Discord Channel — bot adapter for Discord.

Uses discord.py to connect to Discord and forward messages to the Brain.
"""

import asyncio
from typing import Any

import discord
import structlog

from openacm.channels.base import BaseChannel
from openacm.core.brain import Brain
from openacm.core.config import DiscordConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED

log = structlog.get_logger()


class DiscordChannel(BaseChannel):
    """Discord bot channel."""

    def __init__(self, config: DiscordConfig, brain: Brain, event_bus: EventBus):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self._connected = False

        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True

        self._client = discord.Client(intents=intents)
        self._setup_handlers()

    @property
    def name(self) -> str:
        return "discord"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _setup_handlers(self):
        """Set up Discord event handlers."""

        @self._client.event
        async def on_ready():
            self._connected = True
            log.info("Discord connected", user=str(self._client.user))
            await self.event_bus.emit(EVENT_CHANNEL_CONNECTED, {
                "channel": "discord",
                "user": str(self._client.user),
            })

        @self._client.event
        async def on_message(message: discord.Message):
            # Don't respond to ourselves
            if message.author == self._client.user:
                return

            # Check if we should respond
            should_respond = False
            
            # DMs
            if isinstance(message.channel, discord.DMChannel):
                if self.config.respond_to_dms:
                    should_respond = True
            
            # Mentions
            elif self._client.user in message.mentions:
                if self.config.respond_to_mentions:
                    should_respond = True
            
            # Command prefix
            elif message.content.startswith(self.config.command_prefix):
                should_respond = True

            if not should_respond:
                return

            # Clean the message content
            content = message.content
            # Remove bot mention
            if self._client.user:
                content = content.replace(f"<@{self._client.user.id}>", "").strip()
            # Remove command prefix
            if content.startswith(self.config.command_prefix):
                content = content[len(self.config.command_prefix):].strip()

            if not content:
                return

            # Show typing indicator
            async with message.channel.typing():
                try:
                    response = await self.brain.process_message(
                        content=content,
                        user_id=str(message.author.id),
                        channel_id=str(message.channel.id),
                        channel_type="discord",
                    )

                    # Split long messages (Discord limit: 2000 chars)
                    if len(response) <= 2000:
                        await message.reply(response)
                    else:
                        chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                await message.reply(chunk)
                            else:
                                await message.channel.send(chunk)

                except Exception as e:
                    log.error("Discord message error", error=str(e))
                    await message.reply(f"❌ Error: {str(e)}")

    @staticmethod
    def _is_placeholder_token(token: str) -> bool:
        """Check if a token is a placeholder/example value."""
        placeholders = {"your-discord-bot-token-here", "your-token-here", "change-me"}
        return (
            not token
            or token.lower() in placeholders
            or token.startswith("your-")
        )

    async def start(self):
        """Start the Discord bot."""
        if self._is_placeholder_token(self.config.token):
            log.warning("Discord token not configured or is a placeholder, skipping")
            return

        try:
            await self._client.start(self.config.token)
        except Exception as e:
            log.error("Discord connection failed", error=str(e))
            self._connected = False
            await self.event_bus.emit(EVENT_CHANNEL_DISCONNECTED, {
                "channel": "discord",
                "error": str(e),
            })

    async def stop(self):
        """Stop the Discord bot."""
        await self._client.close()
        self._connected = False

    async def send_message(self, target_id: str, content: str, **kwargs) -> bool:
        """Send a message to a Discord channel or user."""
        try:
            channel = self._client.get_channel(int(target_id))
            if channel:
                await channel.send(content)
                return True
            
            user = self._client.get_user(int(target_id))
            if user:
                await user.send(content)
                return True
            
            return False
        except Exception as e:
            log.error("Discord send failed", error=str(e))
            return False
