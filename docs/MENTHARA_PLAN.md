# Menthara — Plan Arquitectural Completo

> Fecha: 2026-05-04  
> Estado: BORRADOR v1 — pendiente de aprobación  
> Basado en: OpenACM SwarmManager (migración con adapters)

---

## 0. Goal — Lo que estamos construyendo

**Menthara es una plataforma SaaS B2B que convierte cualquier documentación de proceso en una capacitación interactiva lista para publicar, sin que el usuario tenga que saber nada de diseño instruccional ni de IA.**

Una empresa llega con sus PDFs, manuales, videos y explicaciones de cómo funciona un proceso — industrial, administrativo, técnico, lo que sea — y Menthara, usando swarms de agentes de IA corriendo en Azure, genera automáticamente:

1. **Un Excel estructurado** con el paso a paso del proceso (compatible con la plataforma de capacitación que ya tienen), que el usuario puede revisar y ajustar inline antes de aprobar.
2. **Una web de capacitación interactiva** completa, con texto narrativo, quizzes de evaluación y visualizaciones (Lottie/CSS en MVP, Three.js en versiones premium), lista para ser publicada y consumida por los empleados de la empresa.

El proceso es completamente asistido: los agentes analizan los archivos, hacen preguntas de clarificación al usuario cuando necesitan más contexto, y trabajan en paralelo para que el resultado llegue en el menor tiempo posible. Cada empresa tiene su propia instancia aislada; 100 empresas generando al mismo tiempo no se afectan entre sí.

**Modelo de negocio:** Licencias B2B por cantidad de usuarios. Tier base: $500 USD/empresa.  
**Stack central:** Python/FastAPI + Azure OpenAI + Azure Container Apps Jobs + React (Vite).  
**Origen del motor de swarms:** Migrado desde OpenACM (no reescrito desde cero).

---

## 1. Qué es Menthara

Plataforma SaaS B2B que convierte documentos de proceso (PDF, DOCX, Excel, video) en capacitaciones interactivas generadas por IA. Las empresas compran licencias por cantidad de usuarios.

**Flujo completo:**

```
Usuario describe el proceso
       ↓
Sube archivos (PDF / DOCX / Excel / video)
       ↓
[SWARM 1 — Analyzer]
  - Extrae texto de todos los archivos
  - Transcribe audio de videos
  - Analiza contenido en paralelo
  - Genera preguntas de clarificación
       ↓
Usuario responde preguntas en la plataforma
       ↓
[SWARM 1 cont. — Excel Generator]
  - Genera el Excel paso a paso (template fijo)
       ↓
Usuario revisa el Excel inline en el browser
  → Edita celdas directamente
  → O escribe "cambia X por Y" → Editor Agent lo modifica
  → Aprueba
       ↓
[SWARM 2 — Training Generator]
  - Genera web de capacitación interactiva (con quizzes, Three.js, etc.)
       ↓
Capacitación lista → se sube a la plataforma existente
```

---

## 2. Decisión Arquitectural: Migrar vs Reescribir

**Decisión: Migrar el SwarmManager de OpenACM con adapters de Azure.**

El `SwarmManager` de OpenACM tiene lógica sólida que no vale la pena reescribir:
- Planificación de tasks con LLM
- Ejecución paralela con `asyncio.gather` y dependencias
- Comunicación worker-to-worker
- Reinicio automático de tasks huérfanas
- Sistema de reintentos con contadores persistentes

Lo que se reemplaza con adapters Azure-native:

| OpenACM (actual) | Menthara (Azure) |
|---|---|
| SQLite | Azure PostgreSQL Flexible Server |
| Filesystem local | Azure Blob Storage |
| LLMRouter (Anthropic/local) | Azure OpenAI Service |
| EventBus + WebSocket | Azure SignalR Service |
| FastAPI embebido | FastAPI en Container App dedicado |
| Workspace local | Blob container por swarm |

**Por qué no reescribir:** La lógica de planning/execution es compleja y ya está probada. Los adapters son ~20% del trabajo. Reescribir sería 3-4 semanas extra sin beneficio real.

---

## 3. Infraestructura Azure

### 3.1 Servicios seleccionados (calidad/precio)

| Servicio | Uso | Tier recomendado | Costo est./mes |
|---|---|---|---|
| **Azure Container Apps** | API backend + Swarm workers | Consumption (pay-per-use) | $30–150 |
| **Azure Container Apps Jobs** | Cada swarm corre como Job aislado | Consumption | incluido |
| **Azure Queue Storage** | Cola entre API y workers | Standard | ~$5 |
| **Azure Blob Storage** | Archivos subidos + outputs | LRS Standard | $10–30 |
| **Azure Database for PostgreSQL Flexible** | Base de datos principal | Burstable B2ms (2vCPU) | $50–70 |
| **Azure AI Foundry** | LLM (kimi-k2) + embeddings para AI Search | Model Catalog | pay-per-token |
| **Azure AI Search** | Índice híbrido compartido — document cracking, chunking, embeddings, retrieval | Standard S1 | ~$75 |
| **Real-time WebSocket** | Eventos al frontend | FastAPI WS + PG NOTIFY (ver §3.4) | **$0 extra** |
| **Azure AI Speech** | Transcripción de video → texto indexable | Standard | $1/hora audio |
| **Azure Static Web Apps** | Frontend React SPA | Free | $0 |
| **Azure Container Registry** | Imágenes Docker | Basic | $5 |

> **Azure Document Intelligence eliminado** — Azure AI Search tiene document cracking nativo para PDF/DOCX/Excel. Solo se necesitaría Doc Intelligence para layouts muy complejos (tablas anidadas, formularios) en V2.

**Total infraestructura (sin AI tokens): ~$200–340/mes**  
**AI tokens (kimi-k2 vía AI Foundry):** Muy variable — un swarm completo con documentos medianos: ~$0.20–1.50 USD (kimi-k2 es más barato que GPT-4o).

Con licencia base de $500 USD/empresa y asumiendo ~10 swarms/mes por empresa, el margen es viable desde el primer cliente.

### 3.2 Real-time sin SignalR — PostgreSQL NOTIFY + WebSockets nativos

Azure SignalR cuesta $50/mes y no es necesario. Ya tenés PostgreSQL en el stack, y PostgreSQL tiene **LISTEN/NOTIFY** nativo — un pub/sub asíncrono que hace exactamente lo que se necesita, gratis.

**Cómo funciona:**

```
SwarmManager Job
  → pg_notify('swarm_events', payload_json)   ← escribe en PG, costo $0

API Container App (FastAPI)
  → asyncpg listener en background             ← escucha el canal
  → recibe el payload
  → broadcast a WebSockets del swarm_id        ← FastAPI native WebSocket

Browser ← WebSocket nativo ← API
```

**Código en el Swarm Job (emitir evento):**
```python
await db.execute(
    "SELECT pg_notify('swarm_events', $1)",
    json.dumps({"swarm_id": swarm_id, "type": "swarm:task_updated", "data": {...}})
)
```

**Código en la API (escuchar y distribuir):**
```python
# Mapa de conexiones activas: swarm_id → set de WebSocket
ws_connections: dict[int, set[WebSocket]] = defaultdict(set)

async def pg_listener_loop():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.add_listener("swarm_events", on_swarm_event)
    while True:
        await asyncio.sleep(3600)  # mantiene viva la conexión

async def on_swarm_event(conn, pid, channel, payload):
    event = json.loads(payload)
    for ws in ws_connections.get(event["swarm_id"], set()):
        await ws.send_json(event)
```

Esto es exactamente lo que hace el `EventBus` de OpenACM — solo cambia el transporte de in-process a cross-process vía PostgreSQL.

**La única limitación: múltiples pods del API**

Si el Container App del API escala a 2+ réplicas, cada pod tiene sus propias conexiones WebSocket en memoria. Un NOTIFY llega a todas las réplicas (PG broadcast a todos los listeners), así que cada pod recibe el evento y hace broadcast solo a sus conexiones locales. **Esto funciona correctamente** — el cliente conectado a Pod A recibe el evento aunque el Job esté conectado a Pod B.

> Si a futuro necesitás más de ~5 réplicas del API simultáneas, el siguiente paso es agregar **Azure Cache for Redis** (~$15–20/mes) como pub/sub central. Pero para MVP y escala mediana, PG NOTIFY es más que suficiente.

| Opción | Costo/mes | Complejidad | Escala a N pods |
|---|---|---|---|
| **PG NOTIFY + FastAPI WS** (recomendado MVP) | $0 extra | Baja — ya tenés PG | ✅ Funciona (PG broadcast a todos) |
| Azure Cache for Redis + FastAPI WS | $15–20 | Media | ✅ Explícito y robusto |
| Azure SignalR Service | $50 | Baja | ✅ Managed |

**Decisión: PG NOTIFY para MVP. Redis solo si se necesitan 5+ réplicas del API simultáneas.**

---

### 3.3 Por qué Container Apps Jobs (no Functions, no AKS)

- **Azure Functions:** timeout de 10 min (Standard). Un swarm puede durar 30+ min. Descartado.
- **AKS:** Demasiado complejo y caro para MVP. Overkill.
- **Container Apps Jobs:** Cada swarm es un Job independiente. 100 usuarios = 100 Jobs corriendo en paralelo sin afectarse. Se factura por vCPU-segundo consumido. Sin timeout rígido. **Elegido.**

### 3.4 Flujo de datos en Azure

```
Browser
  │
  ├─→ Azure Static Web Apps (React SPA)
  │
  └─→ Azure Container App (FastAPI API)
        │
        ├─[WebSocket]─→ Browser  ← eventos real-time (FastAPI native)
        │
        ├─→ Azure Queue Storage  ← encola swarm jobs
        │         │
        │         └─→ Container Apps Jobs (SwarmManager)
        │                 │
        │                 ├─→ Azure Blob Storage (archivos + outputs)
        │                 ├─→ Azure AI Foundry (kimi-k2 + embeddings)
        │                 ├─→ Azure AI Search (queries híbridas al índice)
        │                 ├─→ Azure AI Speech (solo video)
        │                 └─→ Azure PostgreSQL ← pg_notify(eventos)
        │                                           ↑
        └─→ Azure PostgreSQL ────────────────────────┘
              (estado + LISTEN/NOTIFY para real-time)
```

---

## 4. Repositorios y Estructura

Menthara vive en **dos repositorios separados** (ambos ya existen parcialmente):

---

### 4.1 Frontend — `MentharaFront` (ya existe, se extiende)

**Repo:** `C:\Trabajo\QRStudio\Menthara\MentharaFront`  
**Stack real:** React 18 + Create React App + **JavaScript** (sin TypeScript) + Material-UI v6 + Redux + React Router DOM v6

Este frontend ya tiene construido el núcleo de la plataforma de gestión de procedimientos. Menthara reutiliza todo lo que existe y agrega las pantallas del flujo de generación con IA.

**Lo que ya existe y se reutiliza tal cual:**

| Componente existente | Ubicación | Reutilizado en Menthara para |
|---|---|---|
| `Table.jsx` | `pages/Procedure_Tasks/Table/` | **Revisión del Excel generado** — ya muestra tareas con drag-drop, filtros, edición inline |
| `CardEditModal.jsx` | `Table/CardEditModal/` | **Edición de tareas** del Excel generado |
| `procedures_flow/` | `pages/Procedure_Tasks/` | **Vista de dependencias** del paso a paso |
| `Tablet.jsx` | `pages/Tablet/` | **Preview de la capacitación** generada por Swarm 2 |
| `bulk_load.jsx` | `pages/Procedure_Tasks/bulk_load/` | **Upload del Excel** generado (ya conecta a `POST /bulkLoad/{procedureId}`) |
| Auth (Axios.js + usersReducer) | `Config/` + `Reducers/` | **Auth completo** — Bearer token ya implementado |
| Redux store | `Config/store.js` | Se extiende con nuevos reducers para Menthara |

**Lo que se agrega (páginas nuevas de Menthara):**

```
src/pages/
├── MentharaProjects/              # NUEVO — lista de proyectos de generación
│   └── MentharaProjects.jsx
└── MentharaGeneration/            # NUEVO — flujo completo de generación (state machine)
    ├── MentharaGeneration.jsx     # Switch sobre project.status → renderiza la vista correcta
    ├── UploadView/                # NUEVO — describir proceso + subir archivos
    ├── ProgressView/              # NUEVO — swarm corriendo (WebSocket)
    ├── QuestionsView/             # NUEVO — responder preguntas del swarm
    ├── ReviewView/                # REUTILIZA Table.jsx existente + nuevo botón "Aprobar"
    └── TrainingPreviewView/       # REUTILIZA Tablet.jsx existente

src/Actions/
└── mentharaGeneration.js          # NUEVO — actions Redux para el flujo de generación

src/Reducers/
└── mentharaGenerationReducer.js   # NUEVO — estado del swarm, project, status

src/helpers/
└── hooks/
    └── useMentharaWS.js           # NUEVO — WebSocket con reconexión automática
```

**Nuevas rutas en App.js:**
```jsx
// Dentro del Dashboard ya autenticado
<Route path="/menthara/*" element={<MentharaProjects />} />
<Route path="/menthara/:projectId/*" element={<MentharaGeneration />} />
```

**Template Excel ya conocido:**  
`https://xdprocedures.blob.core.windows.net/files/PlantillaProcedures.xlsx`  
El `excel_filler.py` del Swarm 1 usa exactamente este template. Al aprobarse, se sube vía `POST /bulkLoad/{procedureId}` al sistema existente.

**Estructura de tarea ya definida** (el Swarm 1 debe generar datos en este formato):
```js
{
  order: number,
  description: string,
  location: string,
  vrdescription: string,
  guidepractice: "G" | "G/P" | "E" | "P",
  typetask: 0 | 1,
  id_pre_task: string,          // IDs de tareas prerequisito separados por coma
  task_translations: [{
    name: string,               // nombre del idioma
    code: string,               // "es", "en", etc.
    audio_vo: string,           // texto para narración
    suporting_written_text: string
  }]
}
```

---

### 4.2 Backend + Swarms — `menthara-api` (nuevo repo)

**Stack:** Python 3.12 + FastAPI + asyncpg  
**Deploy:** Azure Container Apps (API) + Azure Container Apps Jobs (Swarms)

```
menthara-api/
├── api/                           # FastAPI
│   ├── main.py
│   ├── routers/
│   │   ├── projects.py            # CRUD proyectos de generación
│   │   ├── swarms.py              # Lanzar/monitorear swarms
│   │   ├── files.py               # Upload archivos a Blob Storage
│   │   ├── excel.py               # Editor Agent + aprobación + bulk upload al sistema
│   │   └── ws.py                  # WebSocket endpoint + PG NOTIFY listener
│   ├── middleware/
│   │   └── auth.py                # Valida Bearer token del sistema externo
│   └── db/
│       ├── models.py
│       └── migrations/            # Alembic
│
├── swarm_engine/                  # SwarmManager migrado de OpenACM
│   ├── swarm_manager.py
│   ├── swarm_tools.py
│   └── adapters/
│       ├── base.py
│       ├── llm_adapter.py         # Azure OpenAI + Azure AI Foundry
│       ├── azure_storage.py
│       ├── pg_notify.py
│       └── postgres.py
│
├── swarms/
│   ├── swarm1_analyzer/
│   │   └── workers/
│   │       ├── file_ingester.py   # Azure Doc Intelligence + Speech
│   │       ├── content_analyzer.py
│   │       ├── process_mapper.py
│   │       ├── question_generator.py
│   │       ├── step_designer.py
│   │       └── excel_filler.py    # Genera PlantillaProcedures.xlsx con openpyxl
│   └── swarm2_training/
│       └── workers/
│           ├── content_structurer.py
│           ├── script_writer.py
│           ├── quiz_creator.py
│           ├── visual_planner.py
│           ├── component_generator.py
│           ├── quiz_integrator.py
│           └── assembler.py
│
├── tools/
│   ├── document_intel.py
│   ├── speech.py
│   ├── excel_reader.py            # Celdas → JSON para Editor Agent
│   └── excel_patcher.py           # JSON patch → openpyxl (determinista)
│
├── infra/                         # Azure Bicep
│   ├── main.bicep
│   ├── container-apps.bicep
│   ├── storage.bicep
│   └── postgres.bicep
│
├── docker/
│   ├── Dockerfile.api
│   └── Dockerfile.worker
│
└── .github/workflows/
    ├── deploy-api.yml
    └── deploy-worker.yml
```

---

## 5. Modelo de Datos (PostgreSQL)

```sql
-- Multi-tenant desde el inicio
tenants (id, name, plan, max_users, created_at)
users (id, tenant_id, external_id, email, role, created_at)

-- Proyectos de capacitación
projects (
  id, tenant_id, user_id,
  title, description, status,
  -- status: draft | analyzing | waiting_questions | 
  --         generating_excel | review | approved | 
  --         generating_training | completed | failed
  created_at, updated_at
)

-- Archivos subidos
project_files (
  id, project_id,
  filename, blob_url, file_type,
  -- file_type: pdf | docx | excel | video | other
  size_bytes, processed, extracted_text,
  created_at
)

-- Preguntas generadas por Swarm 1
project_questions (
  id, project_id,
  question_text, answer_text,
  order_idx, answered_at
)

-- Excel generado (metadata + referencia al blob)
project_excel (
  id, project_id,
  blob_url, version,
  approved, approved_at, approved_by,
  created_at
)

-- Swarms (migrado de OpenACM, con tenant_id)
swarms (
  id, project_id, tenant_id,
  swarm_type,  -- 'analyzer' | 'training'
  status, goal, global_model,
  job_id,  -- Azure Container Apps Job execution ID
  created_at, completed_at
)

swarm_workers (id, swarm_id, name, role, azure_service, model, status, output, last_heartbeat)
-- azure_service: 'azure_openai' | 'azure_ai_foundry'
swarm_tasks   (id, swarm_id, worker_id, description, status, result, depends_on)
swarm_messages(id, swarm_id, from_worker, to_worker, content, created_at)

-- Training web generada
training_outputs (
  id, project_id,
  blob_url,  -- ZIP con la web completa
  version, published_url,
  created_at
)
```

---

## 6. Diseño de los Swarms

### 6.1 Swarm 1 — Document Analyzer & Excel Generator

**Pre-swarm — Indexación (ocurre al subir archivos, no es parte del swarm):**

Azure AI Search indexa automáticamente los archivos subidos al Blob Storage:
- Document cracking nativo para PDF/DOCX/Excel
- Chunking automático por sección
- Embeddings generados vía AI Foundry
- Metadata indexada: `project_id`, `tenant_id`, `lang`, `file_type`, `chunk_index`
- Videos: Azure AI Speech transcribe primero, luego se indexa el texto

El índice es **compartido entre todos los proyectos** con aislamiento por filtros `project_id` + `tenant_id`. Migración a índices dedicados por tenant disponible en V2.

**Fase A — Análisis (corre automático una vez el índice está listo):**

| Worker | Función | Servicio Azure / Modelo | Depende de |
|---|---|---|---|
| `retriever` | Ejecuta N queries híbridas (keyword + vector) al índice — topK chunks por tema | **AI Search** — *sin LLM* | índice listo |
| `process_mapper` | Recibe grounding data del retriever y construye el mapa del proceso | **AI Foundry** / kimi-k2 | `retriever` |
| `question_generator` | Genera 3–8 preguntas de clarificación con base en el mapa | **AI Foundry** / kimi-k2 | `process_mapper` |

> `file_ingester` y `content_analyzer_N` eliminados — reemplazados por Azure AI Search. Reducción de LLM calls de N+2 a 2 en Fase A.

→ **Swarm pausa.** Estado: `waiting_questions`.  
→ Usuario responde las preguntas en el UI.  
→ Usuario confirma → API dispara Fase B.

**Fase B — Generación Excel (corre con respuestas):**

| Worker | Función | Servicio Azure / Modelo | Depende de |
|---|---|---|---|
| `step_designer` | Diseña el paso a paso usando el mapa del proceso + respuestas del usuario | **AI Foundry** / kimi-k2 | respuestas de Fase A |
| `excel_filler` | Genera JSON estructurado con todos los pasos (nunca toca el binario) | **AI Foundry** / kimi-k2 | `step_designer` |
| `excel_builder` | Aplica el JSON sobre `PlantillaProcedures.xlsx` con openpyxl — *sin LLM* | pure Python | `excel_filler` |
| `quality_checker` | Valida que el JSON/Excel esté completo y bien formado | **AI Foundry** / kimi-k2 | `excel_builder` |

**El LLM nunca toca el archivo Excel directamente.** Genera un JSON estructurado; `excel_builder` lo convierte a `.xlsx` de forma determinista. Mismo principio que el Editor Agent.

→ Excel generado → subido a Blob → disponible para revisión inline.

**Editor Agent (lightweight — no es swarm completo):**  
Cuando el usuario pide cambios textuales ("cambia el paso 3 por X"):

El LLM **nunca toca el archivo binario**. El flujo es:
1. `excel_reader.py` lee el blob actual con openpyxl y serializa las celdas relevantes a JSON plano
2. LLM recibe ese JSON + la instrucción del usuario; su única responsabilidad es devolver un **JSON de parche estricto**
3. `excel_patcher.py` (determinista, sin LLM) aplica el parche con openpyxl y sobreescribe el blob

```json
// Ejemplo de JSON de parche que devuelve el LLM
[
  {"action": "update", "sheet": "Proceso", "cell": "C4", "new_value": "Verificar presión a 80 PSI"},
  {"action": "update", "sheet": "Proceso", "cell": "D4", "new_value": "Responsable: Operador Senior"}
]
```

Pasar el binario/XML de Excel directamente a un LLM y pedir el archivo íntegro de vuelta corrompe el archivo con alta probabilidad. El LLM solo define *qué* cambiar; openpyxl decide *cómo* cambiarlo.

### 6.2 Swarm 2 — Training Generator

Corre solo después de que el usuario aprueba el Excel.

| Worker | Función | Servicio Azure / Modelo | Depende de |
|---|---|---|---|
| `content_structurer` | Divide el Excel en módulos y secciones | **AI Foundry** / kimi-k2 | — |
| `script_writer` | Escribe el texto narrativo de cada sección | **AI Foundry** / kimi-k2 | `content_structurer` |
| `quiz_creator` | Genera preguntas de evaluación + respuestas | **AI Foundry** / kimi-k2 | `content_structurer` |
| `visual_planner` | Decide visualizaciones (CSS/Lottie → Three.js) | **AI Foundry** / kimi-k2 | `content_structurer` |
| `component_generator` | Genera HTML/CSS/JS por sección | **AI Foundry** / kimi-k2 | `script_writer`, `visual_planner` |
| `quiz_integrator` | Integra quizzes en el HTML | **AI Foundry** / kimi-k2 | `quiz_creator`, `component_generator` |
| `assembler` | Ensambla la web final, crea ZIP | *sin LLM* — solo Python | todos |

→ ZIP subido a Blob → URL de preview generada → usuario descarga o publica.

**Nota importante sobre Three.js:** Generar Three.js directo con LLM tiene ~40% tasa de bugs visuales. 
- **MVP:** Solo CSS animations + Lottie. Funcional y confiable.  
- **V2 Premium:** Three.js con worker de QA headless (Playwright) que verifica el render antes de entregar.

---

## 7. Estrategia LLM

**MVP: un solo modelo, un solo provider — kimi-k2 vía Azure AI Foundry.**

Todo LLM call pasa por `azure-ai-inference` (`ChatCompletionsClient`) con credenciales Azure. El billing y la autenticación son centralizados en la suscripción Azure — no hay SDKs externos ni credenciales de terceros.

| Tarea | Modelo | Servicio |
|---|---|---|
| Todos los workers (Swarm 1 y 2) | kimi-k2 | Azure AI Foundry |
| Embeddings para AI Search | modelo embeddings AI Foundry | Azure AI Foundry |

Configuración por worker en el plan del swarm:

```python
workers = [
    {"name": "retriever",          "service": "azure_ai_search",   "model": None},
    {"name": "process_mapper",     "service": "azure_ai_foundry",  "model": "kimi-k2"},
    {"name": "question_generator", "service": "azure_ai_foundry",  "model": "kimi-k2"},
    {"name": "step_designer",      "service": "azure_ai_foundry",  "model": "kimi-k2"},
    {"name": "excel_filler",       "service": "azure_ai_foundry",  "model": "kimi-k2"},
    {"name": "excel_builder",      "service": None,                "model": None},
    {"name": "quality_checker",    "service": "azure_ai_foundry",  "model": "kimi-k2"},
]
```

> **Cambio de modelo futuro:** el adapter está diseñado para soportar múltiples modelos por worker. Si se necesita mezclar kimi-k2 con GPT-4o o Claude en V2, solo se cambia la config del worker — el engine del swarm no cambia.

---

### 7.2 Dimensión 2 — Credenciales por tenant (billing)

Todo pasa por Azure, por lo que "BYOK" aquí significa que el tenant usa su propia **suscripción Azure** en vez de la de Menthara. Tres variantes:

| Variante | Descripción | Cuándo usarla |
|---|---|---|
| **Shared pool** | Suscripción Azure de Menthara, recursos compartidos | Tier básico ($500) |
| **Dedicated** | Menthara provisiona recursos Azure separados para el tenant dentro de nuestra suscripción | Tier medio/alto, rate limits aislados |
| **BYOK Azure** | El tenant conecta su propia suscripción Azure — pagan directo a Microsoft | Tier enterprise, aislamiento total y control de costos |

La tabla de credenciales almacena endpoints y keys Azure (no hay "provider externo" — todo es Azure):

```sql
CREATE TABLE tenant_llm_credentials (
  id            SERIAL PRIMARY KEY,
  tenant_id     INT REFERENCES tenants(id),
  service       TEXT NOT NULL,     -- 'azure_openai' | 'azure_ai_foundry'
  api_key       TEXT NOT NULL,     -- encriptado con Azure Key Vault
  endpoint      TEXT NOT NULL,     -- endpoint de Azure para este servicio
  is_active     BOOLEAN DEFAULT TRUE,
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

Si el tenant no tiene credenciales propias → `llm_adapter.py` usa los endpoints de Menthara para ese servicio Azure.

---

### 7.3 `llm_adapter.py` — el router que une las dos dimensiones

Como todo pasa por Azure, el adapter solo necesita manejar dos clientes SDK — uno por servicio Azure:

```python
class LLMAdapter:
    async def chat(self, messages, *, service: str, model: str, tenant_id: str, **kwargs):
        credentials = await self._resolve_credentials(tenant_id, service)
        client = self._build_client(service, credentials)
        return await client.complete(messages, model=model, **kwargs)

    async def _resolve_credentials(self, tenant_id: str, service: str):
        # 1. ¿Tiene el tenant sus propios endpoints Azure para este servicio?
        creds = await db.get_tenant_credentials(tenant_id, service)
        if creds:
            return creds
        # 2. Fallback: endpoints de Menthara para ese servicio
        return MENTHARA_AZURE_ENDPOINTS[service]

    def _build_client(self, service: str, credentials):
        match service:
            case "azure_openai":
                # GPT-4o, GPT-4o-mini, o1, etc.
                return AzureOpenAI(
                    azure_endpoint=credentials.endpoint,
                    api_key=credentials.api_key,
                    api_version="2024-12-01-preview",
                )
            case "azure_ai_foundry":
                # Claude, Llama, Mistral, Phi, etc. — API unificada
                return ChatCompletionsClient(
                    endpoint=credentials.endpoint,
                    credential=AzureKeyCredential(credentials.api_key),
                )
```

Desde el SwarmManager, cada worker llama siempre a la misma interfaz — no sabe nada de credenciales ni de qué SDK usa internamente:

```python
response = await llm_adapter.chat(
    messages,
    service=worker.service,     # "azure_ai_foundry" o "azure_openai"
    model=worker.model,         # "claude-3-5-sonnet" o "gpt-4o"
    tenant_id=swarm.tenant_id,  # el adapter resuelve las creds
)
```

La ventaja de `azure-ai-inference` (AI Foundry) es que usa la misma interfaz para Claude, Llama, Mistral, etc. — un solo cliente para todos los modelos del catálogo de Azure.

---

### 7.4 Provisioning automático (Dedicated tier)

Para tenants que suben a Dedicated, Menthara provisiona dos recursos Azure automáticamente:

```python
async def provision_dedicated_resources(tenant_id: str):
    # 1. Azure OpenAI (GPT models)
    oai_resource = await azure_mgmt.cognitive_services.accounts.begin_create(
        resource_group=MENTHARA_RG,
        account_name=f"menthara-oai-{tenant_id[:8]}",
        parameters=CognitiveServicesAccountCreateParameters(
            sku=Sku(name="S0"), kind="OpenAI", location="eastus",
        )
    ).result()

    # 2. Azure AI Foundry project (Claude, Llama, Mistral, etc.)
    # Se crea via Azure AI Foundry SDK / Bicep — un endpoint dedicado por tenant

    await db.upsert_tenant_credentials(tenant_id,
        service="azure_openai",
        api_key=encrypt(oai_key),
        endpoint=oai_resource.properties.endpoint,
    )
    await db.upsert_tenant_credentials(tenant_id,
        service="azure_ai_foundry",
        api_key=encrypt(foundry_key),
        endpoint=foundry_endpoint,
    )
```

El tenant sigue en shared pool mientras se provisiona (1–5 min). Notificación por SignalR cuando esté listo.

---

### 7.5 Por qué por tenant y no por usuario

Azure tiene cuotas duras de recursos por suscripción/región. Con 200 empresas clientes, 200 recursos es manejable; con 10.000 usuarios individuales, no. Además, los swarms los dispara la empresa — no 50 usuarios de la misma empresa lanzando swarms simultáneos en general.

---

## 8. Azure OpenAI Rate Limiting

Un swarm con múltiples `content_analyzer_N` corriendo en paralelo puede golpear los límites de TPM/RPM de Azure OpenAI en segundos, especialmente con contextos largos (texto extraído de PDFs). Si un worker falla por `429 Too Many Requests`, la excepción se propaga, el task queda en error, y el swarm colapsa en cascada.

### Estrategia de defensa en `llm_adapter.py`

**1. Exponential backoff con jitter (obligatorio)**  
Ante cualquier `429` o `503`, el adapter reintenta con backoff creciente + jitter aleatorio para evitar que todos los workers sincronicen sus reintentos:

```python
async def chat_with_backoff(self, messages, **kwargs):
    max_retries = 6
    base_delay = 1.0
    for attempt in range(max_retries):
        try:
            return await self._client.chat.completions.create(messages=messages, **kwargs)
        except openai.RateLimitError:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(min(delay, 60))
```

**2. Semáforo por swarm (concurrencia máxima)**  
Cada swarm tiene un semáforo que limita cuántos workers pueden llamar al LLM simultáneamente. Evita que un swarm grande monopolice la cuota:

```python
# En SwarmManager: un semáforo por swarm, configurable
self._llm_semaphores[swarm_id] = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

# En cada worker antes de llamar al LLM:
async with self.swarm_manager._llm_semaphores[swarm_id]:
    response = await llm_adapter.chat_with_backoff(messages)
```

**3. Global rate limiter (token bucket)**  
Si hay 100 swarms corriendo en paralelo, el semáforo por swarm no es suficiente — el límite es global de Azure. Se implementa un token bucket compartido en Redis (o en memoria si hay un solo worker pod):

```python
# Máximo X requests por minuto globalmente, compartido entre todos los Jobs
global_limiter = AsyncLimiter(max_rate=RPM_LIMIT, time_period=60)
async with global_limiter:
    response = await llm_adapter.chat(messages)
```

**4. Logs y alertas**  
Cada `429` se emite como evento `swarm:llm_throttled` hacia SignalR (visible en el dashboard) y como métrica en Azure Application Insights para detectar si hay que subir el tier de OpenAI.

**Valores de configuración (ajustables por env var):**
```
AZURE_OAI_MAX_CONCURRENT_PER_SWARM=3
AZURE_OAI_GLOBAL_RPM_LIMIT=60
AZURE_OAI_MAX_RETRY_ATTEMPTS=6
```

---

## 9. Idempotencia y Recuperación de Estado

Esta es la parte más crítica del diseño. Un Container Apps Job puede morir en cualquier momento: OOM, fallo de infraestructura Azure, scaling event. Lo que ocurre con el swarm en ese momento define la confiabilidad de toda la plataforma.

### Principio base: PostgreSQL es la única fuente de verdad

El estado en memoria del Job (los `asyncio.Task` activos, el dict `_running`, los semáforos) es **efímero y descartable**. El estado en PostgreSQL es permanente. Todo lo que importa debe estar en DB antes de que el Job muera.

**Invariante que se debe mantener:**  
> Un task solo se marca `completed` en la DB **después** de que su output esté guardado en Blob Storage. Ambas escrituras ocurren en una sola transacción PostgreSQL.

```python
async with db.transaction():
    await blob_storage.upload(f"swarms/{swarm_id}/workers/{name}/output.json", result)
    await db.update_task(task_id, status="completed", result_blob_url=url)
```

Si el Job muere entre el upload a Blob y el update en DB, el task queda `running` en DB → se resetea → se re-ejecuta → sobreescribe el mismo blob (idempotente por nombre determinista). No hay pérdida de datos.

### Heartbeat de workers

La tabla `swarm_workers` agrega una columna `last_heartbeat TIMESTAMPTZ`. Cada worker actualiza este campo cada 30 segundos mientras trabaja. Si el Job muere, el heartbeat deja de actualizarse.

```sql
ALTER TABLE swarm_workers ADD COLUMN last_heartbeat TIMESTAMPTZ;
```

### Watchdog en la API (Resurrection Watcher)

Un background task en el API Container App (equivalente al `ResurrectionWatcher` de OpenACM) revisa periódicamente:

```python
async def swarm_watchdog():
    while True:
        await asyncio.sleep(120)  # cada 2 minutos
        stale_threshold = datetime.now(UTC) - timedelta(minutes=5)
        
        # Swarms marcados como running pero sin heartbeat reciente
        stale_swarms = await db.query("""
            SELECT DISTINCT s.id FROM swarms s
            JOIN swarm_workers w ON w.swarm_id = s.id
            WHERE s.status = 'running'
              AND w.status = 'running'
              AND w.last_heartbeat < $1
        """, stale_threshold)
        
        for swarm in stale_swarms:
            async with db.advisory_lock(swarm.id):  # lock para evitar doble-encolado
                # Re-verificar dentro del lock
                current = await db.get_swarm(swarm.id)
                if current.status == 'running' and is_stale(current):
                    await queue.enqueue_swarm_job(swarm.id)
                    log.warning("swarm_resurrected", swarm_id=swarm.id)
```

### Flujo completo de recuperación

```
T+0:00   Swarm corriendo, 3/7 tasks completadas, Job muere abruptamente
T+0:00   last_heartbeat deja de actualizarse en DB
T+2:00   Watchdog detecta: swarm_{id} running + heartbeat stale > 5min
T+2:00   Watchdog adquiere advisory lock en PostgreSQL sobre swarm_{id}
T+2:00   Re-verifica estado dentro del lock → confirma que es stale
T+2:00   Re-encola el job en Azure Queue Storage
T+2:00   Libera lock
T+2:30   Nuevo Container Apps Job se inicia con el mismo swarm_id
T+2:30   Job llama _reset_orphaned_tasks():
           - Tasks en estado 'running' → reset a 'pending'
           - Tasks en estado 'completed' → no se tocan
T+2:30   Swarm retoma: 4/7 tasks pendientes, continúa sin repetir trabajo
```

### Frontend — reconexión y reconciliación de estado

El WebSocket es **suplementario**, no la fuente de verdad. Si el usuario vuelve al browser después de que el Job murió y se reinició, el frontend no puede reconstruir el estado desde eventos pasados (el WebSocket no tiene historial).

**Solución:** Al cargar o al reconectar el WebSocket, el frontend siempre hace un `GET /api/swarms/{id}` para obtener el estado completo desde PostgreSQL. El WebSocket solo entrega actualizaciones incrementales en tiempo real después de esa carga inicial.

```typescript
// Al montar el componente o al reconectar el WebSocket
const initialState = await fetch(`/api/swarms/${swarmId}`).then(r => r.json())
setSwarmState(initialState)

// Luego, eventos WebSocket solo aplican deltas sobre ese estado base
ws.onmessage = (event) => {
  const payload = JSON.parse(event.data)
  setSwarmState(prev => applyTaskUpdate(prev, payload))
}
```

### Idempotencia de Blobs y Queue

- **Nombres de Blob deterministas:** `swarms/{swarm_id}/workers/{worker_name}/output.json` — siempre el mismo path. Re-ejecutar un worker sobreescribe el blob anterior sin crear duplicados.
- **Deduplicación de encolado:** Antes de encolar, el Watchdog verifica con `SELECT FOR UPDATE` que no haya ya un job activo. Azure Queue Storage no tiene deduplicación nativa (eso es Service Bus), así que el lock de DB es la garantía.

### Tabla de garantías

| Escenario | Consecuencia | Mecanismo |
|---|---|---|
| Job muere entre LLM call y escritura en DB | Task se resetea a `pending` y se re-ejecuta | `_reset_orphaned_tasks()` |
| Job muere después de escribir en Blob pero antes de commit en DB | Se re-ejecuta, blob se sobreescribe (idempotente) | Nombres deterministas |
| Job muere después de commit en DB | Task queda `completed`, no se re-ejecuta | Estado persistente |
| Watchdog encola dos veces por race condition | Solo un Job corre (advisory lock en PostgreSQL) | `SELECT FOR UPDATE` |
| Usuario reconecta con browser tras fallo | Ve estado real, no estado stale | GET REST al cargar |

---

## 10. Real-time — FastAPI WebSocket + PostgreSQL NOTIFY

Reemplaza el EventBus + WebSocket de OpenACM. No usa Azure SignalR (ver §3.2 para la comparativa de opciones).

```
SwarmManager Job
  → pg_notify('swarm_events', json_payload)

API Container App (asyncpg listener en background)
  → recibe el NOTIFY
  → lookup ws_connections[swarm_id]
  → send_json a cada WebSocket conectado

Browser (React + Vite)
  → WebSocket nativo del browser
  → conecta a /ws/swarms/{swarm_id}
  → recibe eventos del swarm en tiempo real
```

**Eventos emitidos (mismos de OpenACM + específicos de Menthara):**
```
swarm:worker_status, swarm:task_updated, swarm:message,
swarm:questions_ready,   ← fase A terminó, el user debe responder preguntas
swarm:excel_ready,       ← Excel generado, listo para revisar
swarm:excel_updated,     ← Editor Agent aplicó cambios al Excel
swarm:training_ready,    ← capacitación generada, lista para publicar
swarm:completed, swarm:error, swarm:llm_throttled
```

---

## 11. Auth — Integración con sistema externo  

El sistema externo maneja login, licencias y usuarios. Menthara valida los tokens de ese sistema.

**Estrategia:** El sistema externo emite JWTs firmados. Menthara valida la firma con la clave pública del sistema externo.

**Lo que necesitamos del sistema externo:**
- Endpoint o clave pública para validar tokens
- Claims en el JWT: `user_id`, `tenant_id`, `plan`, `max_users`
- (Opcional) Webhook para cuando una licencia expira

**Middleware en FastAPI:**
```python
async def auth_middleware(request, call_next):
    token = request.headers.get("Authorization").split(" ")[1]
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    request.state.user_id = payload["user_id"]
    request.state.tenant_id = payload["tenant_id"]
    return await call_next(request)
```

---

## 12. Flujo de Reanudación — El usuario puede cerrar el browser

Un swarm puede tardar 20–30 minutos. El usuario no debe quedarse mirando una pantalla. Puede cerrar el browser, ir a tomar café, volver, y continuar exactamente donde lo dejó.

### Cómo funciona

El estado de cada proyecto vive en PostgreSQL (`projects.status`). El frontend **nunca asume** — siempre pregunta al backend al cargar. El backend siempre sabe la verdad.

**State machine de `project.status`:**

```
draft
  ↓  (sube archivos y describe el proceso)
analyzing          ← Swarm 1 Fase A corriendo
  ↓
waiting_questions  ← preguntas listas, esperando al usuario
  ↓  (usuario responde y confirma)
generating_excel   ← Swarm 1 Fase B corriendo
  ↓
review             ← Excel listo, esperando revisión del usuario
  ↓  (usuario aprueba)
generating_training ← Swarm 2 corriendo
  ↓
completed          ← capacitación lista
```

Estados de error: `failed` (con `error_message` para mostrar al usuario).

### El componente central: `ProjectDetail`

Cuando el usuario abre `/projects/{id}` (ya sea porque volvió al browser, pegó el link, o acabó de disparar un paso):

```jsx
// pages/MentharaGeneration/MentharaGeneration.jsx
export function MentharaGeneration() {
  const { projectId } = useParams()
  const dispatch = useDispatch()
  const project = useSelector(state => state.mentharaGeneration.project)
  const loading = useSelector(state => state.mentharaGeneration.loading)

  useEffect(() => {
    dispatch(fetchProject(projectId))  // carga estado desde REST al montar
  }, [projectId])

  if (loading) return <LoadingModal open />

  // La vista se determina 100% por project.status — sin estado local
  switch (project?.status) {
    case 'draft':                return <UploadView project={project} />
    case 'analyzing':
    case 'generating_excel':
    case 'generating_training':  return <ProgressView project={project} />
    case 'waiting_questions':    return <QuestionsView project={project} />
    case 'review':               return <ReviewView project={project} />   // usa Table.jsx existente
    case 'completed':            return <TrainingPreviewView project={project} /> // usa Tablet.jsx existente
    case 'failed':               return <AlertModal message={project.error_message} />
    default:                     return null
  }
}
```

Ese `switch` sobre `project.status` es toda la lógica de reanudación. Si el usuario vuelve cuando el swarm terminó, ve directamente el Excel para revisar. Si vuelve mientras sigue corriendo, ve el progreso en tiempo real.

### El hook `useProjectWS` — WebSocket con reconexión

El WebSocket es solo para actualizaciones en tiempo real mientras el usuario está en la pantalla. Si se desconecta, el proceso sigue en Azure. Cuando vuelve, el `useQuery` inicial ya trae el estado actual.

```js
// helpers/hooks/useMentharaWS.js
export function useMentharaWS(projectId, onEvent) {
  const dispatch = useDispatch()

  useEffect(() => {
    let ws
    let retryDelay = 1000

    function connect() {
      ws = new WebSocket(`${process.env.REACT_APP_MENTHARA_WS}/ws/projects/${projectId}`)

      ws.onmessage = (msg) => {
        const event = JSON.parse(msg.data)
        onEvent(event)

        // Si el status del proyecto cambió, recargar el estado completo desde REST
        if (event.type === 'project:status_changed') {
          dispatch(fetchProject(projectId))
        }
      }

      ws.onclose = () => {
        setTimeout(connect, Math.min(retryDelay, 30_000))
        retryDelay *= 2
      }

      ws.onopen = () => { retryDelay = 1000 }
    }

    connect()
    return () => ws?.close()
  }, [projectId])
}
```

**Lo que ocurre cuando el usuario vuelve tras estar desconectado:**
1. `useQuery` carga el proyecto desde REST → estado actual real desde PostgreSQL
2. Si el status cambió (ej: `analyzing` → `waiting_questions`), el `switch` renderiza la nueva vista automáticamente
3. `useProjectWS` conecta el WebSocket → a partir de ese momento recibe deltas en tiempo real
4. No hay "sincronización de eventos perdidos" — el estado base siempre viene de REST, los eventos WS solo aplican deltas a partir de la reconexión

### Notificación cuando termina (mientras el usuario está fuera)

Para que el usuario sepa que terminó sin tener que volver a la pestaña:

- **Tab activo en background:** El WS reconnect con backoff lo detecta solo
- **Tab cerrado:** El backend puede enviar un **email** cuando `project.status` cambia a `waiting_questions`, `review`, o `completed`  
  - Implementación simple: disparar email desde el API cuando el Job emite `project:status_changed`
  - Sin costo adicional: Azure Communication Services tiene tier gratuito (2000 emails/mes)

---

## 13. Multi-idioma

**Librería:** `react-i18next` + `i18next`  
**Detección de idioma:** `i18next-browser-languagedetector` (detecta del browser, override manual)

Los prompts del LLM incluyen el idioma del usuario:
```python
f"Respond in {user.language}. Generate questions about the process..."
```

**Idiomas en MVP:** Español + Inglés  
**Agregar idiomas después:** Solo agregar archivos `public/locales/{lang}/translation.json`, sin cambios en el código.

---

## 14. Roadmap por Fases

### Fase 0 — Setup (1 semana)
- [ ] Crear repositorio `menthara-platform`
- [ ] Provisionar Azure: PostgreSQL, Blob Storage, Container Registry
- [ ] Escribir Bicep para toda la infra (reproducible)
- [ ] Setup CI/CD básico (GitHub Actions)
- [ ] Definir schema PostgreSQL inicial con Alembic

### Fase 1 — Motor de Swarms en Azure (2–3 semanas)
- [ ] Extraer `SwarmManager` de OpenACM y adaptar interfaces
- [ ] Implementar adapter `azure_openai.py` con exponential backoff + semáforo por swarm + global token bucket
- [ ] Implementar adapter `postgres.py` con soporte de advisory locks y transacciones para idempotencia
- [ ] Implementar adapter `azure_storage.py` con nombres de blob deterministas
- [ ] Implementar adapter `azure_signalr.py` (reemplaza EventBus)
- [ ] Agregar `last_heartbeat` a `swarm_workers` + lógica de heartbeat en workers
- [ ] Implementar Watchdog de swarms muertos en el API (basado en ResurrectionWatcher de OpenACM)
- [ ] Dockerizar el worker + Container App Job funcionando
- [ ] Test: un swarm simple corre en Azure, emite eventos reales, y se recupera correctamente si el Job es terminado a la fuerza

### Fase 2 — Swarm 1 completo (2–3 semanas)
- [ ] Tool: `document_intel.py` (PDF/DOCX → texto estructurado)
- [ ] Tool: `speech.py` (video → transcripción)
- [ ] Tool: `excel_filler.py` (template fijo → openpyxl)
- [ ] Workers: `file_ingester`, `content_analyzer`, `process_mapper`, `question_generator`
- [ ] Lógica de pausa/resume (Fase A → preguntas → Fase B)
- [ ] Workers: `step_designer`, `excel_filler`, `quality_checker`
- [ ] API endpoints: upload files, start swarm, submit answers, get excel

### Fase 3 — Frontend en MentharaFront (1–2 semanas, paralelo a Fase 2)

El frontend ya existe — no hay setup. Solo se agregan las páginas nuevas de Menthara al proyecto existente.

**Nuevas rutas y páginas:**
- [ ] `MentharaProjects.jsx` — lista de proyectos de generación + botón "Nuevo proyecto"
- [ ] `MentharaGeneration.jsx` — state machine sobre `project.status` (ver §12)
- [ ] `UploadView` — formulario de descripción del proceso + react-dropzone para archivos
- [ ] `ProgressView` — progreso del swarm en tiempo real (hook `useMentharaWS.js`)
- [ ] `QuestionsView` — formulario con las preguntas generadas por el swarm
- [ ] `ReviewView` — **reutiliza `Table.jsx` existente** + botón "Aprobar" + Editor Agent input
- [ ] `TrainingPreviewView` — **reutiliza `Tablet.jsx` existente** para previsualizar la capacitación

**Infraestructura nueva en el frontend:**
- [ ] `useMentharaWS.js` — hook WebSocket con exponential backoff y reconciliación desde REST
- [ ] `mentharaGenerationReducer.js` — estado del swarm/project en Redux
- [ ] `mentharaGeneration.js` (Actions) — llamadas a la API de Menthara
- [ ] Agregar rutas en `App.js`: `/menthara/*` y `/menthara/:projectId/*`
- [ ] (Opcional MVP) agregar `react-i18next` al proyecto existente

### Fase 4 — Swarm 2 (3–4 semanas)
- [ ] Definir el formato exacto del output del Swarm 2 (piezas HTML para `Tablet.jsx`)
- [ ] Workers: `content_structurer`, `script_writer`, `quiz_creator`
- [ ] Workers: `visual_planner` (CSS/Lottie only para MVP)
- [ ] Workers: `component_generator`, `quiz_integrator`, `assembler`
- [ ] Output: JSON/HTML de piezas de contenido → compatible con el formato que espera `Tablet.jsx`
- [ ] `TrainingPreviewView` carga el output del swarm en `Tablet.jsx` existente

### Fase 5 — Hardening y lanzamiento (1–2 semanas)
- [ ] Load testing: 50+ swarms concurrentes en Azure
- [ ] Monitoreo: Azure Application Insights
- [ ] Límites por tenant (max files, max swarms simultáneos)
- [ ] Three.js premium (opcional, post-MVP)
- [ ] Documentación de integración con el sistema externo

---

## 15. Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| SwarmManager acoplado a Brain/LLMRouter de OpenACM | Alto | Definir interfaces abstractas primero; adaptar sin tocar core logic |
| Three.js genera bugs visuales (~40%) | Medio | MVP solo CSS+Lottie; Three.js en V2 con QA headless |
| Videos muy grandes (>1GB) — transcripción lenta | Medio | Azure AI Speech maneja chunking; informar al usuario el tiempo estimado |
| Costo Azure OpenAI escala con uso | Alto | Presupuesto por tenant en DB; alertas de Azure Cost Management |
| Auth con sistema externo — cambios de token format | Bajo | Usar clave pública configurable por env var; no hardcodear formato |
| Excel template cambia en el sistema destino | Bajo | Mantener template en Blob Storage (configurable), no en código |
| Rate limits de Azure OpenAI con workers en paralelo | **Alto** | Semáforo por swarm + exponential backoff con jitter + global token bucket; ver §7 |
| Job de Container App muere a mitad del swarm | **Alto** | Heartbeat en DB + Watchdog en API + `_reset_orphaned_tasks()` al arrancar; ver §8 |
| Handsontable — licencia comercial no-libre | Alto | **Resuelto:** usar AG-Grid Community (Apache 2.0) exclusivamente |
| Editor Agent corrompe el Excel (pasa binario al LLM) | Alto | **Resuelto:** LLM solo devuelve JSON de parche; openpyxl aplica cambios; ver §6.1 |

---

## 16. Preguntas Pendientes (para responder antes de Fase 2)

1. **Auth tokens:** ¿Qué formato/claims tienen los JWT del sistema externo? ¿RS256 o HS256?
2. **Excel template:** ✅ Resuelto — `PlantillaProcedures.xlsx` en `https://xdprocedures.blob.core.windows.net/files/PlantillaProcedures.xlsx`. Endpoint de carga: `POST /bulkLoad/{procedureId}`.
3. **Sistema destino:** ✅ Parcialmente resuelto — el Excel se sube vía `POST /bulkLoad/{procedureId}`. ¿El output del Swarm 2 (training web) también se carga automáticamente al sistema, o solo se previsualiza en `Tablet.jsx`?
4. **Límites de archivos:** ¿Cuál es el tamaño máximo que quieren soportar por proyecto? (define el tier de Blob y de Speech)
5. **Idiomas adicionales:** ¿Además de ES/EN hay algún otro idioma prioritario?
6. **Dominio:** ¿Ya tienen dominio para Menthara? (afecta configuración de Static Web Apps y SignalR CORS)

---

## 17. Stack Tecnológico Resumido

| Capa | Tecnología |
|---|---|
| **Backend** | Python 3.12 + FastAPI + asyncpg |
| **Swarm Engine** | OpenACM SwarmManager (migrado) |
| **LLM** | Azure OpenAI Service (GPT-4o, gpt-4o-mini) + Azure AI Foundry (Claude, Llama, Mistral, Phi) |
| **Database** | Azure PostgreSQL Flexible Server + Alembic |
| **File Storage** | Azure Blob Storage |
| **Real-time** | Azure SignalR Service |
| **Document parsing** | Azure Document Intelligence |
| **Audio/Video** | Azure AI Speech |
| **Excel generation** | openpyxl |
| **Job execution** | Azure Container Apps Jobs |
| **API runtime** | Azure Container Apps |
| **Frontend** | React 18 + CRA + JavaScript + Material-UI v6 + Redux (MentharaFront — ya existe) |
| **Spreadsheet editor** | `Table.jsx` existente en MentharaFront (Material React Table) — ya implementado |
| **Training viewer** | `Tablet.jsx` existente en MentharaFront — ya implementado |
| **i18n** | react-i18next (a agregar al proyecto existente) |
| **CSS/Animations** | MUI + Lottie (MVP); Three.js (V2) |
| **Auth** | JWT validation (clave pública sistema externo) |
| **Infra as Code** | Azure Bicep |
| **CI/CD** | GitHub Actions |
| **Monitoring** | Azure Application Insights |
