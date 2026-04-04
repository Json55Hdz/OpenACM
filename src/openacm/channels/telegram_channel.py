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
from openacm.core.commands import CommandProcessor
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

    def __init__(self, config: TelegramConfig, brain: Brain, event_bus: EventBus, database=None):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self._connected = False
        self._app: Application | None = None
        self._tool_messages: dict[str, int] = {}  # { "chat_id-tool_name": message_id }
        self._cmd = CommandProcessor(brain, database)
        self.ready_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def is_connected(self) -> bool:
        return self._connected

    @staticmethod
    def _is_placeholder_token(token: str) -> bool:
        """Check if a token is a placeholder/example value."""
        placeholders = {"your-telegram-bot-token-here", "your-token-here", "change-me"}
        return (
            not token
            or token.lower() in placeholders
            or token.startswith("your-")
            or ":" not in token  # Real Telegram tokens always contain ':'
        )

    async def start(self):
        """Start the Telegram bot."""
        if self._is_placeholder_token(self.config.token):
            log.warning("Telegram token not configured or is a placeholder, skipping")
            self.ready_event.set()
            return

        self._app = Application.builder().token(self.config.token).build()

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("new", self._cmd_clear))
        self._app.add_handler(CommandHandler("model", self._cmd_model))
        self._app.add_handler(CommandHandler("stats", self._cmd_stats))
        self._app.add_handler(CommandHandler("export", self._cmd_export))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self._app.add_handler(MessageHandler(
            (filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL) & ~filters.COMMAND,
            self._handle_message,
        ))

        # Register EventBus listeners for tool tracking
        self.event_bus.on(EVENT_TOOL_CALLED, self._on_tool_called)
        self.event_bus.on(EVENT_TOOL_RESULT, self._on_tool_result)
        self.event_bus.on(EVENT_MESSAGE_SENT, self._on_message_sent)

        try:
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
        except Exception as e:
            log.error("Telegram bot failed to start", error=str(e))
            self._app = None
            self.ready_event.set()  # unblock waiters even on failure
            return

        self._connected = True
        log.info("Telegram bot started")
        self.ready_event.set()
        await self.event_bus.emit(EVENT_CHANNEL_CONNECTED, {"channel": "telegram"})

    async def stop(self):
        """Stop the Telegram bot."""
        # Deregister event handlers first to prevent stale duplicates after restart
        try:
            self.event_bus.off(EVENT_TOOL_CALLED, self._on_tool_called)
            self.event_bus.off(EVENT_TOOL_RESULT, self._on_tool_result)
            self.event_bus.off(EVENT_MESSAGE_SENT, self._on_message_sent)
        except Exception:
            pass
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                log.warning("Error stopping Telegram app", error=str(e))
            self._app = None
        self._connected = False

    async def restart(self, new_token: str | None = None):
        """Restart the bot, optionally with a new token."""
        log.info("Restarting Telegram bot", new_token_provided=bool(new_token))
        await self.stop()
        if new_token:
            self.config.token = new_token
        await self.start()

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

    def _owns_event(self, data: dict) -> bool:
        """Return True if this channel instance should handle the event."""
        return data.get("channel_type") == "telegram"

    async def _on_tool_called(self, event_type: str, data: dict):
        if not self._app or not self._connected:
            return
        if not self._owns_event(data):
            return

        if os.environ.get("OPENACM_VERBOSE_CHANNELS", "true").lower() != "true":
            return

        channel_id = data.get("channel_id")
        tool_name = data.get("tool")
        if not channel_id or not tool_name:
            return

        # Solo procesar si es un chat de Telegram (channel_id numérico)
        try:
            chat_id = int(channel_id)
        except ValueError:
            # No es un chat de Telegram (ej: "web", "console", etc.)
            return

        try:
            msg = await self._app.bot.send_message(
                chat_id=chat_id,
                text=f"⚙️ *_Ejecutando_* `{tool_name}`...",
                parse_mode="Markdown",
            )
            self._tool_messages[f"{channel_id}-{tool_name}"] = msg.message_id
        except Exception as e:
            log.warning("Could not send tool start notification", error=str(e))

    async def _on_tool_result(self, event_type: str, data: dict):
        if not self._app or not self._connected:
            return
        if not self._owns_event(data):
            return

        if os.environ.get("OPENACM_VERBOSE_CHANNELS", "true").lower() != "true":
            return

        channel_id = data.get("channel_id")
        tool_name = data.get("tool")
        result = data.get("result", "")
        if not channel_id or not tool_name:
            return

        # Solo procesar si es un chat de Telegram (channel_id numérico)
        try:
            chat_id = int(channel_id)
        except ValueError:
            # No es un chat de Telegram (ej: "web", "console", etc.)
            return

        msg_id = self._tool_messages.pop(f"{channel_id}-{tool_name}", None)
        if msg_id:
            try:
                # Update the message instead of deleting
                status_icon = "❌" if "Error:" in str(result) else "✅"
                await self._app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=f"{status_icon} *_Completado_* `{tool_name}`",
                    parse_mode="Markdown",
                )
            except Exception as e:
                log.warning("Could not edit tool finish notification", error=str(e))

    async def _on_message_sent(self, event_type: str, data: dict):
        if not self._app or not self._connected:
            return
        # Skip partial messages (intermediate AI text before tool calls)
        if data.get("partial"):
            return
        channel_type = data.get("channel_type")
        if channel_type != "telegram":
            return

        channel_id = data.get("channel_id")
        content = data.get("content", "")
        attachments = data.get("attachments", [])

        # Strip any stray ATTACHMENT: lines that may have leaked into content
        content = "\n".join(
            line for line in content.splitlines() if not line.startswith("ATTACHMENT:")
        ).strip()

        if not channel_id or (not content and not attachments):
            return

        # Verificar que el channel_id sea numérico (chat de Telegram)
        try:
            chat_id = int(channel_id)
        except ValueError:
            log.warning(f"Invalid Telegram chat_id: {channel_id}")
            return

        try:
            import re
            import io
            from pathlib import Path
            from openacm.security.crypto import decrypt_file

            # Use absolute path via env var set by app.py to avoid CWD ambiguity
            project_root = os.environ.get("OPENACM_PROJECT_ROOT", ".")
            media_dir = Path(project_root) / "data" / "media"

            IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            sent_files: set[str] = set()  # Track already-sent filenames

            # ── 1. Send files from the attachments list (proper mechanism) ──
            sent_attachment_as_caption = False

            for file_name in attachments:
                file_path = media_dir / file_name
                if not file_path.exists():
                    log.warning("Attachment file not found", file=file_name, path=str(file_path))
                    continue
                try:
                    raw_bytes = decrypt_file(file_path)
                    file_io = io.BytesIO(raw_bytes)
                    file_io.name = file_name
                    ext = Path(file_name).suffix.lower()

                    # Clean the /api/media/ link from the text for a nicer caption
                    caption_text = content.replace(f"/api/media/{file_name}", "").strip()
                    caption_text = re.sub(
                        r"📎\s*/api/media/" + re.escape(file_name), "", caption_text
                    ).strip()

                    # Pick a caption for the first file only (set flag AFTER successful send)
                    caption = None
                    if not sent_attachment_as_caption and caption_text and len(caption_text) <= 1024:
                        caption = caption_text

                    if ext in IMAGE_EXTENSIONS:
                        await self._app.bot.send_photo(
                            chat_id=chat_id, photo=file_io, caption=caption
                        )
                    else:
                        await self._app.bot.send_document(
                            chat_id=chat_id, document=file_io, caption=caption
                        )

                    sent_files.add(file_name)
                    if caption:
                        sent_attachment_as_caption = True  # only after successful send
                except Exception as e:
                    log.error("Telegram attachment send failed", file=file_name, error=str(e))

            # ── 2. Fallback: detect media URLs in the message text ──
            # Catches images from screenshot, python_kernel, etc.
            media_links = re.findall(
                r"/api/media/([a-zA-Z0-9_.-]+\.(?:png|jpg|jpeg|gif|webp|pdf|docx|xlsx|zip|csv|txt|html|mp3|mp4|wav))",
                content,
            )
            sent_inline_as_caption = False

            for file_name in media_links:
                if file_name in sent_files:
                    continue  # Already sent via attachments list
                file_path = media_dir / file_name
                if not file_path.exists():
                    continue
                try:
                    raw_bytes = decrypt_file(file_path)
                    file_io = io.BytesIO(raw_bytes)
                    file_io.name = file_name
                    ext = Path(file_name).suffix.lower()

                    caption_text = content.replace(f"/api/media/{file_name}", "").strip()
                    caption = None
                    if (
                        not sent_inline_as_caption
                        and not sent_attachment_as_caption
                        and caption_text
                        and len(caption_text) <= 1024
                    ):
                        caption = caption_text

                    if ext in IMAGE_EXTENSIONS:
                        await self._app.bot.send_photo(
                            chat_id=chat_id, photo=file_io, caption=caption
                        )
                    else:
                        await self._app.bot.send_document(
                            chat_id=chat_id, document=file_io, caption=caption
                        )

                    sent_files.add(file_name)
                    if caption:
                        sent_inline_as_caption = True
                except Exception as e:
                    log.error("Telegram inline media send failed", file=file_name, error=str(e))

            # ── 3. Send the text message ──
            if sent_attachment_as_caption or sent_inline_as_caption:
                # Caption already sent with the file, skip text message
                return

            if sent_files:
                # Files were sent but no caption was used (caption too long),
                # send the text separately, cleaning up media links
                for fname in sent_files:
                    content = content.replace(f"/api/media/{fname}", "").strip()
                    content = re.sub(r"📎\s*/api/media/" + re.escape(fname), "", content).strip()

            if not content:
                return

            # Split long messages (Telegram limit: 4096 chars)
            if len(content) <= 4096:
                await self._app.bot.send_message(chat_id=chat_id, text=content)
            else:
                chunks = [content[i : i + 4000] for i in range(0, len(content), 4000)]
                for chunk in chunks:
                    await self._app.bot.send_message(chat_id=chat_id, text=chunk)
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
        result = await self._cmd.handle("/help", "", "", "")
        await update.message.reply_text(result.text)

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear and /new commands."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            return
        user_id = str(update.effective_user.id)
        channel_id = str(update.message.chat_id)
        result = await self._cmd.handle("/clear", "", user_id, channel_id)
        await update.message.reply_text(result.text)

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /model command."""
        if not update.message:
            return
        args = " ".join(context.args) if context.args else ""
        user_id = str(update.effective_user.id) if update.effective_user else ""
        channel_id = str(update.message.chat_id)
        result = await self._cmd.handle("/model", args, user_id, channel_id)
        await update.message.reply_text(result.text)

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        if not update.message:
            return
        result = await self._cmd.handle("/stats", "", "", "")
        await update.message.reply_text(result.text)

    async def _cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /export command — sends conversation as a text file."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            return
        user_id = str(update.effective_user.id)
        channel_id = str(update.message.chat_id)
        result = await self._cmd.handle("/export", "", user_id, channel_id)

        if result.data and result.data.get("export"):
            import io
            export_bytes = result.data["export"].encode("utf-8")
            doc = io.BytesIO(export_bytes)
            doc.name = "conversation.txt"
            await self._app.bot.send_document(
                chat_id=int(channel_id), document=doc, caption=result.text
            )
        else:
            await update.message.reply_text(result.text)

    async def _save_media(self, data: bytes, ext: str) -> str:
        """Save raw bytes to media dir, return file_id."""
        import secrets
        from openacm.security.crypto import get_media_dir
        file_id = f"{secrets.token_hex(12)}{ext}"
        dest = get_media_dir() / file_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return file_id

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages (text, images, voice, audio, documents)."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            return

        user_id = str(update.effective_user.id)
        channel_id = str(update.message.chat_id)

        content = update.message.text or update.message.caption or ""
        attachments: list[str] = []

        # ── Photo ──────────────────────────────────────────────────────────
        if update.message.photo:
            photo = update.message.photo[-1]  # largest size
            tg_file = await photo.get_file()
            raw = await tg_file.download_as_bytearray()
            file_id = await self._save_media(bytes(raw), ".jpg")
            attachments.append(file_id)
            if not content:
                content = "What's in this image?"

        # ── Voice / Audio ──────────────────────────────────────────────────
        if update.message.voice or update.message.audio:
            media = update.message.voice or update.message.audio
            ext = ".ogg" if update.message.voice else ".mp3"
            tg_file = await media.get_file()
            raw = await tg_file.download_as_bytearray()
            file_id = await self._save_media(bytes(raw), ext)
            attachments.append(file_id)
            if not content:
                content = "Transcribe and respond to this audio message."

        # ── Document (PDF, txt, etc.) ──────────────────────────────────────
        if update.message.document:
            doc = update.message.document
            from pathlib import Path
            ext = Path(doc.file_name or "file.bin").suffix or ".bin"
            tg_file = await doc.get_file()
            raw = await tg_file.download_as_bytearray()
            file_id = await self._save_media(bytes(raw), ext)
            attachments.append(file_id)
            if not content:
                content = f"Process this file: {doc.file_name}"

        if not content and not attachments:
            return

        # Send "typing" action
        await update.message.chat.send_action("typing")

        async def _process_and_handle_errors():
            """Wrapper to catch errors from brain.process_message inside the task."""
            try:
                await self.brain.process_message(
                    content=content,
                    user_id=user_id,
                    channel_id=channel_id,
                    channel_type="telegram",
                    attachments=attachments if attachments else None,
                )
            except Exception as e:
                log.error("Telegram brain processing error", error=str(e))
                try:
                    await self._app.bot.send_message(
                        chat_id=int(channel_id),
                        text=f"❌ Error procesando mensaje: {str(e)[:500]}",
                    )
                except Exception:
                    log.error("Could not send error message to Telegram")

        asyncio.create_task(_process_and_handle_errors())
