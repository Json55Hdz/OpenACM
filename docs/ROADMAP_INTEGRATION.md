# OpenACM — Integration & Evolution Roadmap

Planes arquitectónicos para convertir OpenACM en una plataforma de integración universal.
Estas ideas surgieron del propio sistema analizando sus capacidades y limitaciones.

---

## Visión final — ¿Qué obtenemos con todo esto?

OpenACM deja de ser un "asistente con tools" y se convierte en algo cualitativamente diferente:

> **Un sistema operativo autónomo con IA en el centro, que vive en la nube, tiene ojos y manos en cualquier máquina o software del mundo, actúa sin que nadie se lo pida, y crece solo.**

La diferencia con cualquier chatbot o agente convencional:

| Chatbot / Agente normal | OpenACM completo |
|------------------------|-----------------|
| Reacciona cuando le hablas | Actúa solo mientras duermes |
| Vive en tu PC | Vive en la nube, alcanza cualquier máquina |
| Controla lo que tú le das | Controla cualquier software del planeta |
| Sus capacidades las defines tú | Genera sus propias capacidades |
| Un hilo de conversación | Múltiples agentes en paralelo |
| Olvida entre sesiones | Memoria de largo plazo y objetivos |
| Lo usas tú solo | Multi-tenant, múltiples clientes/usuarios |

---

### Escenarios reales

**Para un estudio de desarrollo de software**
```
Dev hace push a GitHub
→ OpenACM revisa el código automáticamente
→ Corre los tests, detecta un bug crítico
→ Comenta en el PR con el problema específico
→ Avisa al equipo por Telegram
→ Si todo está bien, lo aprueba solo
→ Sin que nadie lo pidiera
```

**Para una empresa de contabilidad**
```
Cliente manda email con facturas adjuntas
→ OpenACM lee el email y los archivos
→ Sube los datos a Contpaqi / SAP via adapter
→ Genera el reporte de confirmación
→ Responde al cliente con el resumen
→ Tiempo total: menos de 2 minutos, cero intervención humana
```

**Para un estudio de diseño / arquitectura**
```
"Genera 5 variaciones de esta fachada en Blender
 y mándame las capturas cuando termines"
→ OpenACM orquesta 5 agentes en paralelo
→ Cada uno modela una variante
→ Los renderiza
→ Te manda las imágenes por WhatsApp
→ Tú estabas en una reunión
```

**Para monitoreo y operaciones**
```
03:00 AM — nadie está despierto

OpenACM detecta que el servidor de producción tarda más de normal
→ Investiga logs automáticamente
→ Identifica un query SQL lento
→ Genera el reporte del problema
→ Te manda WhatsApp con el diagnóstico
→ Si es crítico, ejecuta el rollback que tiene autorizado
```

**Para uso personal**
```
"Mientras duermo:
 - genera los reportes del mes
 - revisa si el competidor actualizó precios
 - si el vuelo que sigo baja de $300, cómpramelo
 - si el servidor cae, despiértame"

→ OpenACM trabaja toda la noche
→ Tú te despiertas con todo hecho
```

**Para un cliente con software legacy**
```
Cliente tiene un ERP de 2003 sin API, sin WebSocket, sin nada
→ Local Agent instalado en la máquina del cliente
→ OpenACM lo controla via GUI Automation como último recurso
→ Extrae datos, los procesa, genera reportes modernos
→ El cliente no tuvo que cambiar su software
```

---

### Qué lo hace único vs alternativas

**vs AutoGPT / agentes genéricos:**
Arquitectura real con seguridad por capas, multi-tenant, canales de comunicación reales, y control de hardware local. No es un experimento — es infraestructura.

**vs n8n / Zapier / Make:**
OpenACM razona. No sigue un flujo fijo — decide qué hacer según el contexto. Y puede modificar sus propios flujos.

**vs soluciones enterprise (UiPath, Blue Prism):**
Costo radicalmente menor, sin licencias, open source, y con LLM en el centro para manejar casos no previstos.

**vs asistentes de voz (Alexa, Google Assistant):**
No depende de ningún proveedor. Corre en tu servidor. Tú controlas los datos. Y puede hacer cosas que ningún asistente comercial permite.

---

### La propiedad más importante: se extiende solo

Con el Self-Evolution Engine activo:

```
Usuario: "conecta esto con el sistema de nómina de la empresa"

OpenACM no sabe cómo hacerlo → investiga la API del sistema
→ genera el adapter → lo prueba → lo registra
→ ejecuta la tarea original
→ la próxima vez ya sabe cómo hacerlo

Sin que nadie haya escrito una línea de código
```

Esto es lo que lo separa de cualquier otra plataforma:
**no necesita un desarrollador para crecer.**

---

## Contexto: Qué ya existe

Antes de implementar, tener en cuenta lo que **ya está resuelto**:

| Capacidad | Archivo |
|-----------|---------|
| Creación dinámica de tools | `src/openacm/tools/tool_creator.py` |
| Creación dinámica de skills | `src/openacm/tools/skill_creator.py` |
| Skills generadas auto-guardadas | `skills/generated/` |
| WebSocket para UI | `src/openacm/web/server.py` |
| Ejecución de comandos CLI | `src/openacm/tools/system_cmd.py` |
| Operaciones de archivo | `src/openacm/tools/file_ops.py` |
| Control de Blender vía bpy | `src/openacm/tools/blender_tool.py` |
| Channels (Discord, Telegram, WhatsApp) | `src/openacm/channels/` |

No reinventar estas piezas — extenderlas.

---

## Plan 1 — Universal Integration Bus (UIB)

### Qué es
Un WebSocket endpoint dedicado (`/ws/integration`) separado del WebSocket de la UI, donde **programas externos** pueden conectarse a OpenACM como clientes.

### Para qué sirve
- Unity, Godot, apps custom pueden conectarse y darle herramientas al agente
- El agente puede llamar funciones del programa externo en tiempo real
- El programa externo puede llamar tools de OpenACM

### Protocolo (JSON simple)

```json
// Programa externo → OpenACM: registrar su propia función
{ "type": "register_function", "name": "crear_objeto_3d", "schema": { ... } }

// Programa externo → OpenACM: llamar una tool de OpenACM
{ "type": "call_tool", "tool": "web_search", "args": { "query": "..." }, "id": "abc123" }

// OpenACM → Programa externo: resultado
{ "type": "result", "id": "abc123", "data": "..." }

// OpenACM → Programa externo: invocar función registrada
{ "type": "invoke", "name": "crear_objeto_3d", "args": { ... }, "id": "xyz" }
```

### Archivos a crear
```
src/openacm/web/api/integration_ws.py   ← endpoint WebSocket
src/openacm/core/integration_bus.py     ← lógica de registro y routing
```

### Casos de uso
- Unity con un paquete C# que se conecta al bus
- App de contabilidad custom que expone sus funciones
- Claude Code CLI notificando a OpenACM que haga QA de cambios
- Cualquier script Python externo que quiera usar el agente

---

## Plan 2 — Adapter System

### Qué es
Una carpeta `adapters/` con conectores para programas específicos. Cada adapter sabe **cómo** hablar con su programa target, eligiendo el método más profundo disponible.

### Árbol de decisión de métodos de integración

```
¿Cómo controlar un programa externo?

├── Tiene Python API / SDK nativa    → úsala directo
│     Ejemplos: Blender (bpy), Maya, FreeCAD, Rhino
│
├── Tiene WebSocket o HTTP API       → UIB / requests
│     Ejemplos: Unity con paquete, apps modernas, Odoo
│
├── Es aplicación Windows con COM    → win32com.client
│     Ejemplos: Excel, Word, AutoCAD, SAP GUI, Visio
│
├── Tiene interfaz de línea de comandos → system_cmd (ya existe)
│     Ejemplos: ffmpeg, git, ImageMagick, ERPs legacy
│
├── Intercambia información por archivos → file_ops (ya existe)
│     Ejemplos: Contpaqi (DBF), COI, algunos ERPs
│
├── Tiene base de datos accesible    → conexión directa SQL
│     Ejemplos: Odoo (PostgreSQL), ERPs con SQL Server
│
└── No tiene nada de lo anterior     → GUI Automation (último recurso)
      Herramientas: pyautogui + uiautomation
      OpenACM ya tiene screenshot.py como base
```

### Estructura de un adapter

```
adapters/
  excel/
    manifest.json      ← qué hace, versiones soportadas, método de integración
    bridge.py          ← lógica de conexión
    schema.yaml        ← tools que expone al agente
  unity/
    manifest.json
    bridge.py
    schema.yaml
  sap/
    ...
  contpaqi/
    ...
  generated/           ← adapters generados automáticamente por el agente
```

### Formato de manifest.json

```json
{
  "name": "excel",
  "description": "Control de Microsoft Excel",
  "method": "com",
  "requires": ["pywin32"],
  "platform": ["windows"],
  "tools": ["leer_celda", "escribir_celda", "ejecutar_macro", "exportar_pdf"]
}
```

### Adapters prioritarios a implementar
1. **Excel / Office** (COM via win32com) — caso de uso universal
2. **Unity** (WebSocket via UIB) — ya tienen experiencia con Blender
3. **SAP GUI** (COM via win32com o SAP RFC) — empresarial
4. **GUI Automation genérico** (pyautogui + uiautomation) — fallback

---

## Plan 3 — Declarative Tools (YAML)

### Qué es
Definir tools sin escribir código Python. El sistema auto-genera el handler.

### Para qué sirve
Usuarios no técnicos pueden crear integraciones describiendo qué quieren, no cómo hacerlo.

### Formato propuesto

```yaml
name: crear_factura_sap
description: Crea una factura en SAP con los datos proporcionados
adapter: sap
method: rfc
function: BAPI_BILLINGDOC_CREATEMULTIPLE
input:
  cliente:
    type: string
    description: ID del cliente en SAP
  monto:
    type: number
    description: Monto total de la factura
  concepto:
    type: string
    description: Descripción del concepto
```

### Flujo
```
archivo .yaml en adapters/sap/tools/
    → loader detecta el archivo
    → genera ToolDefinition automáticamente
    → registra en ToolRegistry
    → agente puede usarla sin reiniciar
```

---

## Plan 4 — Self-Evolution Engine (Evolver)

### Qué es
Módulo que detecta cuándo OpenACM no puede resolver algo y genera el adapter/tool necesario **de forma autónoma**, sin que el usuario lo pida.

### Nota
`tool_creator.py` y `skill_creator.py` ya existen y hacen esto parcialmente. El Evolver es la capa que **detecta automáticamente** la necesidad sin que el usuario lo solicite explícitamente.

### Flujo propuesto

```
Usuario: "abre Excel y ponme el total de ventas del mes"

1. Agente intenta ejecutar → no tiene tool para Excel
2. Evolver detecta: "necesito integración con Excel en Windows"
3. Evolver busca en adapters/: no existe adapter de Excel
4. Evolver genera adapter usando COM (win32com)
5. Guarda en adapters/generated/excel/
6. Registra las tools nuevas dinámicamente
7. Ejecuta la tarea original
8. La próxima vez ya tiene el adapter listo
```

### Archivo a crear
```
src/openacm/core/evolver.py
```

---

## Plan 5 — GUI Automation (Fallback universal)

### Qué es
Cuando ningún otro método funciona, OpenACM puede controlar cualquier programa viendo la pantalla e interactuando con el teclado y mouse.

### Base existente
`src/openacm/tools/screenshot.py` ya existe — ve la pantalla.

### Lo que falta

```python
# Herramientas necesarias:
# pyautogui    → mouse, teclado, posición absoluta
# uiautomation → lee árbol de elementos UI de Windows (botones, campos, menús)
# pygetwindow  → gestiona ventanas (focus, mover, redimensionar)
```

### Tools a agregar en desktop_control_tool.py

```
click(x, y)                     → click en coordenadas
click_element(name)             → click en elemento por nombre/texto
type_text(text)                 → escribir texto
get_window_elements(app_name)   → leer árbol UI de una ventana
focus_window(app_name)          → traer ventana al frente
drag(x1, y1, x2, y2)           → drag and drop
```

### Flujo con visión
```
Screenshot → LLM analiza qué hay en pantalla → decide acción → ejecuta → repite
```

Este es el mismo approach de OpenAI Operator y Anthropic Computer Use.

---

## Plan 6 — Proactive Engine

### Qué es
El gap de autonomía más grande: OpenACM solo reacciona cuando alguien le escribe. El Proactive Engine le da la capacidad de **actuar por iniciativa propia** en base a tiempo o eventos.

### Tres tipos de comportamiento proactivo

**1. Cron Jobs (basado en tiempo)**
```
Cada lunes 08:00  → genera reporte semanal → manda por email/Telegram
Cada 5 minutos    → verifica que el servidor del cliente responda
Cada día 23:59    → resume las tareas completadas del día
Cada mes          → genera factura automática
```

**2. Watchers (basado en eventos del sistema)**
```
Archivo nuevo en carpeta  → procésalo automáticamente
Git commit detectado      → corre tests y revisa código
Log con "ERROR"           → alerta inmediata al admin
Uso de CPU > 90%          → investiga qué proceso y notifica
```

**3. Goal Tracking (objetivos de largo plazo)**
```
"Monitorea el precio de X hasta que baje de $100"
"Avísame cuando el competidor actualice su sitio"
"Cada vez que llegue un email de cliente VIP, respóndelo"
```

### Archivos a crear
```
src/openacm/core/proactive_engine.py   ← scheduler + watcher + goal tracker
src/openacm/core/job_store.py          ← persistencia de jobs en DB
```

### Nota importante
En local este engine se pausa si se apaga la PC. En servidor corre 24/7 — es donde cobra todo su valor.

---

## Plan 7 — Inbound Webhooks

### Qué es
Un endpoint público que permite que **cualquier servicio externo despierte a OpenACM** con un evento.

### Endpoint propuesto
```
POST /webhook/{source}/{event}
```

### Ejemplos de uso
```
GitHub  → POST /webhook/github/push       → OpenACM revisa el commit
Stripe  → POST /webhook/stripe/payment    → OpenACM genera factura
Twilio  → POST /webhook/twilio/sms        → OpenACM responde el SMS
Cualquier ERP → POST /webhook/erp/venta   → OpenACM procesa la venta
```

### Flujo interno
```
Webhook recibido
    → valida firma/token del origen
    → identifica qué skill/agente manejar
    → ejecuta en background (no bloquea respuesta HTTP)
    → responde 200 OK inmediatamente
```

### Archivos a crear
```
src/openacm/web/api/webhooks.py    ← endpoints + validación de firmas
src/openacm/core/webhook_router.py ← mapeo source/event → handler
```

---

## Plan 8 — Multi-agent Orchestration

### Qué es
`AgentRunner` ya existe pero no hay coordinador. Este plan añade un **orquestador** que divide tareas complejas entre agentes especializados y consolida los resultados.

### Diferencia con lo actual
```
Ahora:    Un agente → hace todo secuencialmente
Con esto: Orquestador → divide → 3 agentes en paralelo → consolida
```

### Ejemplo
```
Tarea: "Analiza este proyecto y dime qué mejorar"

Orquestador divide:
  ├── Agente Seguridad   → revisa vulnerabilidades
  ├── Agente Performance → revisa cuellos de botella
  └── Agente Código      → revisa calidad y deuda técnica

Orquestador consolida → reporte unificado
```

### Archivos a crear
```
src/openacm/core/orchestrator.py   ← divide, asigna, consolida
```

---

## Plan 9 — Long-term Memory & Goals

### Qué es
La memoria actual es solo historial de conversación. Este plan agrega una **memoria semántica persistente** separada de los chats.

### Tres capas de memoria

```
Capa 1: Conversación     → ya existe (MemoryManager)
Capa 2: Hechos           → "El cliente X prefiere facturas en PDF"
                            "El servidor Y falla los lunes"
                            "La API de Z tiene rate limit de 100/min"
Capa 3: Objetivos activos → "Monitorear precio hasta que baje de $X"
                             "Recordarme el viernes sobre el contrato"
```

### Diferencia con RAG
RAG (ya existe) busca en documentos. Esta memoria es sobre **decisiones, preferencias y patrones aprendidos** de la operación diaria.

### Archivo a crear
```
src/openacm/core/long_term_memory.py
```

---

## Plan 10 — Email Channel

### Qué es
Email como canal nativo, igual que Discord o Telegram. OpenACM recibe y responde emails.

### Dos modos

**Modo recepción via API (recomendado para empezar)**
```
SendGrid Inbound Parse / Mailgun Routes
    → POST a /webhook/email/inbound
    → OpenACM procesa como mensaje normal
    → responde via SMTP
```

**Modo servidor SMTP propio (avanzado, requiere dominio)**
```
MX record apunta al servidor
    → OpenACM recibe emails directo
    → sin intermediarios
```

### Archivo a crear
```
src/openacm/channels/email_channel.py
```

---

## Plan 11 — Voice Channel

### Qué es
Input y output de voz directamente en el browser, sin dependencias externas.

### Stack propuesto
```
Input:   Web Speech API (STT nativo del browser, Chrome/Edge)
Output:  Web Speech Synthesis API (TTS nativo) o ElevenLabs para voz premium
```

### Sin APIs de terceros para el caso básico
Chrome y Edge tienen reconocimiento de voz nativo. Funciona sin Google Cloud, sin cuentas, sin costo.

### Archivo a crear
```
src/openacm/channels/voice_channel.py   ← lógica backend
frontend/components/VoiceInput.tsx      ← componente UI
```

---

## Ventajas exclusivas de despliegue en servidor

El shift fundamental al montar en servidor:

> **De "asistente que ayuda cuando le hablas" → a "servicio autónomo que trabaja mientras duermes"**

| Capacidad | Local | Servidor |
|-----------|-------|----------|
| Proactive Engine | Se pausa si apagas la PC | Corre 24/7 |
| Webhooks | Necesita ngrok/tunnel | IP/dominio público real |
| Multi-usuario | Solo tú | Múltiples clientes simultáneos |
| Email channel | Limitado | MX record propio posible |
| Background jobs | Mueren con el proceso | Persistentes |
| SSL/HTTPS | Manual | Automático con Caddy |
| Escala | 1 instancia | Load balancer posible |

### Casos de uso que solo existen en servidor

```
02:00 AM  → genera reporte de ventas del día → manda por email (nadie lo pidió)
Cada 5min → monitorea servidor del cliente → si cae, alerta en <1min
GitHub push → OpenACM revisa el código automáticamente → comenta en el PR
Cliente manda email → OpenACM responde en <30s → sin intervención humana
Precio baja de umbral → OpenACM compra / alerta / actúa → mientras duermes
```

---

## Stack de servidor recomendado

### Configuración ideal para producción

```yaml
# docker-compose.prod.yml

services:

  openacm:
    build: .
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://openacm:pass@postgres/openacm
      - REDIS_URL=redis://redis:6379
    depends_on:
      - postgres
      - redis

  worker:
    build: .
    command: python -m openacm --worker   # proceso separado para jobs pesados
    restart: unless-stopped
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    # SQLite no escala en servidor, PostgreSQL es la base correcta

  redis:
    image: redis:7-alpine
    # Cola de jobs (Proactive Engine + background tasks)
    # Cache de sesiones y rate limiting

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
    # Reverse proxy + SSL automático con Let's Encrypt
    # Zero config para HTTPS

volumes:
  postgres_data:
```

### Caddyfile (SSL automático)
```
openacm.tudominio.com {
    reverse_proxy openacm:8080
}
```
Un solo archivo. Caddy obtiene el certificado SSL solo, sin certbot, sin configuración manual.

### Por qué este stack

| Componente | Por qué |
|------------|---------|
| **PostgreSQL** | SQLite no soporta escrituras concurrentes. Con múltiples usuarios o workers, PostgreSQL es necesario. |
| **Redis** | Cola de jobs para el Proactive Engine y background tasks. También cache para reducir llamadas a la DB. |
| **Worker separado** | Los jobs largos (generar reportes, procesar archivos grandes, monitoreo) no deben bloquear las requests del usuario. |
| **Caddy** | SSL automático sin configuración. Más simple que nginx + certbot. Perfecto para un solo servidor. |

### Proveedor de servidor recomendado
Para empezar con costo mínimo y buena performance:

| Opción | Specs mínimos | Costo aprox |
|--------|--------------|-------------|
| **Hetzner CX22** | 2 vCPU, 4GB RAM, 40GB SSD | ~$4/mes |
| **DigitalOcean Basic** | 2 vCPU, 2GB RAM | ~$12/mes |
| **Contabo VPS S** | 4 vCPU, 8GB RAM | ~$5/mes |

Hetzner es la mejor relación precio/performance para Europa. Contabo para más RAM barata.

### Cambios necesarios en el código para soportar este stack

```
src/openacm/storage/database.py   → agregar soporte PostgreSQL (además de SQLite)
src/openacm/core/job_queue.py     → cola de jobs con Redis (para worker separado)
src/openacm/core/config.py        → leer DATABASE_URL y REDIS_URL del entorno
```

---

## Plan 13 — Swarm Compute (Enjambre de Ejecución)

### Qué es
La intersección del Plan 12 (Local Agent) y el Plan 8 (Multi-agent Orchestration). OpenACM no solo distribuye lógica de LLM entre agentes — distribuye **carga de trabajo real entre hardware físico**.

Todos los dispositivos con un Local Agent instalado forman un clúster unificado que el orquestador usa de forma transparente.

### El concepto

```
Sin Swarm:   OpenACM → un agente → una máquina → hace todo secuencialmente

Con Swarm:   OpenACM → orquestador → detecta qué máquina tiene recursos
                                    → distribuye tareas al hardware disponible
                                    → las tareas corren en paralelo
                                    → consolida resultados
```

### Caso de uso concreto

```
Usuario: "compila el proyecto y renderiza este video 4K"

Orquestador consulta estado de todos los agentes conectados:
  ├── "mi-pc"   → CPU: 87% (compilando), RAM: 72%, GPU: 15%
  ├── "laptop"  → CPU: 12%, RAM: 38%, GPU: 78% (libre)
  └── "raspi"   → CPU: 45%, RAM: 60%, GPU: N/A

Decisión automática:
  → Build del proyecto    ── "mi-pc"  (ya tiene el código, sigue compilando)
  → Render 4K del video   ── "laptop" (GPU libre, CPU disponible)

Ejecución:
  → Transfiere el video a laptop
  → Ambas máquinas trabajan en paralelo
  → Orquestador espera ambos resultados
  → Consolida y responde al usuario

Tiempo total: el de la tarea más larga (no la suma de las dos)
```

### Lo que hace el Local Agent adicionalmente

Además de ejecutar comandos, cada agente reporta su estado al servidor periódicamente:

```json
{
  "agent": "laptop",
  "heartbeat": {
    "cpu_percent": 12.4,
    "ram_percent": 38.1,
    "gpu_percent": 78.0,
    "disk_free_gb": 120.5,
    "capabilities": ["run_command", "file_ops", "screenshot", "ffmpeg", "python"],
    "active_tasks": 0
  }
}
```

`system_info.py` ya usa `psutil` — ya sabe leer CPU/RAM/disco. El agente solo necesita enviarlo al servidor cada N segundos.

### Resource-aware Scheduler

El orquestador ya existente (Plan 8) necesita una capa adicional: antes de asignar una tarea, consulta el heartbeat de los agentes y elige el más adecuado.

```python
# Lógica de asignación (simplificada)

def pick_agent(task_type, agents):
    if task_type == "gpu_render":
        return max(agents, key=lambda a: a.gpu_free)
    if task_type == "compile":
        return max(agents, key=lambda a: a.cpu_free * a.ram_free)
    if task_type == "file_processing":
        return max(agents, key=lambda a: a.disk_free)
    return min(agents, key=lambda a: a.active_tasks)  # fallback: menos ocupado
```

### Casos de uso

| Tarea | Quién la recibe | Por qué |
|-------|----------------|---------|
| Compilar código | Máquina con el repo | Evita transferencia de archivos |
| Render 3D / video | Máquina con GPU libre | Usa el hardware correcto |
| Procesar dataset grande | Máquina con más RAM | No satura la principal |
| Web scraping masivo | Cualquier máquina libre | Distribuye las requests |
| Tests paralelos | Todas las máquinas | Cada una corre un subset |
| Backup | Máquina con disco libre | No interrumpe trabajo activo |

### Transferencia de archivos entre agentes

El punto crítico: si laptop tiene que renderizar un video que está en mi-pc, hay que transferirlo.

```
Opción A (simple):   via servidor central
  mi-pc → upload a OpenACM server → laptop descarga

Opción B (eficiente): peer-to-peer directo
  mi-pc ←→ laptop directo en la red local (más rápido, sin pasar por internet)
  El servidor solo coordina — no mueve los datos

Opción B es preferible para archivos grandes en red local
```

### Comparación con alternativas

| Sistema | Complejidad | Requiere | OpenACM Swarm |
|---------|------------|---------|---------------|
| Kubernetes Jobs | Alta | Cluster k8s, Docker | Solo Local Agent |
| Apache Spark | Alta | JVM, configuración | Solo Local Agent |
| Ray (Python) | Media | Instalación específica | Solo Local Agent |
| **OpenACM Swarm** | **Baja** | **Local Agent ya instalado** | **Automático** |

No requiere infraestructura especial. Si el Local Agent está instalado para el Plan 12, el Swarm es gratis — solo hay que activar el scheduler en el orquestador.

### Archivos a modificar/crear

```
src/openacm/core/orchestrator.py        ← agregar resource-aware scheduler
openacm-agent/agent.py                  ← agregar heartbeat periódico con psutil
src/openacm/core/swarm_registry.py      ← tabla de agentes + sus recursos actuales
```

### Seguridad

Hereda todo el modelo del Plan 12. Adicionalmente:
- Las tareas distribuidas llevan la misma firma HMAC
- El agente destino verifica que tiene la capability requerida antes de aceptar
- Los archivos transferidos van cifrados (Fernet, ya existe en `crypto.py`)
- El audit log registra en qué máquina corrió cada tarea

---

## Plan 14 — MQTT

### Por qué el sistema lo sigue pidiendo
OpenACM ya controla dispositivos IoT (Tuya, LG TV, Xiaomi) pero con protocolos propietarios. MQTT es el protocolo estándar universal de IoT — miles de dispositivos lo hablan nativamente: Arduino, ESP32, Raspberry Pi, sensores industriales, Home Assistant, Node-RED, y cualquier sistema custom.

Sin MQTT, cada dispositivo nuevo requiere un driver nuevo. Con MQTT, cualquier cosa que publique en un topic ya es un ciudadano de primera clase en OpenACM.

### Dos modos de operación

**Modo subscriber — escuchar el mundo**
```
OpenACM se suscribe a topics MQTT
→ Reacciona en tiempo real a eventos de sensores y dispositivos
→ Alimenta directamente el Proactive Engine
```

**Modo publisher — controlar el mundo**
```
OpenACM publica comandos en topics MQTT
→ Cualquier dispositivo suscrito los ejecuta
→ Sin necesidad de saber el protocolo propietario del dispositivo
```

### Combinación con el Proactive Engine

Aquí es donde MQTT brilla:

```
# Ejemplos de reglas automáticas

Sensor temperatura publica: {"temp": 32}
→ OpenACM detecta > 30°C
→ Publica en topic AC: {"power": "on", "temp": 22}
→ Manda notificación WhatsApp: "Encendí el AC, hacía 32°C"

Sensor de puerta publica: {"state": "open", "time": "03:14"}
→ OpenACM detecta hora inusual
→ Enciende luces, toma screenshot de cámara, notifica

Máquina industrial publica: {"status": "error", "code": "E42"}
→ OpenACM busca el código en el manual (RAG)
→ Crea ticket en el sistema de soporte
→ Alerta al técnico de turno por Telegram
```

### Casos de uso reales

| Escenario | Publisher | Subscriber | Acción |
|-----------|-----------|------------|--------|
| Smart Home | Sensores, switches | OpenACM | Automatización con contexto e IA |
| Industria 4.0 | Sensores de producción | OpenACM | Detección de anomalías + alertas |
| Agricultura | Sensores de humedad/temp | OpenACM | Riego automático inteligente |
| Home Assistant | Home Assistant broker | OpenACM | Bridge bidireccional con HA |
| Arduino/ESP32 | Dispositivos custom | OpenACM | Control de hardware DIY |

### Integración con lo existente

```
IoT actual:                      Con MQTT:
Tuya  → driver propio            Tuya  → driver propio  (sin cambios)
LG TV → driver propio            LG TV → driver propio  (sin cambios)
Xiaomi → driver propio           Xiaomi → driver propio (sin cambios)
                                 MQTT  → cualquier device nuevo (automático)
                                 Home Assistant → bridge completo
                                 Arduino/ESP32 → directo
```

MQTT no reemplaza los drivers existentes — los complementa como protocolo universal para todo lo demás.

### Archivos a crear

```
src/openacm/tools/iot/drivers/mqtt_driver.py   ← publisher + subscriber
src/openacm/core/mqtt_bus.py                   ← broker interno + routing a Proactive Engine
config/mqtt.yaml                               ← broker URL, topics, reglas
```

### Config propuesta

```yaml
# config/mqtt.yaml

broker:
  host: "localhost"        # o tu broker externo (Home Assistant, Mosquitto)
  port: 1883
  tls: false               # true para brokers públicos

subscriptions:
  - topic: "casa/sensores/#"     # wildcard — todos los sensores
    handler: proactive_engine    # dispara reglas del Proactive Engine

  - topic: "industria/maquinas/+"
    handler: alert_on_error      # alerta si hay error

publish_prefix: "openacm/"      # OpenACM publica bajo este prefijo
```

---



| Fase | Plan | Local/Servidor | Impacto | Esfuerzo |
|------|------|---------------|---------|----------|
| 1 | UIB (WebSocket externo) | Ambos | Alto |  |
| 1 | COM Adapter para Excel | Local | Alto | |
| 1 | Voice Channel | Ambos | Alto |  |
| 2 | Adapter System (base) | Ambos | Alto |  |
| 2 | Inbound Webhooks | Servidor | Alto |  |
| 2 | Email Channel | Servidor | Alto |  |
| 3 | Proactive Engine | Servidor > Local | Muy Alto |  |
| 3 | Declarative YAML Tools | Ambos | Medio |  |
| 3 | Multi-agent Orchestration | Ambos | Alto |  |
| 4 | Long-term Memory | Ambos | Alto |  |
| 4 | Self-Evolution Engine | Ambos | Muy Alto |  |
| 4 | Stack servidor prod | Servidor | Infraestructura |  |
| 4 | MQTT | Ambos | Alto | ~2h |
| 4 | Swarm Compute | Ambos | Muy Alto |  (sobre Plan 8 + 12) |
| 5 | GUI Automation fallback | Local | Medio |  |

---

## Plan 12 — Local Agent

### Qué es
Un cliente ultraligero que corre en cualquier PC y se conecta al servidor OpenACM via WebSocket. Permite que el servidor controle la máquina local sin exponer ningún puerto, sin VPN, sin configuración de red.

### Arquitectura de conexión

```
Servidor OpenACM (público)          PC Local (detrás de NAT/firewall)
         │                                      │
         │    ←── Local Agent inicia conexión ──│
         │         wss://openacm.dominio.com     │
         │                                      │
         │ ──── "ejecuta screenshot" ──────────►│
         │ ◄─── resultado ─────────────────────│
         │                                      │
         │ ──── "corre comando X" ─────────────►│ ← agente decide si es permitido
         │ ◄─── output ────────────────────────│
```

El agente **inicia** la conexión (outbound). No abre puertos. Funciona detrás de cualquier firewall o NAT sin configuración.

### Multi-máquina natural

```
Servidor OpenACM
    ├── agent:"mi-pc"        → tu escritorio en casa
    ├── agent:"laptop"       → tu laptop
    ├── agent:"oficina-mx"   → PC de la oficina
    └── agent:"cliente-sap"  → máquina con SAP del cliente
```

### Archivo a crear
```
openacm-agent/
  agent.py          ← cliente WebSocket + ejecutor local
  config.yaml       ← capacidades permitidas + límites
  install.sh        ← instala como servicio del sistema
```

---

### Seguridad del Local Agent — el punto crítico

Aquí es donde brilla (y donde más duele si se hace mal).

**El problema fundamental:**
> Si el servidor se compromete, el atacante tiene un canal directo a tu PC.
> El agente local NO puede confiar ciegamente en el servidor.

Modelo: **Zero Trust hacia el servidor**.

---

#### Capa 1 — Transport (lo básico)

```
WSS (WebSocket Secure) obligatorio — nunca WS en texto plano
Certificate pinning opcional — el agente verifica que el certificado
                               del servidor sea exactamente el esperado,
                               no solo que sea válido
```

El `crypto.py` existente ya maneja Fernet para cifrado simétrico. Extenderlo para el canal del agente.

---

#### Capa 2 — Autenticación mutua

```
Servidor → Agente:  JWT firmado con clave privada del servidor
Agente → Servidor:  Token único por máquina (generado en instalación)

Ambos se autentican mutuamente — ni el servidor acepta agentes
desconocidos, ni el agente acepta servidores sin firma válida.
```

Token por máquina:
```yaml
# config/agent-token.yaml  (generado en instalación, nunca viaja al servidor completo)
machine_id: "mi-pc-uuid-unico"
token_hash: "sha256 del token real"   ← el servidor guarda solo el hash
```

---

#### Capa 3 — Capability Manifest (la más importante)

El agente declara explícitamente qué puede hacer. **Si no está en el manifest, se rechaza sin importar quién lo pida.**

```yaml
# config/capabilities.yaml

capabilities:
  - name: screenshot
    risk: low
    confirmation: never

  - name: run_command
    risk: high
    confirmation: always          # ← requiere aprobación local antes de ejecutar
    allowed_commands:             # whitelist explícita
      - "git status"
      - "git pull"
      - "npm test"
      - "pytest"
    blocked_patterns:             # reusa policies.py existente
      - "rm -rf"
      - "format"
      - "del /f"
      - "DROP TABLE"

  - name: file_read
    risk: low
    confirmation: never
    allowed_paths:
      - "~/proyectos/"
      - "~/documentos/"
    blocked_paths:
      - "~/.ssh/"
      - "~/.aws/"
      - "/etc/"

  - name: file_write
    risk: medium
    confirmation: on_new_file     # confirma solo si el archivo no existía
    allowed_paths:
      - "~/proyectos/"
```

El servidor puede pedir lo que quiera. El agente filtra contra este manifest antes de ejecutar cualquier cosa. Las `policies.py` existentes se reutilizan directamente aquí.

---

#### Capa 4 — Command Signing

Cada comando que envía el servidor viene firmado digitalmente:

```json
{
  "type": "invoke",
  "capability": "run_command",
  "args": { "command": "git pull" },
  "id": "abc123",
  "timestamp": 1234567890,
  "signature": "HMAC-SHA256(payload, server_secret)"
}
```

El agente verifica la firma antes de ejecutar. Si alguien intercepta la conexión y manda comandos falsos, la firma no valida y se rechaza.

Timestamp incluido para prevenir **replay attacks** — un comando capturado no puede enviarse de nuevo 5 minutos después.

---

#### Capa 5 — Audit Log local

Todo queda registrado localmente en la máquina, independiente del servidor:

```
[2026-03-29 14:32:01] EJECUTADO   run_command "git pull"           OK  (solicitado por servidor)
[2026-03-29 14:35:22] RECHAZADO   run_command "rm -rf /tmp/test"   BLOCKED: blocked_pattern
[2026-03-29 14:40:11] CONFIRMADO  file_write  "nuevo_archivo.py"   OK  (aprobado por usuario local)
[2026-03-29 14:41:00] RECHAZADO   file_read   "~/.ssh/id_rsa"      BLOCKED: blocked_path
```

El log vive en la máquina local. Incluso si el servidor es malicioso y borra sus propios logs, el agente tiene su registro independiente.

---

#### Capa 6 — Confirmación local para acciones destructivas

Para comandos con `risk: high` o `confirmation: always`, el agente puede mostrar una notificación nativa del sistema operativo:

```
┌─────────────────────────────────────┐
│  OpenACM Local Agent                │
│                                     │
│  El servidor solicita ejecutar:     │
│  > git push origin main             │
│                                     │
│  [Permitir]  [Denegar]  [Ver log]   │
└─────────────────────────────────────┘
```

El servidor espera respuesta. Si el usuario no responde en X segundos → denegado automáticamente.

---

#### Capa 7 — Kill Switch

Si detecta comportamiento anómalo (demasiadas peticiones, comandos fuera de patrón, firma inválida repetida):

```python
# El agente se desconecta solo y requiere reconexión manual
# Notifica al usuario local que algo raro pasó
# Registra el incidente en el audit log
```

---

### Resumen del modelo de seguridad

```
Internet / Servidor comprometido
         │
         ▼
   ┌─────────────────────────────────────────┐
   │  WSS + Certificate Pinning              │  ← Capa 1: nadie intercepta
   │  Autenticación mutua + JWT              │  ← Capa 2: solo servidores legítimos
   │  Command Signing + Timestamp            │  ← Capa 3: no replay attacks
   │  Capability Manifest (whitelist)        │  ← Capa 4: scope limitado
   │  policies.py (blocked patterns)         │  ← Capa 5: comandos peligrosos
   │  Confirmación local (risk: high)        │  ← Capa 6: humano en el loop
   │  Audit Log local independiente          │  ← Capa 7: trazabilidad
   │  Kill Switch automático                 │  ← Capa 8: auto-protección
   └─────────────────────────────────────────┘
         │
         ▼
      Tu PC — solo ejecuta lo que está en el manifest

```

### Reutilización de lo existente

| Componente existente | Rol en el agente |
|---------------------|-----------------|
| `security/sandbox.py` | Ejecuta comandos locales con los mismos límites |
| `security/policies.py` | Valida comandos contra blocked_patterns del manifest |
| `security/crypto.py` | Cifrado del canal + verificación de firmas |
| `security/auth.py` | Base para autenticación mutua |

No se escribe seguridad desde cero — se reutiliza y se extiende lo que ya existe.

---



- Los adapters deben ser **opcionales** — si el paquete requerido no está instalado, el adapter simplemente no carga
- El UIB debe tener **autenticación** igual que el dashboard (token-based)
- Los adapters generados por el Evolver van a `adapters/generated/` igual que skills y tools
- GUI Automation solo en Windows por ahora (uiautomation es Windows-only)
- Todos los adapters deben seguir el mismo patrón que los channels existentes en `src/openacm/channels/`
- Migrar de SQLite a PostgreSQL es condición necesaria antes de desplegar en servidor con múltiples usuarios
- El worker separado debe compartir el mismo codebase, solo cambia el comando de entrada
