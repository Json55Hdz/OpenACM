# Channels

OpenACM is channel-agnostic. The same AI brain handles messages from all channels identically. Channels are responsible for receiving messages, delivering responses, and translating platform-specific features.

---

## Web Dashboard

The built-in browser interface. No extra setup required — always available at `http://127.0.0.1:47821`.

**Features:**
- Real-time message streaming
- File upload (images, PDFs, audio, text files)
- Inline image preview and file download
- Conversation history with encryption indicator
- Multi-conversation management (sidebar with delete)
- Tool execution log (toggle on/off)
- Interactive terminal output mirror
- New conversation badge and fresh start indicator

**Conversation identity:** Each new conversation gets a unique ID (`web_<timestamp>`). Conversations persist in the database and can be resumed by selecting them from the sidebar.

---

## Console

The interactive terminal built into the OpenACM startup process. No extra setup.

**Features:**
- Type messages directly in the terminal
- Full ANSI color output
- Slash commands: `/models`, `/tools`, `/config`, `/help`

**Usage:**
```
You> take a screenshot
You> what's my disk usage?
You> /models
You> quit
```

Console conversations use `channel_id=console`, `user_id=console`.

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
4. Enable in `config/default.yaml`:
   ```yaml
   channels:
     telegram:
       enabled: true
       token: "${TELEGRAM_TOKEN}"
       allowed_users: []   # restrict by Telegram user ID if needed
   ```

### Restricting Access
```yaml
channels:
  telegram:
    allowed_users:
      - 123456789   # Find your ID via @userinfobot
```

### File Support
- Send images → OpenACM analyzes them (with vision-capable models)
- Send audio/voice → transcribed via Whisper API or faster-whisper
- Send documents → text extracted and added to context

### Agent Bots
Each agent can have its own Telegram bot (separate `telegram_token`). This gives specialists their own dedicated bot without sharing the main agent.

---

## Discord

OpenACM runs as a Discord bot, responding to mentions and DMs.

### Setup

1. Create an application at [discord.com/developers](https://discord.com/developers)
2. Add a Bot, enable Message Content Intent
3. Copy the bot token
4. Add to `config/.env`:
   ```env
   DISCORD_TOKEN=...
   ```
5. Enable in config:
   ```yaml
   channels:
     discord:
       enabled: true
       token: "${DISCORD_TOKEN}"
       command_prefix: "!"
       respond_to_mentions: true
       respond_to_dms: true
       allowed_guilds: []   # Empty = all guilds
   ```

### Restricting to Specific Servers
```yaml
channels:
  discord:
    allowed_guilds:
      - 1234567890123456789   # Your server's guild ID
```

### Features
- Responds to `@OpenACM <message>` mentions
- Responds to direct messages
- Optional command prefix (e.g., `!ask what's my IP?`)

---

## WhatsApp

OpenACM connects to WhatsApp via an HTTP bridge running locally on port 3001. This requires a WhatsApp bridge solution (such as [whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) or [mautrix-whatsapp](https://github.com/mautrix/whatsapp)).

### Setup

1. Set up a WhatsApp bridge on `http://localhost:3001`
2. Enable in config:
   ```yaml
   channels:
     whatsapp:
       enabled: true
       bridge_url: "http://localhost:3001"
       rate_limit_per_minute: 20
   ```

**Note:** WhatsApp's Terms of Service restrict automated bots. Use for personal automation only.

---

## Channel IDs and User IDs

Each conversation is identified by `channel_id:user_id`:

| Channel | channel_id | user_id |
|---------|-----------|---------|
| Web | `web` | `web_<timestamp>` |
| Console | `console` | `console` |
| Telegram | Telegram chat ID | `tg_<chat_id>` |
| Discord | Guild ID | Discord user ID |
| WhatsApp | Phone number | Phone number |

This pair is the conversation key — same pair = same conversation history.

---

## Adding Custom Channels

Any messaging platform can be added by implementing `BaseChannel`. See [Extending OpenACM](./17-extending.md#adding-custom-channels) for details.
