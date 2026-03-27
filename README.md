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

### First Launch

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
│   └── web/
│       └── static/             # Frontend build (copied from frontend/dist)
├── config/                     # Configuration (.env)
├── data/                       # Database and files
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
