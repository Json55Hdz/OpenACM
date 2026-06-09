# Menthara — Diagrama de Arquitectura Completo

> Generado: 2026-05-05 | Basado en MENTHARA_PLAN.md v1

---

## 1. Flujo Principal — Journey del Usuario

```mermaid
flowchart TD
    START([👤 Usuario]) --> UV

    subgraph UV ["① Upload + Indexación automática"]
        UV1[Describe el proceso]
        UV2[Sube archivos\nPDF · DOCX · Excel · Video]
        UV3["⚡ Azure AI Search Indexer\nauto-chunking + embeddings\nfiltros: project_id · tenant_id · lang"]
        UV1 --- UV2
        UV2 -->|"dispara al subir"| UV3
    end

    UV --> S1A

    subgraph S1A ["② Swarm 1 — Fase A: Análisis (automático)"]
        direction LR
        RTV["🔍 retriever\nqueries híbridas al índice\nsin LLM — topK chunks"]
        PM["🗺️ process_mapper\nkimi-k2 + grounding data"]
        QG["❓ question_generator\nkimi-k2 + grounding data"]
        RTV --> PM --> QG
    end

    S1A -->|"⏸️ PAUSA — preguntas listas"| QV

    subgraph QV ["③ Preguntas de Clarificación"]
        QV1[Lee las preguntas generadas]
        QV2[Responde y confirma]
        QV1 --> QV2
    end

    QV --> S1B

    subgraph S1B ["④ Swarm 1 — Fase B: Excel (automático)"]
        direction LR
        SD["🎨 step_designer\nkimi-k2"]
        EF["📋 excel_filler\nkimi-k2 → JSON estructurado"]
        EB["📊 excel_builder\nopenpyxl — sin LLM\nJSON → PlantillaProcedures.xlsx"]
        QC["✅ quality_checker\nkimi-k2"]
        SD --> EF --> EB --> QC
    end

    S1B -->|"⏸️ PAUSA — Excel listo"| RV

    subgraph RV ["⑤ Revisión del Excel"]
        direction TB
        RV1["Revisa pasos en Table.jsx"]
        CHK{"¿Necesita cambios?"}
        RV1 --> CHK
        CHK -->|"escribe: cambia X por Y"| EA
        subgraph EA ["🤖 Editor Agent"]
            EA1["excel_reader → JSON"]
            EA2["kimi-k2 devuelve patch"]
            EA3["excel_patcher aplica"]
            EA1 --> EA2 --> EA3
        end
        EA --> RV1
        CHK -->|"✅ Aprueba"| RV2([Excel aprobado])
    end

    RV --> S2

    subgraph S2 ["⑥ Swarm 2 — Training Generator (automático)"]
        direction TB
        CS["📐 content_structurer\nkimi-k2"]
        subgraph PAR [" en paralelo "]
            direction LR
            SW["✍️ script_writer\nkimi-k2"]
            QC2["🧪 quiz_creator\nkimi-k2"]
            VP["🎨 visual_planner\nkimi-k2"]
        end
        CG["🖥️ component_generator\nkimi-k2"]
        QI["🔗 quiz_integrator\nkimi-k2"]
        ASM["📦 assembler → ZIP\npure Python"]
        CS --> PAR
        SW --> CG
        VP --> CG
        QC2 --> QI
        CG --> QI
        QI --> ASM
    end

    S2 -->|"⏸️ PAUSA — training listo"| TV

    subgraph TV ["⑦ Preview y Publicación"]
        TV1["Previsualiza en Tablet.jsx"]
        TV2["🌐 Publica al sistema externo\nPOST /bulkLoad/:procedureId"]
        TV1 --> TV2
    end

    TV --> DONE(["🎉 Capacitación publicada"])
```

---

## 2. Estado del Proyecto (State Machine)

```mermaid
stateDiagram-v2
    [*] --> draft : usuario crea proyecto

    draft --> analyzing         : sube archivos y describe proceso
    analyzing --> waiting_questions : Swarm 1 Fase A termina
    waiting_questions --> generating_excel : usuario responde preguntas
    generating_excel --> review  : Swarm 1 Fase B termina\nExcel listo
    review --> review            : Editor Agent aplica cambios
    review --> generating_training : usuario aprueba Excel
    generating_training --> completed : Swarm 2 termina\ntraining listo
    completed --> [*]

    analyzing --> failed         : error en swarm
    generating_excel --> failed  : error en swarm
    generating_training --> failed : error en swarm
    failed --> analyzing         : usuario reintenta
```

---

## 3. Infraestructura Azure

```mermaid
graph LR
    subgraph FRONT [Frontend]
        SWA[Azure Static Web Apps\nReact + MUI + Redux]
    end

    subgraph API_LAYER [API Layer]
        ACA[Azure Container App\nFastAPI — API]
        WD[Watchdog\nResurrection Watcher]
        PGL[asyncpg Listener\npg_notify → WebSocket]
        ACA --- WD
        ACA --- PGL
    end

    subgraph JOBS [Swarm Workers]
        JOB_S1A[Container Apps Job\nSwarm 1 — Fase A]
        JOB_S1B[Container Apps Job\nSwarm 1 — Fase B]
        JOB_S2[Container Apps Job\nSwarm 2]
    end

    subgraph AZURE_SVCS [Azure Services]
        AIF[Azure AI Foundry\nkimi-k2 — Model Catalog\n+ modelo de embeddings]
        AIS[Azure AI Search\níndice híbrido compartido\nfiltros: project_id + tenant_id]
        SPE[Azure AI Speech\nvideo → transcripción]
    end

    subgraph STORAGE [Persistencia]
        PG[(PostgreSQL\nestado + pg_notify)]
        BLOB[(Blob Storage\narchivos + Excel + ZIP)]
        QUEUE[(Queue Storage\njob triggers)]
        ACR[Container Registry\nimágenes Docker]
    end

    SWA <-->|REST + WebSocket| ACA
    ACA -->|encola jobs| QUEUE
    ACA -->|indexa al subir| AIS
    ACA -->|video| SPE
    SPE -->|transcripción| AIS
    QUEUE --> JOB_S1A & JOB_S1B & JOB_S2
    ACA <-->| | PG
    JOB_S1A & JOB_S1B & JOB_S2 <-->| | PG
    JOB_S1A & JOB_S1B & JOB_S2 <-->| | BLOB
    JOB_S1A -->|queries híbridas| AIS
    JOB_S1B & JOB_S2 -->|LLM calls| AIF
    JOB_S1A -->|LLM calls| AIF
    ACR -.->|imágenes| ACA & JOB_S1A & JOB_S1B & JOB_S2
```

---

## 4. Real-time (PG NOTIFY → WebSocket)

```mermaid
sequenceDiagram
    participant JOB as Container Apps Job
    participant PG as PostgreSQL
    participant API as FastAPI (asyncpg listener)
    participant WS as WebSocket (browser)

    JOB->>PG: pg_notify('swarm_events', {swarm_id, type, data})
    PG-->>API: NOTIFY broadcast
    API->>API: lookup ws_connections[swarm_id]
    API-->>WS: send_json(event)
    WS-->>WS: dispatch Redux action\nactualiza UI en tiempo real
```

---

## 5. Swarm 1 — Detalle de Workers

```mermaid
gantt
    title Swarm 1 — Ejecución en el tiempo
    dateFormat X
    axisFormat %s

    section Pre-swarm (al subir archivos)
    AI Search indexer — auto chunking + embeddings   :done, pre1, 0, 15

    section Fase A (swarm arranca)
    retriever — queries híbridas al índice (sin LLM) :a1, after pre1, 5
    process_mapper — kimi-k2 + grounding data        :a2, after a1, 15
    question_generator — kimi-k2 + grounding data    :a3, after a2, 10

    section Pausa — usuario responde
    waiting_questions                                :crit, a4, after a3, 60

    section Fase B
    step_designer                                    :b1, after a4, 20
    excel_filler — JSON estructurado                 :b2, after b1, 15
    excel_builder — openpyxl sin LLM                 :b3, after b2, 5
    quality_checker                                  :b4, after b3, 10
```

---

## 6. Swarm 2 — Detalle de Workers

```mermaid
gantt
    title Swarm 2 — Ejecución en el tiempo
    dateFormat X
    axisFormat %s

    section Estructuración
    content_structurer    :s1, 0, 15

    section Generación paralela
    script_writer         :s2, after s1, 25
    quiz_creator          :s3, after s1, 20
    visual_planner        :s4, after s1, 20

    section Componentes
    component_generator   :s5, after s2, 30

    section Integración
    quiz_integrator       :s6, after s3, 15

    section Ensamblado
    assembler             :s7, after s5, 10
```

---

## 7. Pipeline de Indexación (Azure AI Search)

> Ocurre al momento de subir archivos — **antes** de que arranque el swarm. Índice compartido con filtros `project_id` + `tenant_id` para aislamiento multi-tenant.

```mermaid
sequenceDiagram
    participant USR as Usuario
    participant API as FastAPI API
    participant BLOB as Blob Storage
    participant SPE as AI Speech
    participant AIS as Azure AI Search
    participant EMB as Embeddings (AI Foundry)

    USR->>API: POST /projects/:id/files (PDF/DOCX/Excel/Video)
    API->>BLOB: guarda archivo original

    alt PDF · DOCX · Excel
        API->>AIS: trigger indexer (blob URL)
        AIS->>AIS: document cracking nativo
        AIS->>AIS: chunking automático por sección
        AIS->>EMB: genera embedding por chunk
        AIS->>AIS: indexa con metadata\nproject_id · tenant_id · lang · file_type · chunk_index
    else Video
        API->>SPE: transcripción async
        SPE-->>API: texto transcrito
        API->>AIS: indexa transcripción como chunks
        AIS->>EMB: genera embeddings
        AIS->>AIS: indexa con metadata
    end

    API-->>USR: 200 OK — archivo indexado y listo
    Note over AIS: índice listo para queries\ncuando arranque el swarm
```

---

## 8. LLM Adapter — Resolución de credenciales

> Kimi K2 se consume desde **Azure AI Foundry** (Model Catalog). El SDK es `azure-ai-inference` con `ChatCompletionsClient` — misma interfaz para todos los workers, credenciales y billing centralizados en Azure.

```mermaid
flowchart LR
    W[Worker\nmodel + tenant_id]
    W --> LA[LLMAdapter.chat]

    LA --> CR{¿tiene el tenant\ncredenciales Azure propias\npara AI Foundry?}
    CR -->|sí| TC[tenant_llm_credentials\nen PostgreSQL\nendpoint + key Azure]
    CR -->|no| MC[AZURE_AI_FOUNDRY_ENDPOINT\n+ AZURE_AI_FOUNDRY_KEY\nenv vars de Menthara]

    TC --> BC[build_client]
    MC --> BC

    BC --> KIMI["azure-ai-inference\nChatCompletionsClient\nendpoint: Azure AI Foundry\nmodel: kimi-k2\n\n✅ billing en suscripción Azure\n✅ misma interfaz para todos los workers"]
```

---

## 8. Idempotencia y Recuperación (Watchdog)

```mermaid
sequenceDiagram
    participant JOB as Container Apps Job
    participant PG as PostgreSQL
    participant WD as Watchdog (API)
    participant Q as Azure Queue

    JOB->>PG: heartbeat cada 30s
    Note over JOB: Job muere abruptamente

    loop cada 2 min
        WD->>PG: SELECT swarms con heartbeat > 5min stale
        PG-->>WD: [swarm_id_X]
        WD->>PG: advisory_lock(swarm_id_X)
        WD->>PG: re-verifica estado dentro del lock
        WD->>Q: encola re-ejecución
        WD->>PG: libera lock
    end

    Q-->>JOB: nuevo Container Apps Job
    JOB->>PG: _reset_orphaned_tasks()\ntasks 'running' → 'pending'
    Note over JOB: retoma desde tasks pendientes\nno repite las completadas
```
