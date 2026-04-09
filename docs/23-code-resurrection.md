# 23 - Code Resurrection (Segundo Cerebro de Código)

## ¿Qué es Code Resurrection?
"Code Resurrection" es una característica única de OpenACM que actúa como un Segundo Cerebro de Código local. Le permite al agente "leer" tus repositorios y proyectos de código antiguos de forma silenciosa en segundo plano (mientras no lo estás usando activamente). 

Cuando le pides a OpenACM que construya una nueva característica, el RAG Engine (basado en ChromaDB) ahora puede recuperar automáticamente referencias dentro de tu viejo código para resolver problemas basándose en tu propio estilo y en soluciones que ya programaste en el pasado (por ejemplo, integraciones a APIs complejas que hiciste hace 2 años y de las cuales ya no te acuerdas).

## Arquitectura Autónoma y Segura

### 1. Ingesta Silenciosa (Idle Watcher)
OpenACM contiene un *background watcher* (`resurrection_watcher.py`) que usa una lógica asíncrona inteligente. El proceso **solo funciona cuando OpenACM está en IDLE**. Si el LLM empieza a pensar o procesar un mensaje para ti, la indexación se pausa automáticamente. Además, procesa archivos lentamente (con throttling) para no provocar ningún impacto en el rendimiento de tu CPU/RAM, permitiéndote jugar o compilar sin lag.

### 2. Filtro Anti-Basura Multinivel
Indexar proyectos de software normalmente llenaría la base de datos de basura inservible. El Watcher de OpenACM está programado para **ignorar proactivamente** elementos pesados de los motores más comunes:
- **Node.js**: Ignora la carpeta `node_modules`, directorio `.next`, `dist`, `build`.
- **Python**: Ignora directorios como `.venv`, `__pycache__`, `.pytest_cache`.
- **Unity**: Excluye brutalmente `Library/`, `Temp/`, `Logs/`, `Builds/`.
- **Unreal Engine**: Omite `Binaries/`, `Intermediate/`, `Saved/`.
- **.NET / C#**: Omite carpetas `bin` y `obj`.

### 3. Chunking y Eliminación Inteligente
En lugar de pasar todo un archivo fuente inmenso de 2,000 líneas que mermaría la densidad semántica de los vectores, OpenACM divide los archivos automáticamente en pequeños **bloques superpuestos (overlapping)** de código. Y lo más importante: si modificas un archivo en tu editor, OpenACM eliminará los *embeddings* de tu versión anterior antes de ingestar la nueva, **manteniendo limpia tu Base de Datos** de versiones obsoletas o código muerto.

### 4. Filtro Anti-Junior (Garantía de Calidad)
**¿Qué pasa si mi código del 2021 era muy malo y no usaba Clean Code?**
OpenACM lo tiene previsto. El código recuperado de proyectos antiguos es inyectado al LLM no para que haga un "Copy-Paste" ciego, sino con una instrucción fuerte (System Prompt) de que **él es el Senior Developer**. Su trabajo es extraer la **lógica de negocio abstracta** y las reglas del dominio de ese código viejo, pero proveerte la solución siempre refactorizada usando los estándares modernos.

## ⚠️ Advertencia de Privacidad y Seguridad

> [!CAUTION]
> **Secretos y Tokens Hardcodeados**
> OpenACM está diseñado con seguridad estructural (Secure by Design): el Watcher **ignora por defecto todos los archivos `.env`, `.pem`, `.key`** y variables ocultas. Todo lo que RAG indexa se procesa y se cifra en **tu base de datos local** (`data/vectordb`). Nunca se envía un proyecto entero a internet.
> 
> **PERO OJO:** Si dentro de un archivo de código legítimo (ej. `database.py` o `config.js`) cometiste el error en el pasado de dejar un token AWS o un password *hardcodeado* en el texto sin formato, esa línea será almacenada en tu base de datos Vectorial Local. Si a futuro le pides a un LLM online (como OpenAI o Claude) que te ayude con ese código, el sistema sacará el fragmento de la base local y **sí lo enviará en el prompt hacia la nube** para procesar la respuesta.
> 
> *Solución: Trata siempre de usar proveedores locales (vía Ollama) si vas a trabajar sobre repositorios gubernamentales o con credenciales hardcodeadas sucias.*

## ¿Cómo activarlo?

### Vía Chat (Flujo Autónomo)
Si la característica no está activa, OpenACM mismo te la "ofrecerá" cuando tu conversación con él llegue a una conclusión amigable. Solo necesitas responderle en el chat con la ruta de tu proyecto:
> "Indexa mis juegos de `D:\UnityProjects`"

El LLM detectará tu intención, correrá internamente la herramienta `add_resurrection_path`, guardará la configuración y activará el Watcher sin que tengas que tocar nada de la interfaz.

### Vía Dashboard
1. Abre el Dashboard web (por defecto `http://127.0.0.1:47821`).
2. Ve a la pestaña de **Configuración**.
3. En la sección de **Code Resurrection**, agrega explícitamente las rutas raíz de tus proyectos.

---
**Nota:** El proceso de indexación de repositorios masivos puede tardar horas. No te preocupes si no ves el contexto de forma inmediata en las siguientes preguntas; la paciencia es clave para que OpenACM siga siendo imperceptible para tu PC mientras arma tu copia de seguridad mental paso a paso.
