"""
Intent keyword categories used by ToolRegistry for fallback tool selection.

Each key maps to a tool category; each value is a list of keywords that
trigger inclusion of that category's tools when semantic search is unavailable
or returns no results.

Add keywords here — never in registry.py.
"""

INTENT_KEYWORDS: dict[str, list[str]] = {
    "system": [
        # General execution
        "run", "execute", "command", "terminal", "bash", "shell", "install",
        "system", "proceso", "ejecuta", "ejecutar", "pip", "npm",
        # Git / version control
        "git", "commit", "push", "pull", "clone", "branch", "merge", "checkout",
        "stash", "rebase", "diff", "log", "status", "remote", "fetch", "tag",
        "inicializa", "iniciar", "inicializar", "deploy", "desplegar",
        # System info
        "stats", "stat", "cpu", "ram", "memoria", "memory", "disco", "disk",
        "gpu", "temperatura", "temperature", "bateria", "battery",
        "rendimiento", "performance", "uso", "usage", "recursos", "resources",
        "info del pc", "info pc", "como esta el pc", "estado del pc",
    ],
    "file": [
        # Basic file ops
        "file", "read", "write", "save", "directory", "folder",
        "archivo", "carpeta", "leer", "escribir", "guardar", "lista",
        # Document formats
        "pdf", "excel", "word", "pptx", "powerpoint", "xlsx", "docx",
        "csv", "zip", "download", "descargar", "adjunto", "adjuntar",
        # Code editing
        "edit", "edita", "editar", "modifica", "modificar", "cambia", "cambiar",
        "reemplaza", "replace", "refactor", "refactoriza",
        "función", "funcion", "clase", "class", "método", "metodo", "method",
        "línea", "linea", "line", "outline", "estructura", "structure",
        "busca en", "search in", "grep", "find in",
        "lint", "linter", "error de sintaxis", "syntax error",
        "arregla el código", "fix the code", "fix code",
        "code", "código", "codigo", "implement", "implementa",
    ],
    "web": [
        "search", "browse", "url", "website", "navigate", "click",
        "busca", "buscar", "web", "página", "página web",
    ],
    "ai": [
        "remember", "memory", "recall", "search_memory",
        "recuerda", "memoria", "olvida", "recordar",
    ],
    "media": [
        "screenshot", "screen", "image", "photo", "capture", "pdf", "send_file",
        "captura", "pantalla", "panta", "foto", "imagen", "enviar archivo",
        "toma un", "toma una", "hazme un", "dame una captura", "graba",
    ],
    "google": [
        "gmail", "email", "correo", "calendar", "calendario",
        "event", "evento", "drive", "youtube", "google",
    ],
    "meta": [
        # Tool/skill listing
        "list tools", "list skills", "what tools", "what skills",
        "listar tools", "listar skills", "listar herramientas",
        "qué tools", "que tools", "qué herramientas", "que herramientas",
        "qué habilidades", "que habilidades",
        "what can you do", "what are your tools", "what are your skills",
        "qué puedes hacer", "que puedes hacer",
        "cuáles son", "cuales son",
        "show tools", "show skills", "muéstrame", "muestrame",
        "available tools", "herramientas disponibles",
        # Skill/tool creation
        "create_skill", "create_tool", "crear skill", "crear tool",
        "nueva habilidad", "nuevo skill", "new skill",
        "create a skill", "make a skill", "define a skill",
    ],
    "mcp": [
        "mcp", "model context protocol", "mcp server", "mcp tool",
        "servidor mcp", "herramienta mcp",
    ],
    "ui": [
        "ui", "interfaz", "interface", "pantalla", "screen", "dashboard",
        "formulario", "form", "landing", "página", "component", "componente",
        "diseño", "design", "frontend", "html", "react", "vue",
        "stitch", "google stitch", "mockup", "prototipo", "prototype",
        "layout", "card", "tabla", "table", "botón", "button",
    ],
    "iot": [
        # Lighting
        "light", "lights", "luz", "luces", "lamp", "lampara", "bulb",
        # Covers
        "curtain", "curtains", "blind", "blinds", "persiana", "persianas",
        "cortina", "cortinas", "cover", "shutter",
        # Entertainment
        "tv", "television", "tele", "lg", "webos",
        "netflix", "youtube", "hdmi",
        # Appliances
        "vacuum", "aspiradora", "robot", "xiaomi", "roborock",
        "switch", "enchufe", "plug", "outlet",
        # Platforms
        "iot", "smart home", "domótica", "domotica",
        "tuya", "smartlife", "miio",
        # Controls
        "turn on", "turn off", "enciende", "apaga", "encender", "apagar",
        "dim", "brightness", "brillo", "color", "temperatura de color",
        "open", "close", "abre", "cierra", "abrir", "cerrar",
        "volume", "volumen", "channel", "canal", "mute", "silencio",
        "scan devices", "escanear dispositivos",
    ],
}
