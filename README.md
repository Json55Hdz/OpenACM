# 🚀 OpenACM — El Agente Autónomo Tier-1

![OpenACM](https://img.shields.io/badge/OpenACM-Tier--1-blueviolet) 
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Modern-green)

**OpenACM** no es un simple chatbot. Es un agente avanzado (Tier-1) integrado nativamente con tu PC. Puede controlar tu entorno local, escribir y ejecutar código Python en vivo, abrir navegadores Headless para extraer datos de internet, y posee memoria vectorial a largo plazo.

Todo servido desde un Dashboard Web robusto con encriptación local y protegido por token.

---

## 🌟 SuperPoderes (Tier-1 Features)

1. **Memoria RAG ("Hipocampo")**: Gracias a `ChromaDB`, OpenACM recuerda conversaciones antiguas. 
2. **Navegación Autónoma (Browser Agent)**: Usando `Playwright`, el bot puede entrar a webs, hacer login, tomar screenshots y exportar contenido dinámico.
3. **Jupyter Kernel (Python Interactivo)**: OpenACM ejecuta código con estado. Las variables persisten. ¡Si grafica algo en `matplotlib`, te devolverá la foto en el chat!
4. **Multimodalidad y Archivos**: Puede generar PDFs, Excels, zips, tomar fotos de tu propia pantalla y enviártelo de vuelta para que lo descargues usando `/api/media/...`.
5. **Dashboard Protegido**: No requiere internet para el UI. Todo corre en local, cifrado, y protegido por un `DASHBOARD_TOKEN`.

---

## 🛠️ Requisitos Previos

Solo asegúrate de tener descargado el código. Puedes clonarlo usando git o descargar el ZIP desde GitHub.
```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM
```

---

## ⚡ Instalación Automática (Recomendado)

Hemos incluido scripts que hacen TODO por ti: Instalar gestores, crear el entorno, instalar dependencias, Python y los navegadores web del bot.

### 💻 En Windows
Simplemente entra a la carpeta y haz doble clic en el archivo:
- `setup.bat`

O ejecútalo desde tu PowerShell.

### 🐧 En Ubuntu / WSL / Linux
Abre tu terminal en la carpeta del proyecto y ejecuta:
```bash
chmod +x setup.sh run.sh
./setup.sh
```

### 🐳 Instalación con Docker

Puedes desplegar OpenACM al completo usando Docker (recomendado para servidores o para aislar el entorno). Todo el setup y las dependencias ya están listas en la imagen.

1. **Clonar el repositorio**:
   ```bash
   git clone https://github.com/Json55Hdz/OpenACM.git
   cd OpenACM
   ```
2. **Levantar el contenedor**:
   ```bash
   docker-compose up -d --build
   ```
3. **Ver tu Token de acceso**:
   Como el generador corre dentro de Docker, tienes que ver los logs para obtener tu Token incial:
   ```bash
   docker logs openacm
   ```
   *(Copia el `🔑 Dashboard Token`)*
4. **Acceder**:
   Ve a `http://localhost:8080`, ingresa el token y listo. Las bases de datos y la config están vinculadas en las carpetas `./data` y `./config` de tu anfitrión, por lo que **no perderás nada** si apagas o reseteas el contenedor.

---

## 🚀 Cómo Arrancar OpenACM

Ya sea en Windows, Ubuntu o WSL, hemos creado scripts cortos para arrancar el sistema con un solo clic:

### 💻 En Windows
Solo haz doble clic en `run.bat` o ejecútalo en la terminal:
```bash
.\run.bat
```

### 🐧 En Linux / WSL
```bash
./run.sh
```

---

### 🔑 El primer arranque

La primera vez que corras OpenACM, la consola hará tres cosas mágicas:
1. **Generar tu Token**: Verás un texto que dice `🔑 Dashboard Token: O4KzV-...`. **Cópialo**.
2. **Levantar el Dashboard**: Arrancará en `http://localhost:8080`.
3. **Bloquear la Web**: Abres el enlace, pegas tu Token y estás dentro.

---

## 🧩 Notas Importantes

- **Playwright (Browser)**: La primera vez que el bot intente usar internet, puede haber una pausa de un par de minutos mientras se auto-instala Chromium en tu sistema en background.
- **Modelos LLM**: OpenACM soporta OpenAI, Anthropic, Gemini, o modelos locales vía Ollama (ej: `llama3.2`). Entra a `Configuración` en el Dashboard para añadir tus API Keys o URLs.
- **Telegram / Redes**: Si completas la configuración desde la Web, el bot podrá interactuar también por Telegram (¡Con las fotos reales y PDFs subidos como archivos nativos!).
