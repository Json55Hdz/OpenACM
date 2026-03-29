# OpenACM — Open AI Computer Manager

![OpenACM](https://img.shields.io/badge/OpenACM-Tier--1-blueviolet)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Modern-green)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript)

**OpenACM** is not a simple chatbot. It is an advanced Tier-1 autonomous agent natively integrated with your PC. It can control your local environment, write and execute Python code in real time, open headless browsers to extract data from the web, and has long-term vector memory.

All served from a modern Web Dashboard built with **React + TypeScript + Next.js + Tailwind CSS**.

---

## Features (Tier-1)

1. **RAG Memory**: Thanks to `ChromaDB`, OpenACM remembers past conversations.
2. **Autonomous Navigation (Browser Agent)**: Using `Playwright`, the bot can visit websites, log in, take screenshots, and export dynamic content.
3. **Jupyter Kernel (Interactive Python)**: OpenACM executes stateful code. Variables persist. If it plots something with `matplotlib`, the image is sent right to the chat!
4. **Multimodality & Files**: It can generate PDFs, Excel files, zips, take screenshots of your own screen, and send them back for download via `/api/media/...`.
5. **Modern React Dashboard**: Built with React 19, TypeScript, Next.js 16, Tailwind CSS, Zustand, TanStack Query, and Sonner.
6. **Local Intent Router**: A hybrid local/cloud architecture that classifies simple requests instantly on-device, skipping the cloud LLM entirely to save cost and latency.

---

## Local Intent Router (Hybrid Architecture)

OpenACM uses a **hybrid local/cloud** processing model. Not every message needs to hit a cloud API.

### How it works

When you send a message, a tiny local classifier runs first (~5–40ms, pure CPU):

```
Your message
     │
     ▼
LocalRouter (sentence-transformers, local CPU)
     │
     ├── confidence > 0.88 + simple intent → execute directly (0 tokens spent)
     │
     └── confidence < 0.88 or complex task → cloud LLM as usual
```

### Self-learning

The router learns automatically from usage. When the LLM handles a message and calls a tool (e.g. `run_command("start chrome")`), OpenACM infers the intent was `OPEN_APP` and stores that phrase as a new example — no manual labeling needed.

Learned examples are saved to `data/router_learned.json` and persist across restarts. Hot-reload means no restart is needed when a new example is learned.

```
First time:   "que tal si me abres el gugel porfa?" → confidence 0.72 → LLM
              LLM calls run_command("start chrome") → learns OPEN_APP
Next time:    "que tal si me abres el gugel porfa?" → confidence 0.97 → local ✓
```

### Supported intents (out of the box)

| Intent | Examples |
|---|---|
| `OPEN_APP` | "abre chrome", "open spotify", "can you launch discord" |
| `PLAY_MEDIA` | "ponme musica en spotify", "play something on youtube" |
| `SYSTEM_INFO` | "cuánta RAM tengo", "check cpu usage" |
| `SCREENSHOT` | "toma una captura", "take a screenshot" |
| `FILE_SIMPLE` | "crea una carpeta", "lista los archivos" |
| `WEB_SEARCH_SIMPLE` | "busca en google qué es Python" |
| `COMPLEX_TASK` | "redáctame un correo", "analiza este documento" → always goes to LLM |

The router uses `paraphrase-multilingual-MiniLM-L12-v2` (50+ languages). You don't need to add translations — Spanish, English, Portuguese, etc. all work from the same set of examples.

> **First run note:** The multilingual model (~470MB) downloads automatically on first use and is cached forever. Subsequent startups are instant.

---

## Minimum System Requirements

### Minimum (basic usage, no local AI features)

| Component | Minimum |
|---|---|
| OS | Windows 10 / Ubuntu 20.04 / macOS 12 |
| CPU | 4 cores, 2.0 GHz |
| RAM | **8 GB** |
| Storage | 5 GB free (Python env + Node + Playwright browsers) |
| Internet | Required for cloud LLM APIs |
| Python | 3.12+ |
| Node.js | 20+ |

### Recommended (full features including Local Router)

| Component | Recommended |
|---|---|
| OS | Windows 11 / Ubuntu 22.04 |
| CPU | 6+ cores, 3.0 GHz |
| RAM | **16 GB** |
| Storage | 10 GB free (adds ~500MB for multilingual NLP model) |
| Internet | Required for cloud LLMs; Local Router works offline |
| Python | 3.12+ |
| Node.js | 20+ |

### For future local AI features (Whisper, Vision, YOLOv8)

| Component | Required |
|---|---|
| GPU | NVIDIA RTX 3060+ (8GB VRAM minimum) |
| RAM | 32 GB |
| Storage | 50 GB free |
| CUDA | 12.x |

> **Without a GPU:** OpenACM runs perfectly fine. The Local Router runs on CPU. Cloud LLMs (OpenAI, Gemini, Groq, Anthropic) handle all AI reasoning. A GPU is only needed for planned future modules (Whisper local transcription, local vision models, YOLOv8 object detection).

---

## Prerequisites

Before starting, you need:

- **Git** (to clone the repository)
- **Node.js 20+** (for the React frontend)
- **Python 3.12+** (for the backend)

```bash
# Clone the repository
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM
```

---

## Automatic Setup (Recommended)

We've included scripts that do EVERYTHING for you: install package managers, create the environment, install dependencies, Python, Node.js, and the bot's web browsers.

### Windows
Simply enter the folder and double-click:
- `setup.bat`

Or run it from PowerShell:
```powershell
.\setup.bat
```

**setup.bat will automatically:**
1. Install Python 3.12 and uv
2. Create the virtual environment
3. Install backend dependencies
4. Install Node.js (if not already installed)
5. Install frontend dependencies
6. **Build the React frontend** (`npm run build`)
7. Copy the build to `src/openacm/web/static/`

### Ubuntu / WSL / Linux
Open your terminal in the project folder and run:
```bash
chmod +x setup.sh run.sh build-frontend.sh
./setup.sh
```

### Docker

You can deploy OpenACM entirely using Docker (recommended for servers or to isolate the environment).

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Json55Hdz/OpenACM.git
   cd OpenACM
   ```
2. **Start the container**:
   ```bash
   docker-compose up -d --build
   ```
3. **View your access token**:
   Since the token generator runs inside Docker, check the logs to get your initial token:
   ```bash
   docker logs openacm
   ```
   *(Copy the `Dashboard Token`)*
4. **Access**:
   Go to `http://localhost:8080`, enter the token, and you're in. Databases and config are bound to the `./data` and `./config` folders on your host, so **nothing is lost** if you stop or reset the container.

---

## Running OpenACM

### Windows
Double-click `run.bat` or run it in the terminal:
```bash
.\run.bat
```

**Note:** `run.bat` will automatically check if the frontend is built. If not, it will run `build-frontend.bat` first.

### Linux / WSL
```bash
./run.sh
```

---

## Frontend Development (Optional)

If you want to modify the React frontend:

```bash
# Enter the frontend directory
cd frontend

# Install dependencies (first time only)
npm install

# Development mode with hot-reload
npm run dev

# Build for production (automatically copies to static/)
npm run build
```

**Frontend technologies:**
- React 19 + TypeScript
- Next.js 16 (App Router)
- Tailwind CSS
- Chart.js for charts
- TanStack Query (React Query) for APIs
- Zustand for global state
- Sonner for notifications
- Lucide React for icons

---

## First Launch

The first time you run OpenACM, the console will do three things:
1. **Generate your Token**: You'll see `Dashboard Token: O4KzV-...`. **Copy it**.
2. **Start the Dashboard**: It will launch at `http://localhost:8080`.
3. **Protect the Web**: Open the link, paste your Token, and you're in.

---

## Important Notes

- **Frontend Build**: The first time you run `run.bat`, the React frontend will be built automatically. This may take 1-2 minutes.
- **Playwright (Browser)**: The first time the bot tries to use the browser, there may be a brief pause while Chromium is auto-installed in the background.
- **LLM Models**: OpenACM supports OpenAI, Anthropic, Gemini, or local models via Ollama (e.g., `llama3.2`). Go to `Configuration` in the Dashboard to add your API Keys or URLs.
- **Telegram / Channels**: If you complete the configuration from the Web, the bot can also interact through Telegram (with real photos and PDFs uploaded as native files!).
- **Local Router model**: On first use, `paraphrase-multilingual-MiniLM-L12-v2` (~470MB) downloads automatically in the background. You'll see `LocalRouter: model loaded and ready` in the console when it's done.

---

## Privacy & Data

OpenACM is **100% self-hosted**. No data ever leaves your machine to any OpenACM server, because there are no OpenACM servers.

| What | Where it lives | Shared with OpenACM? |
|---|---|---|
| API keys (OpenAI, Anthropic, etc.) | `config/.env` — local file only | Never |
| Conversations & history | `data/openacm.db` — local SQLite | Never |
| Uploaded files & media | `data/media/` — local folder | Never |
| Long-term memory (RAG) | `data/chroma/` — local ChromaDB | Never |
| Learned intent examples | `data/router_learned.json` — local file | Never |

**The only outbound traffic is the requests you explicitly trigger:**
- Messages sent to whichever cloud LLM you configure (OpenAI, Anthropic, Gemini, xAI, etc.)
- Telegram / Discord / WhatsApp messages, if you connect those channels
- Browser automation via Playwright, when you ask it to visit a website

If you use Ollama with a local model, **no message ever leaves your machine at all**.

---

## Project Structure

```
OpenACM/
├── frontend/                    # React + Next.js Frontend
│   ├── app/                    # Next.js App Router
│   ├── components/             # React Components
│   ├── hooks/                  # Custom hooks (useAPI, useWebSocket)
│   ├── stores/                 # Zustand stores
│   ├── package.json            # npm dependencies
│   └── next.config.ts          # Next.js config
├── src/openacm/
│   ├── core/
│   │   ├── brain.py            # Central AI engine + agentic loop
│   │   ├── local_router.py     # Local intent classifier (hybrid architecture)
│   │   ├── llm_router.py       # Cloud LLM interface (LiteLLM)
│   │   ├── memory.py           # Conversation memory
│   │   └── rag.py              # Long-term vector memory (ChromaDB)
│   └── web/
│       └── static/             # Frontend build (copied from frontend/dist)
├── data/
│   ├── openacm.db              # SQLite database
│   └── router_learned.json     # Auto-learned intent examples (grows with use)
├── config/                     # Configuration (.env)
├── build-frontend.bat          # Script to build frontend
├── setup.bat                   # Automatic setup
└── run.bat                     # Start OpenACM
```

---

## Dashboard Features

- **Dashboard**: Real-time statistics, activity charts
- **Chat**: Multi-channel conversations, real-time WebSocket, attachment support
- **Tools**: Available tools management
- **Skills**: Create, edit, enable/disable custom skills
- **Configuration**: Change LLM model, manage API keys, preferences

---

## License

BSL 1.1 License - See LICENSE for details.
