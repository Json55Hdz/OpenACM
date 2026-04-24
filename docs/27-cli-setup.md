# CLI Setup Wizard

OpenACM incluye un wizard de configuración completamente funcional desde consola, ideal para servidores Linux headless, VPS, o cualquier entorno sin GUI.

---

## Lanzar el wizard

```bash
# Menú principal (acceso directo a cualquier sección)
openacm-setup

# Configuración guiada paso a paso (recomendado para primera vez)
openacm-setup --guided
openacm-setup -g

# Alternativa directa sin instalar
python -m openacm.cli.setup_wizard
python -m openacm.cli.setup_wizard --guided
```

---

## Modos de operación

### Menú principal

Muestra el estado actual de todas las secciones (✓/✗) y permite saltar a cualquiera directamente.

```
┌─────────────────────────────────────────────────┐
│  OpenACM Setup Wizard                           │
│  Configura tu agente sin necesitar el navegador │
└─────────────────────────────────────────────────┘

  ✓  Proveedores LLM         3 built-in + 1 custom
  ✓  Modelo por defecto      opencode_go
  ✗  Canales                 —
  ✓  Perfil de usuario       Cortana
  ✗  Google Services         —
  ✓  Local Router            habilitado
  ...

  [G]  Configuración guiada (paso a paso)

  [ 1]  Proveedores LLM  (API keys)
  [ 2]  Modelo por defecto + parámetros
  ...
  [0]  Salir
```

### Configuración guiada (`--guided`)

Recorre todas las secciones en orden lógico. En cada paso puedes:

| Tecla | Acción |
|-------|--------|
| `Enter` / `N` | Siguiente sección |
| `P` | Sección anterior |
| `M` | Volver al menú principal |

---

## Secciones

### 1 · Proveedores LLM

Configura las API keys de los proveedores de IA. Se guardan en `config/.env`.

| Proveedor | Variable |
|-----------|----------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |
| xAI (Grok) | `XAI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| OpenCode.GO | `OPENCODE_GO_API_KEY` |
| Ollama | *(no requiere key — local)* |

**Controles:** Enter = mantener actual · `x` = borrar

---

### 2 · Modelo por defecto + parámetros

Selecciona el proveedor y modelo que OpenACM usará por defecto, y opcionalmente ajusta:

- **Temperature** (0.0–2.0) — creatividad vs. determinismo
- **Max tokens** — límite de respuesta
- **Top-p** (0.0–1.0) — diversidad de tokens

Se guarda en `config/local.yaml` bajo `llm.default_provider` y `llm.providers.{id}`.

---

### 3 · Canales

Conecta OpenACM a Telegram y/o Discord.

| Canal | Variable |
|-------|----------|
| Telegram | `TELEGRAM_TOKEN` |
| Discord | `DISCORD_TOKEN` |

- **Telegram:** obtén el token con `@BotFather` → `/newbot`
- **Discord:** `discord.com/developers/applications` → Bot → Token

---

### 4 · Perfil de usuario

Personaliza la identidad del asistente:

- **Nombre del asistente** — cómo se llama (ej: "Cortana")
- **Tu nombre** — cómo te llama a ti
- **Comportamiento / personalidad** — instrucciones de tono, idioma, estilo

Se guarda en `config/local.yaml` bajo la clave `A` con `onboarding_completed: true`.

---

### 5 · Google Services

Conecta Gmail, Drive, Calendar, Sheets y YouTube.

**Paso 1 — Credenciales:** El wizard te guía para obtener el JSON de OAuth2 de Google Cloud Console y lo guarda en `config/google_credentials.json`.

**Paso 2 — Token OAuth2:** Requiere abrir un navegador al menos una vez. Opciones para servidores headless:

```bash
# Opción A: SSH port-forward (recomendado)
ssh -L 47821:localhost:47821 usuario@servidor
# Luego abre http://localhost:47821 en tu navegador local
# y completa el paso de Google en el onboarding web.

# Opción B: desde otro dispositivo en la misma red
# Abre http://IP-DEL-SERVIDOR:47821 desde tu celular o laptop
```

El token se guarda automáticamente en `config/google_token.json`.

---

### 6 · Proveedores personalizados

Agrega cualquier API compatible con OpenAI (LM Studio, vLLM, Ollama API, etc.).

Campos requeridos:
- **Nombre** — identificador visible
- **Base URL** — ej: `http://localhost:1234/v1`
- **Modelo por defecto**

Campos opcionales:
- **API Key** — si la API lo requiere
- **Modelos adicionales** — lista separada por comas

Se guardan en `config/custom_providers.json`.

---

### 7 · Local Router

El Local Router clasifica mensajes cortos sin consumir tokens del LLM (~5ms usando MiniLM embeddings locales).

| Parámetro | Descripción |
|-----------|-------------|
| `enabled` | Activar/desactivar el router |
| `observation_mode` | Solo registra decisiones, no enruta (útil para debugging) |
| `confidence_threshold` | 0.5–1.0 — qué tan seguro debe estar para enrutar sin LLM |

---

### 8 · Code Resurrection

Configura rutas que OpenACM indexa para recuperar contexto de sesiones de trabajo pasadas.

- Agrega rutas de proyectos, workspaces, o cualquier directorio relevante
- OpenACM las usa para reconstruir contexto cuando detecta que estás trabajando en algo familiar

---

### 9 · RAG & Compaction

| Parámetro | Rango | Descripción |
|-----------|-------|-------------|
| `rag_relevance_threshold` | 0.1–0.95 | Qué tan relevante debe ser un recuerdo para incluirlo |
| `compact_threshold` | 5–200 | Mensajes antes de compactar automáticamente |
| `compact_keep_recent` | 2–20 | Mensajes recientes que se conservan completos |

**Valores por defecto:** threshold=0.5, compact=25, keep=6

---

### 10 · Debug & Logging

| Parámetro | Descripción |
|-----------|-------------|
| Debug mode | Activa logs de nivel DEBUG en `data/logs/` |
| Verbose channels | Loguea todos los mensajes de Telegram/Discord |
| Modo de ejecución | `confirmation` \| `auto` \| `yolo` |

**Modos de ejecución:**
- `confirmation` — pide OK antes de ejecutar comandos (recomendado)
- `auto` — ejecuta automáticamente los comandos no bloqueados
- `yolo` — sin restricciones (solo para desarrollo local)

---

### 11 · Dashboard Token

Genera o regenera el token de autenticación para el web UI y el REPL.

```bash
# El token se usa en:
# · http://localhost:47821  (web UI)
# · openacm-cli             (modo REPL interactivo)
```

El token se guarda como `DASHBOARD_TOKEN` en `config/.env`.

---

## Configuración manual (sin wizard)

Si prefieres configurar sin el wizard, edita los archivos directamente:

### `config/.env`
```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
XAI_API_KEY=xai-...
OPENROUTER_API_KEY=sk-or-...
OPENCODE_GO_API_KEY=...
TELEGRAM_TOKEN=123456:ABC...
DISCORD_TOKEN=...
DASHBOARD_TOKEN=...  # genera con: python -c "import secrets; print(secrets.token_hex(32))"
```

### `config/local.yaml`
```yaml
A:
  name: "NombreAsistente"
  system_prompt: "Eres ... [USER INSTRUCTIONS - BEHAVIOR MODE]: My user's name is ..."
  onboarding_completed: true
  rag_relevance_threshold: 0.5
  compact_threshold: 25
  compact_keep_recent: 6

llm:
  default_provider: opencode_go
  providers:
    opencode_go:
      base_url: "https://opencode.ai/zen/go/v1"
      default_model: "kimi-k2.5"

security:
  execution_mode: confirmation

local_router:
  enabled: true
  confidence_threshold: 0.88

resurrection_paths:
  - /ruta/a/tu/proyecto
```

---

## Setup en servidor Linux headless

Flujo recomendado para un VPS o servidor Ubuntu sin GUI:

```bash
# 1. Instalar dependencias
sudo apt update && sudo apt install -y python3.12 python3.12-venv nodejs npm

# 2. Clonar e instalar
git clone https://github.com/Json55Hdz/OpenACM
cd OpenACM
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Buildear el frontend (solo una vez)
cd frontend && npm install && npm run build && cd ..

# 4. Correr el wizard de configuración
openacm-setup --guided

# 5. Para Google OAuth (si lo necesitas): port-forward desde tu máquina local
# ssh -L 47821:localhost:47821 usuario@servidor
# Luego abre http://localhost:47821 en tu navegador

# 6. Iniciar OpenACM
openacm
```

---

---

## openacm-manage — Gestión desde consola

Para **usar** las funcionalidades del agente (swarms, cron, rutinas, etc.) mientras el servidor está corriendo:

```bash
# Menú principal
openacm-manage

# Ir directo a una sección
openacm-manage swarms
openacm-manage cron
openacm-manage routines
openacm-manage skills
openacm-manage agents
openacm-manage stats
```

> **Requisito:** OpenACM debe estar corriendo (`openacm`) antes de usar `openacm-manage`.

### Secciones del manager

| Tecla | Sección | Qué puedes hacer |
|-------|---------|-----------------|
| `S` | Swarms | Crear, planificar, iniciar, detener, monitorear, enviar mensajes |
| `C` | Cron Jobs | Crear jobs con expresiones cron, trigger manual, historial |
| `R` | Rutinas | Ver rutinas detectadas, ejecutar, activar/desactivar, analizar |
| `K` | Skills | Crear, generar con IA, activar/desactivar |
| `A` | Agentes | Crear, generar con IA, chatear/probar |
| `T` | Stats | Tokens, costos, memoria RAG, historial diario |

### Flujo típico de un Swarm

```
openacm-manage swarms
→ [A] Crear nuevo swarm
→ Ingresa nombre y objetivo
→ El agente genera preguntas de clarificación → respondes
→ Se genera el plan (workers + tareas)
→ [I] Iniciar
→ [M] Monitorear en vivo (refresca cada 3s)
```

### Crear un Cron Job

```
openacm-manage cron
→ [A] Crear job
→ Nombre: "Reporte diario"
→ Expresión: 0 9 * * 1-5   (lun-vie a las 9:00)
→ Tipo: custom_command
→ Comando: "genera un resumen del día"
→ Activar: sí
```

---

## Archivos generados

| Archivo | Qué guarda |
|---------|-----------|
| `config/.env` | API keys, tokens, variables de entorno |
| `config/local.yaml` | Config local (sobreescribe default.yaml) |
| `config/custom_providers.json` | Proveedores OpenAI-compatibles |
| `config/google_credentials.json` | Credenciales OAuth2 de Google |
| `config/google_token.json` | Token de acceso de Google (generado tras OAuth) |
| `data/debug_mode` | `true` o `false` — activa logs detallados |

> **Nota:** `config/.env` y `config/local.yaml` están en `.gitignore`. Nunca los subas al repositorio.
