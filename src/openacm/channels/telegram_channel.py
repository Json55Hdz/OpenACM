"""
Telegram Channel — bot adapter for Telegram.

Uses python-telegram-bot to connect and forward messages to the Brain.
"""
import os
import asyncio
import structlog
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from openacm.channels.base import BaseChannel
from openacm.core.brain import Brain
from openacm.core.config import TelegramConfig
from openacm.core.events import (
    EventBus, 
    EVENT_CHANNEL_CONNECTED,
    EVENT_TOOL_CALLED,
    EVENT_TOOL_RESULT,
    EVENT_MESSAGE_SENT,
)

log = structlog.get_logger()


class TelegramChannel(BaseChannel):
    """Telegram bot channel."""

    def __init__(self, config: TelegramConfig, brain: Brain, event_bus: EventBus):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self._connected = False
        self._app: Application | None = None
        self._tool_messages: dict[str, int] = {}  # { "chat_id-tool_name": message_id }

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self):
        """Start the Telegram bot."""
        if not self.config.token:
            log.warning("Telegram token not configured")
            return

        self._app = (
            Application.builder()
            .token(self.config.token)
            .build()
        )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("model", self._cmd_model))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        
        # Register EventBus listeners for tool tracking
        self.event_bus.on(EVENT_TOOL_CALLED, self._on_tool_called)
        self.event_bus.on(EVENT_TOOL_RESULT, self._on_tool_result)
        self.event_bus.on(EVENT_MESSAGE_SENT, self._on_message_sent)

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        self._connected = True
        log.info("Telegram bot started")
        await self.event_bus.emit(EVENT_CHANNEL_CONNECTED, {"channel": "telegram"})

    async def stop(self):
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        self._connected = False

    async def send_message(self, target_id: str, content: str, **kwargs) -> bool:
        """Send a message to a Telegram chat."""
        if not self._app:
            return False
        try:
            await self._app.bot.send_message(
                chat_id=int(target_id),
                text=content,
                parse_mode="Markdown",
            )
            return True
        except Exception as e:
            log.error("Telegram send failed", error=str(e))
            return False

    def _is_allowed(self, user_id: int) -> bool:
        """Check if a user is allowed to interact with the bot."""
        if not self.config.allowed_users:
            return True  # No restrictions
        return str(user_id) in self.config.allowed_users

    async def _on_tool_called(self, event_type: str, data: dict):
        if not self._app or not self._connected:
            return
            
        if os.environ.get("OPENACM_VERBOSE_CHANNELS", "true").lower() != "true":
            return
            
        channel_id = data.get("channel_id")
        tool_name = data.get("tool")
        if not channel_id or not tool_name:
            return
            
        try:
            msg = await self._app.bot.send_message(
                chat_id=int(channel_id),
                text=f"⚙️ *_Ejecutando_* `{tool_name}`...",
                parse_mode="Markdown",
            )
            self._tool_messages[f"{channel_id}-{tool_name}"] = msg.message_id
        except Exception as e:
            log.warning("Could not send tool start notification", error=str(e))

    async def _on_tool_result(self, event_type: str, data: dict):
        if not self._app or not self._connected:
            return
            
        if os.environ.get("OPENACM_VERBOSE_CHANNELS", "true").lower() != "true":
            return
            
        channel_id = data.get("channel_id")
        tool_name = data.get("tool")
        result = data.get("result", "")
        if not channel_id or not tool_name:
            return
            
        msg_id = self._tool_messages.pop(f"{channel_id}-{tool_name}", None)
        if msg_id:
            try:
                # Update the message instead of deleting
                status_icon = "❌" if "Error:" in str(result) else "✅"
                await self._app.bot.edit_message_text(
                    chat_id=int(channel_id),
                    message_id=msg_id,
                    text=f"{status_icon} *_Completado_* `{tool_name}`",
                    parse_mode="Markdown",
                )
            except Exception as e:
                log.warning("Could not edit tool finish notification", error=str(e))

    async def _on_message_sent(self, event_type: str, data: dict):
        if not self._app or not self._connected:
            return
        
        channel_type = data.get("channel_type")
        if channel_type != "telegram":
            return
            
        channel_id = data.get("channel_id")
        content = data.get("content", "")
        if not channel_id or not content:
            return
            
        try:
            import re
            import io
            from pathlib import Path
            from openacm.security.crypto import decrypt_file
            
            # Check for media embedded in the message
            media_links = re.findall(r'/api/media/([a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|gif|webp))', content)
            sent_as_caption = False
            
            for file_name in media_links:
                file_path = Path("data/media") / file_name
                if file_path.exists():
                    try:
                        raw_bytes = decrypt_file(file_path)
                        photo_io = io.BytesIO(raw_bytes)
                        photo_io.name = file_name
                        
                        # Strip the raw media link from caption to look cleaner
                        caption_text = content.replace(f"/api/media/{file_name}", "").strip()
                        
                        if not sent_as_caption and len(caption_text) <= 1024 and len(caption_text) > 0:
                            await self._app.bot.send_photo(
                                chat_id=int(channel_id), 
                                photo=photo_io, 
                                caption=caption_text
                            )
                            sent_as_caption = True
                        elif not sent_as_caption and len(caption_text) == 0:
                            await self._app.bot.send_photo(chat_id=int(channel_id), photo=photo_io)
                            sent_as_caption = True
                        else:
                            await self._app.bot.send_photo(chat_id=int(channel_id), photo=photo_io)
                            
                    except Exception as e:
                        log.error("Telegram media send failed", error=str(e))
            
            if sent_as_caption:
                return

            # Split long messages (Telegram limit: 4096 chars)
            if len(content) <= 4096:
                await self._app.bot.send_message(chat_id=int(channel_id), text=content)
            else:
                chunks = [content[i:i+4000] for i in range(0, len(content), 4000)]
                for chunk in chunks:
                    await self._app.bot.send_message(chat_id=int(channel_id), text=chunk)
        except Exception as e:
            log.error("Telegram event send failed", error=str(e))

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            await update.message.reply_text("⛔ Not authorized.")
            return
        
        await update.message.reply_text(
            "👋 ¡Hola! Soy **ACM**, tu asistente AI.\n\n"
            "Envíame cualquier mensaje y te responderé. "
            "Puedo ejecutar comandos, buscar información, "
            "y mucho más.\n\n"
            "Comandos:\n"
            "/clear — Limpiar conversación\n"
            "/model — Ver/cambiar modelo LLM\n"
            "/help — Ver ayuda",
            parse_mode="Markdown",
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not update.message:
            return
        await update.message.reply_text(
            "🤖 **ACM — Ayuda**\n\n"
            "Simplemente escríbeme un mensaje y te responderé.\n\n"
            "Puedo:\n"
            "• Responder preguntas\n"
            "• Ejecutar comandos del sistema\n"
            "• Leer y escribir archivos\n"
            "• Buscar en internet\n"
            "• Ver info del sistema\n\n"
            "Comandos:\n"
            "/clear — Limpiar historial\n"
            "/model — Cambiar modelo\n"
            "/help — Esta ayuda",
            parse_mode="Markdown",
        )

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear command."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            return
        
        await self.brain.memory.clear(
            str(update.effective_user.id),
            str(update.message.chat_id),
        )
        await update.message.reply_text("✅ Conversación limpiada.")

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /model command."""
        if not update.message:
            return
        current = self.brain.llm_router.current_model
        await update.message.reply_text(f"🧠 Modelo actual: `{current}`", parse_mode="Markdown")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            return

        content = update.message.text
        if not content:
            return

        user_id = str(update.effective_user.id)
        channel_id = str(update.message.chat_id)

        # Send "typing" action
        await update.message.chat.send_action("typing")

        try:
            # Fire and forget. The response will be captured by _on_message_sent
            # and routed to Telegram, even if triggered from Web UI.
            asyncio.create_task(self.brain.process_message(
                content=content,
                user_id=user_id,
                channel_id=channel_id,
                channel_type="telegram",
            ))

        except Exception as e:
            log.error("Telegram message error", error=str(e))
            await update.message.reply_text(f"❌ Error: {str(e)}")
