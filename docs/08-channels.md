# Channels

OpenACM is channel-agnostic. The same AI brain handles messages from all channels identically. Channels are responsible for receiving messages, delivering responses, and translating platform-specific features.

Besides the global channels described here, every [agent](./07-agents.md#channels) can have its own Telegram bot and WhatsApp number.

---

## Web Dashboard

The built-in browser interface. No extra setup required — always available at `http://127.0.0.1:47821`.

**Features:**
- Real-time responses, with partial text shown while tools run
- File upload (images, PDFs, audio, Office documents, text files)
- Inline image preview and file download
- Conversation history with encryption indicator
- Multi-conversation sidebar: web conversations, external channel conversations, and one folder per agent (collapsible, remembered across sessions, paginated)
- Tool execution log (toggle on/off)
- Interactive terminal per conversation (real PTY) that also mirrors the AI's commands
- Cancel button to abort the current request

**Conversation identity:** Web conversations use `channel_id=web`; each new conversation gets its own user id (`web_<timestamp>`). Conversations persist in the database and can be resumed by selecting them from the sidebar.

---

## Console

The interactive terminal built into the OpenACM startup process. No extra setup.

**Features:**
- Type messages directly in the terminal
- Full ANSI color output
- Console-only commands: `/models`, `/tools`, `/config`
- Shared slash commands: `/new`, `/clear`, `/reset`, `/compact`, `/model`, `/stats`, `/export`, `/workspace`, `/help`

**Usage:**
```
You> take a screenshot
You> what's my disk usage?
You> /models
You> quit
```

Console conversations use `channel_id=console`, `user_id=console`. When OpenACM runs without a TTY (Docker, systemd) the console is skipped and the process just keeps the web server and channels alive.

There is also `openacm-cli`, a separate REPL that connects to a running OpenACM over HTTP/WebSocket (it's what you can launch inside the dashboard terminal).

---

## Telegram

OpenACM runs as a Telegram bot. Any message to the bot is processed by the agent.

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the token
3. Add to `config/.env`:
   ```env
   TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
4. Restart OpenACM. When `TELEGRAM_TOKEN` is set the channel **auto-enables**; you can also enable it explicitly in `config/local.yaml`:
   ```yaml
   channels:
     telegram:
       enabled: true
       allowed_users: []   # restrict by Telegram user ID if needed
   ```

You can also paste the token in the onboarding wizard or **Configuration** — the bot is (re)started immediately without a restart.

### Restricting Access
```yaml
channels:
  telegram:
    allowed_users:
      - "123456789"   # Find your ID via @userinfobot — quote it, IDs are strings
```

### File Support
- Send images → OpenACM analyzes them (with vision-capable models)
- Send audio/voice → transcribed with the OpenAI Whisper API (if `OPENAI_API_KEY` is set), local faster-whisper, or MarkItDown as a last resort
- Send documents → text extracted and added to context

### Tool logs
By default external channels also receive short tool-execution messages. Turn this off in **Configuration** (`POST /api/config/verbose_channels`, `OPENACM_VERBOSE_CHANNELS=false`).

### Agent Bots
Each agent can have its own Telegram bot (**Agents → Channels → Telegram**). This gives specialists their own dedicated bot without sharing the main agent.

---

## Discord

OpenACM runs as a Discord bot, responding to mentions, DMs and a command prefix.

### Setup

1. Create an application at [discord.com/developers](https://discord.com/developers)
2. Add a Bot, enable Message Content Intent
3. Copy the bot token
4. Add to `config/.env`:
   ```env
   DISCORD_TOKEN=...
   ```
5. Enable in `config/local.yaml` (Discord is not auto-enabled):
   ```yaml
   channels:
     discord:
       enabled: true
       command_prefix: "!"
       respond_to_mentions: true
       respond_to_dms: true
   ```

### Features
- Responds to `@OpenACM <message>` mentions
- Responds to direct messages
- Optional command prefix (e.g., `!ask what's my IP?`)
- Files produced by tools are uploaded as Discord attachments

> The config model also has an `allowed_guilds` list, but in v0.4.7 the Discord channel does not enforce it. Restrict the bot by only inviting it to servers you trust.

---

## WhatsApp

OpenACM supports two WhatsApp modes, selected with `channels.whatsapp.mode`:

| Mode | How it works | Recommended |
|------|--------------|-------------|
| `cloud_api` (default) | Official **Meta WhatsApp Cloud API**. Meta POSTs incoming messages to your public `https://<your-domain>/webhooks/whatsapp` | ✅ Yes — no ban risk |
| `bridge` | Legacy local HTTP bridge (e.g. whatsapp-web.js) at `bridge_url` | Unofficial, ban risk |

### Cloud API setup (summary)

1. Create a Meta app with the WhatsApp product and note the access token, phone number ID and app secret
2. Put the credentials in `config/.env`:
   ```env
   WHATSAPP_ACCESS_TOKEN=EAAG...
   WHATSAPP_PHONE_NUMBER_ID=123456789012345
   WHATSAPP_VERIFY_TOKEN=any-string-you-choose
   WHATSAPP_APP_SECRET=...
   ```
3. Expose OpenACM over HTTPS (e.g. Cloudflare Tunnel) and set the webhook in Meta to `https://<your-domain>/webhooks/whatsapp` with the same verify token
4. The channel auto-enables once `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` are present

Incoming webhook bodies are validated against `WHATSAPP_APP_SECRET` (`X-Hub-Signature-256`). The full step-by-step guide is in [WhatsApp Setup](./WHATSAPP_SETUP.md).

### Bridge mode

```yaml
channels:
  whatsapp:
    enabled: true
    mode: bridge
    bridge_url: "http://localhost:3001"
    rate_limit_per_minute: 20
```

**Note:** WhatsApp's Terms of Service restrict unofficial automation. Prefer the Cloud API.

---

## Channel IDs and User IDs

Each conversation is identified by `channel_id:user_id`:

| Channel | channel_id | user_id |
|---------|-----------|---------|
| Web | `web` | `web` / `web_<timestamp>` |
| Console | `console` | `console` |
| Telegram | Telegram chat ID | Telegram user ID |
| Discord | Discord channel ID | Discord user ID |
| WhatsApp | Sender phone number | Sender phone number |
| Agents (API/test) | `agent_<id>` | caller-provided |
| Cron `send_message` jobs | `cron` | `cron` |

This pair is the conversation key — same pair = same conversation history.

---

## Adding Custom Channels

Any messaging platform can be added by implementing `BaseChannel`. See [Extending OpenACM](./17-extending.md#adding-custom-channels) for details.
