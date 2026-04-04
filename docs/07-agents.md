# Agents

Agents are isolated instances of OpenACM with their own system prompt, a restricted set of tools, and optionally their own dedicated Telegram bot. While the main OpenACM agent is a generalist, agents are specialists.

---

## How Agents Work

Each agent has:
- **Name and description** — displayed in the dashboard
- **System prompt** — defines the agent's persona and expertise
- **Allowed tools** — a whitelist of tools the agent can use
- **Telegram bot token** (optional) — gives the agent its own dedicated bot

When an agent receives a message, it runs through the same agentic loop as the main agent, but can only call its allowed tools. This restriction is enforced at the tool execution level, not just the prompt level.

---

## Creating an Agent

### Via Dashboard
**Agents** → **New Agent** → fill in the form.

### Via Chat
```
You: Create an agent called "ResearchBot" that specializes in finding 
     and summarizing online information. Give it access only to 
     web_search, get_webpage, and remember_note. 
     It should be concise, cite sources, and prefer primary sources.
```

### Via API
```bash
curl -X POST http://localhost:47821/api/agents \
  -H "Authorization: Bearer acm_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ResearchBot",
    "description": "Finds and summarizes information",
    "system_prompt": "You are a research specialist. Always cite sources. Prefer academic and primary sources.",
    "allowed_tools": ["web_search", "get_webpage", "remember_note"]
  }'
```

---

## Messaging an Agent

### Via Telegram
If the agent has a `telegram_token`, it runs as an independent bot. Users message it directly on Telegram.

### Via API
```bash
curl -X POST http://localhost:47821/api/agents/1/chat \
  -H "Authorization: Bearer acm_xxx" \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the latest developments in fusion energy?", "user_id": "web"}'
```

### Via the main OpenACM agent
The main agent can delegate to sub-agents using the `create_agent` tool to spawn a task-specific agent for a complex subtask.

---

## Use Cases

### Specialized Bots
Give friends or colleagues Telegram bots with limited, safe capabilities:

```
Agent: "ScheduleBot"
Tools: calendar_list, calendar_create, gmail_read
Prompt: "Help users manage their schedule. Only create events they explicitly confirm."
```

### Automated Workers
An agent with `run_command` and `write_file` that processes files:

```
Agent: "DataProcessor"
Tools: read_file, write_file, run_python
Prompt: "You are a data processing agent. Process CSV files and output clean reports."
```

### Research Assistants
```
Agent: "ResearchBot"
Tools: web_search, get_webpage, remember_note, search_memory
Prompt: "Research topics thoroughly. Store key findings in memory. Synthesize, don't just copy."
```

### IoT Controller
```
Agent: "HomeBot"
Tools: iot_devices, iot_control, iot_status
Prompt: "Control smart home devices. Always confirm before turning off devices that might be in use."
```

---

## Agent vs Main Agent

| Feature | Main Agent | Sub-Agent |
|---------|-----------|-----------|
| Tool access | All registered tools | Whitelist only |
| Memory | Shared conversation DB | Separate per-agent conversations |
| System prompt | Config default + skills | Custom per-agent |
| Telegram | Shared main bot | Own dedicated bot (optional) |
| Web dashboard | Full access | Via API only |

---

## Security Considerations

- Agents are isolated by tool whitelist — they cannot call tools outside their allowed list
- Each agent has its own webhook secret for Telegram webhook verification
- Agent conversations are stored separately in the database (by agent channel_id)
- If you give an agent `run_command`, it has the same OS access as the main agent — be careful with tool choice
