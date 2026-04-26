# Agent Superpowers — Plan de implementación

## Cambios clave de arquitectura
- **LLM-agnostic**: las acciones usan el formato de function calling de litellm (OpenAI-compatible), funciona con cualquier proveedor conectado (Anthropic, OpenAI, Gemini, Ollama, etc.)
- **Channel system genérico**: en lugar de hardcodear WhatsApp, cada agente puede tener N canales de cualquier tipo. Agregar Discord o Slack en el futuro es solo implementar un nuevo handler, sin tocar la arquitectura.

---

## Qué se va a construir

### Capa 1 — Agent Actions (herramientas HTTP configurables)
Cada agente tiene una lista de "acciones" que el LLM llama como function calls estándar.
El LLM (cualquiera) decide cuándo invocarlas, el servidor ejecuta el HTTP call y devuelve el resultado.

### Capa 2 — Widget responses (botones, encuestas en el chat)
El agente incluye un bloque `widget` en su respuesta.
El frontend lo renderiza como botones/encuestas interactivos.
Al clickear, el valor se envía como mensaje normal → el flujo continúa.

### Capa 3 — Channel system (WhatsApp, Telegram, Discord, ...)
Tabla genérica `agent_channels`. Cada canal tiene tipo + config JSON.
Un mismo agente puede tener WhatsApp + Telegram + Discord simultáneamente.
Los widgets se convierten automáticamente al formato interactivo del canal.

---

## Archivos a crear

| Archivo | Qué hace |
|---|---|
| `src/openacm/web/routers/channels.py` | Webhook handler genérico + dispatcher por tipo de canal |
| `src/openacm/channels/base.py` | Clase abstracta `BaseChannel` (parse_incoming, send_message, send_widget) |
| `src/openacm/channels/whatsapp.py` | Implementación WhatsApp Business API |
| `src/openacm/channels/telegram_channel.py` | Implementación Telegram (complementa el bot existente) |

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `src/openacm/storage/database.py` | Migration 17: tabla `agent_actions` + tabla `agent_channels`. CRUD de ambas. Deprecar `whatsapp_*` / migrar `telegram_token` al nuevo sistema. |
| `src/openacm/web/routers/agents.py` | Endpoints CRUD para acciones y canales. |
| `src/openacm/core/agent_runner.py` | Inyectar acciones como tools reales. Append widget system note. |
| `src/openacm/web/server.py` | Registrar router de channels. |
| `frontend/hooks/use-agents.ts` | Tipos `AgentAction`, `AgentChannel`. Hooks correspondientes. |
| `frontend/app/agents/page.tsx` | Sección "Actions" + sección "Channels" en el modal. |
| `frontend/app/chat/page.tsx` | Parser y renderer de bloques `widget`. |

---

## Esquema de base de datos

### Nueva tabla `agent_actions`
```sql
CREATE TABLE agent_actions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id      INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,           -- "Buscar cliente"
    description   TEXT NOT NULL,           -- lo que lee el LLM para decidir cuándo usarlo
    url           TEXT NOT NULL,           -- "https://api.ejemplo.com/buscar"
    method        TEXT DEFAULT 'POST',     -- GET | POST | PUT | PATCH | DELETE
    headers_json  TEXT DEFAULT '{}',       -- {"Authorization": "Bearer TOKEN"}
    body_template TEXT DEFAULT '',         -- '{"query": "{{data}}", "user": "{{user_id}}"}'
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Nueva tabla `agent_channels`
```sql
CREATE TABLE agent_channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,     -- 'whatsapp' | 'telegram' | 'discord' | 'slack' | ...
    name        TEXT DEFAULT '',   -- "WhatsApp principal" (label del usuario)
    is_active   INTEGER DEFAULT 1,
    config_json TEXT DEFAULT '{}', -- config específica del tipo (ver abajo)
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_channels_agent ON agent_channels(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_channels_type  ON agent_channels(type);
```

#### Config JSON por tipo de canal

**WhatsApp Business**
```json
{
  "phone_id": "1234567890",
  "token": "EAABcde...",
  "verify_token": "mi_verify_token_secreto"
}
```

**Telegram**
```json
{
  "bot_token": "123456:ABC-DEF..."
}
```

**Discord** _(Phase 2)_
```json
{
  "bot_token": "...",
  "application_id": "...",
  "public_key": "..."
}
```

**Slack** _(Phase 2)_
```json
{
  "bot_token": "xoxb-...",
  "signing_secret": "..."
}
```

> **Nota sobre Telegram existente:** Los agentes que hoy tienen `telegram_token` en la columna vieja seguirán funcionando. En la migration se crea la nueva tabla; la migración completa del campo viejo es opcional y puede hacerse después.

---

## Body template — variables disponibles

| Variable | Descripción |
|---|---|
| `{{data}}` | Lo que el LLM quiere enviar a la acción |
| `{{message}}` | El mensaje original del usuario |
| `{{user_id}}` | ID del usuario que habla |
| `{{agent_id}}` | ID del agente |
| `{{channel_type}}` | Tipo del canal de origen (whatsapp, telegram, web, ...) |

---

## LLM-agnostic function calling

Las acciones se convierten al formato estándar OpenAI que litellm normaliza para todos los providers:

```python
{
  "type": "function",
  "function": {
    "name": "action__42",                        # action__{id}
    "description": "Busca un cliente por nombre o email en el CRM",
    "parameters": {
      "type": "object",
      "properties": {
        "data": {"type": "string", "description": "Datos a enviar a la acción"}
      },
      "required": []
    }
  }
}
```

Funciona igual con GPT-4, Claude, Gemini, Llama 3 via Ollama, etc. — litellm hace la traducción.

### _ActionToolRegistry (wrapper del registry existente)

```
tool_registry (existente)
    └── _ActionToolRegistry (wrapper)
            ├── tools:  {inner tools} ∪ {action__{id} stubs}   ← check "in tools"
            ├── get_tools_schema()   → inner + action schemas
            ├── get_tools_by_intent() → inner + action schemas
            └── execute(name, args)
                    ├── name == "action__{id}" → HTTP call (httpx)
                    └── otherwise              → inner.execute(...)
```

El truco: `tools` es un dict custom que responde a `__contains__` para ambos (inner + acciones), pero `.values()` solo devuelve los tools del inner — para que el loop de MCP tools en Brain no crashee sobre los dicts de acciones.

---

## Widget format (en respuestas del agente)

El agente incluye en su respuesta un fenced code block con lenguaje `widget`:

### Botones (single-select, máx ~5)
~~~
```widget
{"type":"buttons","text":"¿Qué quieres hacer?","options":[{"label":"Ver reportes","value":"ver_reportes"},{"label":"Nueva tarea","value":"nueva_tarea"}]}
```
~~~

### Encuesta (multi-select + submit)
~~~
```widget
{"type":"poll","text":"¿Cuáles son tus favoritos?","options":["Pizza","Sushi","Tacos"],"multi":true}
```
~~~

### Rating / estrellas
~~~
```widget
{"type":"rating","text":"¿Cómo fue tu experiencia?","scale":5}
```
~~~

El system prompt de cada agente recibe automáticamente las instrucciones del formato widget — el usuario no necesita incluirlo manualmente.

---

## Channel system — arquitectura genérica

### Clase base `BaseChannel`
```python
class BaseChannel(ABC):
    type: str                          # 'whatsapp' | 'telegram' | ...
    
    @abstractmethod
    async def verify_webhook(self, request) -> Response:
        """GET — verificación inicial del proveedor."""
    
    @abstractmethod
    async def parse_incoming(self, request) -> list[IncomingMessage] | None:
        """POST — parsea el body y devuelve mensajes normalizados."""
    
    @abstractmethod
    async def send_text(self, channel_config, to, text) -> None:
        """Envía texto plano al usuario."""
    
    @abstractmethod
    async def send_widget(self, channel_config, to, widget) -> None:
        """Convierte widget JSON al formato interactivo del canal y lo envía."""
```

### IncomingMessage (normalizado)
```python
@dataclass
class IncomingMessage:
    user_id: str      # identificador del remitente en el canal
    text: str         # texto del mensaje (o value del botón pulsado)
    raw: dict         # payload original completo
```

### Endpoints del router genérico
```
GET  /api/agents/{agent_id}/channels/{channel_id}/webhook
POST /api/agents/{agent_id}/channels/{channel_id}/webhook
```

El dispatcher busca el canal por `channel_id`, instancia el handler correcto según `type`, y lo ejecuta.

### Agregar un canal nuevo en el futuro
1. Crear `src/openacm/channels/discord.py` con `class DiscordChannel(BaseChannel)`
2. Registrar en el dispatcher: `CHANNEL_HANDLERS = {"discord": DiscordChannel, ...}`
3. Agregar el tipo al select de la UI
4. Listo — no hay que tocar nada más

---

## Conversión de widgets por canal

| Widget | WhatsApp | Telegram | Discord |
|---|---|---|---|
| `buttons` ≤3 | Interactive `button` | InlineKeyboard | Components Button Row |
| `buttons` 4-10 | Interactive `list` | InlineKeyboard (rows) | Select Menu |
| `poll` multi | `list` simulado | `sendPoll` nativo | Select Menu multi |
| `rating` | Botones 1-5 | InlineKeyboard 1-5 | Buttons Row |
| Texto normal | `text` message | `sendMessage` | `createMessage` |

---

## UI — Modal del agente (nuevas secciones)

### Tab / sección "Actions"
```
[ + Add Action ]

┌─────────────────────────────────────────┐
│  🔗  Buscar cliente                      │
│  POST  https://api.ejemplo.com/clientes  │
│  "Busca un cliente por nombre o email"   │
│                              [Edit] [✕]  │
└─────────────────────────────────────────┘
```

Formulario de acción: Nombre · Descripción · URL · Method · Headers (JSON) · Body template

### Sección "Channels" (en Advanced o tab separado)
```
[ + Add Channel ]

┌─────────────────────────────────────────┐
│  💬  WhatsApp principal      [active]    │
│  Webhook: /api/agents/3/channels/1/...  │
│                              [Edit] [✕]  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  ✈️  Telegram Bot            [active]    │
│  Webhook: /api/agents/3/channels/2/...  │
│                              [Edit] [✕]  │
└─────────────────────────────────────────┘
```

Al editar un canal, aparece un form específico según el tipo seleccionado.

### Card del agente — badges de canales activos
`[WhatsApp]  [Telegram]  [Tools: 3]`

---

## Orden de implementación

1. `database.py` — migration 17 + CRUD (base para todo)
2. `channels/base.py` — clases base + tipos normalizados
3. `channels/whatsapp.py` — implementación WhatsApp
4. `channels/telegram_channel.py` — implementación Telegram
5. `agent_runner.py` — _ActionToolRegistry + widget system note + cargar acciones
6. `agents.py` (backend) — CRUD endpoints de acciones y canales
7. `channels.py` (router) — dispatcher genérico
8. `server.py` — registrar router
9. `use-agents.ts` — tipos + hooks
10. `agents/page.tsx` — UI de acciones + canales
11. `chat/page.tsx` — widget renderer

---

## Esfuerzo estimado

| Parte | LOC aprox. | Complejidad |
|---|---|---|
| DB migration + CRUD | ~100 | Baja |
| channels/base.py | ~60 | Baja |
| channels/whatsapp.py | ~150 | Media |
| channels/telegram_channel.py | ~100 | Baja (API simple) |
| agent_runner.py | ~120 | Media |
| agents.py endpoints | ~80 | Baja |
| channels.py router | ~80 | Baja |
| use-agents.ts | ~80 | Baja |
| agents/page.tsx | ~250 | Media |
| chat/page.tsx widget | ~80 | Baja |
| **Total** | **~1100** | |
