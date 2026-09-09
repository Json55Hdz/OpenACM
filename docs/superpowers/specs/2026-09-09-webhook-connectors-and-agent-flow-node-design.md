# Diseño: Conectores de Webhook + Nodo "Agente" en Flows

**Fecha**: 2026-09-09
**Estado**: Aprobado para plan de implementación

## Contexto y motivación

El plugin `energichat_reporte_danos` (repo privado `openacm-clients`,
`clients/eep/plugin/`) implementa la integración "Reporte de Daños" entre
EnergiChat y OpenACM: un webhook firmado con HMAC-SHA256, deduplicación,
una máquina de estados determinística, y una llamada de salida firmada de
vuelta a EnergiChat. Construirla tomó ~15 archivos Python específicos del
contrato exacto de esa integración.

EEP va a necesitar más integraciones de este tipo (ej. "Pagos / estado de
cuenta", conectada al mismo chat de WhatsApp pero como un webhook
completamente separado, con su propio contrato). El objetivo de este
diseño es que agregar la **siguiente** integración sea cuestión de
configurar desde el dashboard y dibujar un Flow visual — no de escribir
Python nuevo ni de desplegar código.

Dos piezas, ambas genéricas (sin ningún conocimiento de EnergiChat/EEP),
para el repo general de OpenACM:

1. **Sistema de Conectores de Webhook** — registra webhooks dinámicos
   desde el dashboard, cada uno disparando un Flow.
2. **Nodo "Agente" en el editor de Flows** — permite que un Flow llame a
   un Agente de OpenACM (LLM) como un paso más.

Todo lo específico de una integración real (ruta, secreto, a qué Flow
apunta, la lógica de negocio del Flow mismo) es **configuración/datos**,
creada desde el dashboard y guardada en la base de datos del servidor del
cliente — nunca código, nunca comiteado a ningún repo.

## Alcance (YAGNI)

- **v1 es síncrono**: la petición HTTP corre el Flow dentro de la misma
  request y responde con su resultado. El patrón "ack rápido (202) + Flow
  en segundo plano + respuesta firmada aparte" que sí necesita EnergiChat
  para Reporte de Daños **no se generaliza en esta versión** — no hay un
  segundo caso real que lo confirme todavía. Si "Pagos" resulta
  necesitarlo, se agrega como extensión cuando se conozca su contrato real.
- Tres esquemas de autenticación (`hmac_sha256`, `bearer_token`,
  `static_header_secret`) cubren todo lo visto hasta ahora (EnergiChat,
  el webhook de agentes existente). No se construye un sistema de
  plugins de auth extensible — son tres implementaciones fijas.
- Sin reintentos configurables, sin catálogo de plantillas por proveedor,
  sin logs unificados cross-conector más allá de lo que ya loguea OpenACM.
  Eso es la versión "plataforma completa" que se descartó explícitamente
  a favor de esta más chica.

## Componentes

### 1. Modelo de datos — `webhook_connectors`

Nueva tabla (migración ~37, siguiente disponible tras la 36 de
`skills.flow_id`):

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER PK | |
| `slug` | TEXT UNIQUE NOT NULL | Arma la ruta `/api/webhooks/{slug}` |
| `name` | TEXT NOT NULL | Nombre visible en el dashboard |
| `auth_scheme` | TEXT NOT NULL | `hmac_sha256` \| `bearer_token` \| `static_header_secret` |
| `auth_config` | TEXT (JSON) NOT NULL | Config específica del esquema, ver abajo |
| `flow_id` | INTEGER NOT NULL | FK a la tabla de flows existente |
| `enabled` | BOOLEAN NOT NULL DEFAULT true | Apagar sin borrar |
| `created_at` | TIMESTAMP | |

`auth_config` por esquema:
- `hmac_sha256`: `{"secret": str, "timestamp_header": str, "signature_header": str, "max_skew_seconds": int}`
- `bearer_token`: `{"token": str, "header_name": str}` (default `Authorization`)
- `static_header_secret`: `{"header_name": str, "secret": str}`

Un campo más, opcional, fuera de `auth_config`:
- `dedupe_header` (TEXT, nullable): nombre de un header (ej.
  `X-Event-Id`) que identifica el evento de forma única para ese
  proveedor. Si se configura, un valor repetido no vuelve a correr el
  Flow — devuelve el mismo resultado guardado la primera vez. Si se deja
  vacío, no hay deduplicación (varios proveedores no la necesitan, y no
  todos mandan un id de evento). Generaliza la deduplicación por
  `eventId` que EnergiChat sí exige, sin asumir que todo proveedor lo hace.

CRUD estándar vía la capa de base de datos existente (mismo patrón que
`get_agent_flows`/`create_agent_flow` ya usan) + endpoints REST bajo
`/api/webhook-connectors` (protegidos por el token del dashboard, como
cualquier otra ruta de administración) y una pantalla nueva en el
frontend para crear/editar/apagar conectores.

### 1.5. Auditoría — `webhook_connector_events`

Mismo motivo que ya tiene `energichat_events` en el plugin de EEP: sin
esto, un conector nuevo no tiene forma de ver "qué llegó y qué pasó"
desde el dashboard. Tabla nueva (migración ~38):

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER PK | |
| `connector_id` | INTEGER FK | |
| `dedupe_key` | TEXT, nullable | Valor del header de `dedupe_header`, si el conector lo configuró |
| `received_at` | TIMESTAMP | |
| `body` | TEXT (JSON) | El body recibido, tal cual |
| `status` | TEXT | `ok` \| `auth_failed` \| `bad_request` \| `flow_error` |
| `result` | TEXT, nullable | El `result` devuelto (o el mensaje de error) |
| `duration_ms` | INTEGER | Cuánto tardó el Flow |

Se inserta una fila por cada request que pasa la verificación de `slug`
(incluye los `auth_failed`, para poder ver intentos de acceso inválidos).
Nunca se guardan headers completos (podrían traer secretos) — solo el
body y el resultado.

**Dónde vive**: ambas tablas (`webhook_connectors` y
`webhook_connector_events`) están **siempre en la base de datos interna
de OpenACM** — no hay opción de Postgres externo aquí. Eso es una
decisión específica del plugin `energichat_reporte_danos` (EEP quería
centralizar en su `ia_reportedanos`), no algo que el core deba
generalizar: ningún otro dato del core (agentes, flows, skills) vive en
un Postgres externo por cliente, y los conectores no son la excepción. Si
un cliente puntual necesita que lo que pase por un conector también
termine en su propia base, eso se resuelve dentro del Flow (un nodo HTTP
que escriba allá), no con un toggle en el core.

Vista en el dashboard: por cada conector, una lista simple (no el feed
tipo chat que tiene el plugin de EEP — esa presentación es específica de
WhatsApp/usuario-bot, no aplica a un webhook genérico) con fecha, status,
y el `result`/error, más contadores agregados (total, por status) — mismo
espíritu que la sección de estadísticas que ya existe, generalizado.

### 2. Ruta genérica `POST /api/webhooks/{slug}`

- Declarada pública una sola vez, de forma estática, en
  `TokenAuthMiddleware` (prefijo `/api/webhooks/` completo exento del
  token del dashboard) — no hace falta registro dinámico de rutas, cada
  request resuelve el conector por `slug` en tiempo de ejecución.
- Verifica la auth según el `auth_scheme` del conector encontrado
  (implementaciones puras, reutilizables, ver Testing).
- Arma `params = {"headers": {...}, "body": <json parseado>}` para el
  Flow — el Flow los lee con el templating `{{body.campo}}` que ya existe.
- Corre `FlowExecutor.run(graph, params)` (ya es una función standalone,
  sin acoplamiento a chat/agente — confirmado leyendo
  `src/openacm/core/flow_executor.py`).
- Responde `200` con `{"result": "<texto del nodo End>"}` — siempre JSON,
  siempre esta forma fija (sin campo de configuración adicional para
  status/formato: YAGNI hasta que un conector real necesite otra cosa).
  Si el propio Flow necesita devolver una estructura más rica, el
  autor del Flow arma un JSON como texto en el template del End (ej.
  `{"situationCode": "{{cond1}}", "mensaje": "{{set1}}"}`) — el caller lo
  parsea del campo `result`.

### 3. Manejo de errores

| Caso | HTTP |
|---|---|
| `slug` no existe o conector apagado | 404 |
| Auth inválida (firma/token/secreto no coincide) | 401 |
| Body no es JSON válido | 400 |
| Flow mal formado (sin Start o sin End) | 500 (error de configuración nuestro, no del caller) |
| `FlowExecutor.run()` devuelve un string de error (ya es su contrato actual — nunca lanza excepción) | 502 |

Nunca se exponen detalles internos (secretos, stack traces) en la
respuesta — solo van a los logs.

### 4. Nodo "Agente" en `FlowExecutor`

Nuevo tipo de nodo (`agent`), junto a los existentes (`http`,
`conditional`, `woocommerce`, `set`, `get`, `end`, `loop`) en
`KNOWN_NODE_TYPES` / `NODE_TARGET_HANDLES` / `NODE_SOURCE_HANDLES` /
`FlowExecutor._HANDLERS`.

- Config: `agent_id` (qué Agente de OpenACM llamar) + `message`
  (wire-or-literal, mismo patrón que el campo `url`/`body` del nodo HTTP
  — se resuelve vía `resolve_field()`).
- Ejecución: `await AgentRunner.run(agent, message_resuelto)` — método ya
  existente, standalone, devuelve un string.
- Salida: el texto de respuesta del agente, disponible al resto del Flow
  como `{{nodoAgente}}` — igual que la salida de cualquier otro nodo.
- Requiere que el `FlowExecutor` reciba una forma de obtener el agente
  por id (nueva dependencia inyectada al constructor, mismo patrón que
  `get_connection` ya usa para el nodo WooCommerce) y una instancia de
  `AgentRunner` (o los componentes para construir uno: `llm_router`,
  `tool_registry`, `memory`, `event_bus`, `database`).

Esto no es exclusivo de los conectores — cualquier Flow (disparado por
chat, por un conector, o por el tool `create_or_update_agent_flow`)
gana la capacidad de invocar un Agente como paso.

## Ejemplo de flujo de datos (hipotético)

```
EnergiChat → POST /api/webhooks/energichat-pagos
             headers: X-Sig: <hmac>, X-Ts: 1788...
             body: {"matricula": "511659", "accion": "estado_cuenta"}
                    │
                    ▼
   1. Busca conector "energichat-pagos" → existe, enabled=true
   2. auth_scheme=hmac_sha256 → verifica X-Sig contra el secreto guardado
   3. params = {"headers": {...}, "body": {"matricula": "511659", ...}}
   4. FlowExecutor.run(flow_pagos.graph_json, params)
        Start → Http (GET estado-cuenta, matrícula={{body.matricula}})
              → Conditional (¿saldo pendiente?)
              → Agente (redacta el mensaje final con el resultado)
              → End (template: {{nodoAgente}})
   5. Responde 200 con el texto del End
```

## Testing

- **Verificadores de auth** (los 3 esquemas): funciones puras, tests
  unitarios directos — firma/token válido e inválido, timestamp vencido,
  header faltante. Generaliza los tests que ya existen para
  `hmac_auth.py` en el plugin de EEP.
- **CRUD de `webhook_connectors`**: contra una base de datos real de
  test, sin mocks — mismo patrón que el resto de OpenACM.
- **`webhook_connector_events` / deduplicación**: evento nuevo se guarda
  y corre el Flow; mismo `dedupe_key` en un segundo request devuelve el
  `result` guardado sin volver a correr el Flow; sin `dedupe_header`
  configurado, dos requests idénticos corren el Flow dos veces; un
  intento con auth inválida también queda registrado (`status=auth_failed`).
- **Ruta genérica**: tests de integración con `TestClient` — conector
  inexistente (404), auth inválida (401), body inválido (400), Flow con
  error (502), camino feliz (200) — con un Flow de prueba inyectado vía
  fixture, no un Flow real.
- **Nodo Agente**: test unitario con un `AgentRunner` fake — confirma que
  resuelve el `message` con templates y expone la salida al resto del
  flow, igual que ya se prueba el nodo HTTP.
- **Fin a fin**: conector + Flow simple (Start → Http mockeado → End),
  llamada completa por la ruta genérica, respuesta esperada.

## Fuera de alcance de esta entrega

- El conector real de "EnergiChat Pagos" (o cualquier otro) — eso se crea
  después, desde el dashboard del servidor `eep`, una vez EEP entregue su
  contrato. No es parte de esta implementación.
- El patrón asíncrono ack-rápido + callback firmado (ver "Alcance (YAGNI)").
- Migrar la lógica de "Reporte de Daños" existente a un Flow — sigue
  siendo Python porque ya está construida, probada, y alineada al guion;
  no hay necesidad de reescribirla.
