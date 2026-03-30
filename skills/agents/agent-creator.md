---
name: agent-creator
description: Knows how to create autonomous agents via the create_agent tool
category: agents
is_active: true
---

# Agent Creator Skill

Use the `create_agent` tool when the user asks to create a bot, automated assistant, webhook responder, or wants to replace an n8n/automation workflow with an AI agent.

## When to use

- "crea un bot de soporte"
- "quiero un asistente que responda preguntas sobre mi negocio"
- "haz un agente que conteste en Telegram con estas reglas"
- "reemplaza este flujo de n8n con un agente"
- "crea un bot FAQ para mi tienda"

## How to write a good system_prompt

A good system prompt has:
1. **Identity** — who the agent is and for which company/context
2. **Tone** — formal, casual, friendly, etc.
3. **Rules** — what it can and cannot say
4. **Escalation** — when to redirect to a human or contact info
5. **Language** — what language(s) to respond in

## Example

```
create_agent(
  name="Soporte Acme",
  description="Bot de soporte al cliente para Acme Corp",
  system_prompt="""Eres el asistente de soporte de Acme Corp, una empresa de software.

Personalidad: amable, conciso y profesional.

Reglas:
- Responde siempre en español
- Nunca reveles información de precios internos
- Para reembolsos, dirige al usuario a soporte@acme.com
- Si no sabes algo, di honestamente que no tienes esa información
- No hagas promesas de plazos de entrega
""",
  allowed_tools="none"
)
```

## After creating

Always show the user:
- The webhook URL
- The secret key (only shown once — remind them to save it)
- How to call it with curl or from their app
