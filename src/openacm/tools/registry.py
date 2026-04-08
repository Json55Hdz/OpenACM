"""
Tool Registry — manages all available tools.

Handles tool registration, schema generation, and execution
with security policy enforcement.
"""

import json
import re
import time
import types
from typing import Any

import numpy as np
import structlog

from openacm.core.events import EventBus
from openacm.security.sandbox import Sandbox
from openacm.storage.database import Database
from openacm.tools.base import ToolDefinition, get_registered_tools

log = structlog.get_logger()

# Semantic tool selection threshold — tools with cosine similarity above this
# are included in the LLM call. Tuned for multilingual MiniLM embeddings.
SEMANTIC_TOOL_THRESHOLD = 0.28

# Always include these tools regardless of similarity score
ALWAYS_INCLUDE_TOOLS = {
    "send_file_to_chat",
    "run_command",
    "read_file",
    "write_file",
    "edit_file",
    "web_search",
}


class ToolRegistry:
    """Central registry for all tools."""

    def __init__(self, sandbox: Sandbox, event_bus: EventBus, database: Database):
        self.sandbox = sandbox
        self.event_bus = event_bus
        self.database = database
        self.tools: dict[str, ToolDefinition] = {}
        # Semantic tool selection cache
        self._tool_embeddings: np.ndarray | None = None  # shape (N, dim)
        self._tool_names_order: list[str] = []  # parallel to _tool_embeddings rows
        self._semantic_model: Any = None  # reference to sentence-transformer model

    def register(self, tool: ToolDefinition):
        """Register a single tool."""
        self.tools[tool.name] = tool
        log.debug("Tool registered", name=tool.name, risk=tool.risk_level)

    def register_module(self, module: types.ModuleType):
        """
        Register all @tool-decorated functions from a module.
        Imports the module to trigger decorator registration, then
        collects tools that have _tool_definition attributes.
        """
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if callable(attr) and hasattr(attr, "_tool_definition"):
                tool_def: ToolDefinition = attr._tool_definition
                self.register(tool_def)

    def precompute_tool_embeddings(self, model: Any) -> None:
        """
        Pre-compute embeddings for all registered tool descriptions.
        Called once at startup after tools are registered and the
        sentence-transformer model is loaded.
        """
        if not self.tools:
            return

        self._semantic_model = model
        names = []
        descriptions = []
        for name, tool in self.tools.items():
            names.append(name)
            # Use name + description for richer semantic signal
            descriptions.append(f"{name}: {tool.description}")

        self._tool_embeddings = model.encode(
            descriptions, convert_to_numpy=True, show_progress_bar=False
        )
        # Normalize once for fast cosine similarity later
        norms = np.linalg.norm(self._tool_embeddings, axis=1, keepdims=True) + 1e-8
        self._tool_embeddings = self._tool_embeddings / norms
        self._tool_names_order = names

        log.info(
            "Semantic tool embeddings cached",
            tool_count=len(names),
            embedding_dim=self._tool_embeddings.shape[1],
        )

    def get_tools_semantic(self, message: str) -> list[dict[str, Any]] | None:
        """
        Select tools by semantic similarity between message and tool descriptions.

        Returns a list of tool schemas for tools above the similarity threshold,
        or None if semantic selection is unavailable (model not loaded).
        Falls back gracefully — caller should use keyword matching if None.
        """
        if self._semantic_model is None or self._tool_embeddings is None:
            return None

        # Embed user message
        msg_emb = self._semantic_model.encode(
            [message], convert_to_numpy=True, show_progress_bar=False
        )
        msg_norm = msg_emb / (np.linalg.norm(msg_emb, axis=1, keepdims=True) + 1e-8)

        # Cosine similarity against all tools (pre-normalized)
        similarities = (msg_norm @ self._tool_embeddings.T)[0]

        # Select tools above threshold + always-include tools
        selected: list[dict[str, Any]] = []
        for i, (name, sim) in enumerate(zip(self._tool_names_order, similarities)):
            if sim >= SEMANTIC_TOOL_THRESHOLD or name in ALWAYS_INCLUDE_TOOLS:
                selected.append(self.tools[name].to_slim_schema())

        log.debug(
            "Semantic tool selection",
            message=message[:60],
            total_tools=len(self.tools),
            selected_tools=len(selected),
            top_matches=[
                f"{self._tool_names_order[i]}={similarities[i]:.3f}"
                for i in np.argsort(similarities)[::-1][:5]
            ],
        )

        return selected

    # Keyword-to-category mapping for intent-based tool filtering
    INTENT_KEYWORDS: dict[str, list[str]] = {
        "system": [
            "run", "execute", "command", "terminal", "bash", "shell", "install",
            "system", "proceso", "ejecuta", "ejecutar", "pip", "npm",
            # Git / version control
            "git", "commit", "push", "pull", "clone", "branch", "merge", "checkout",
            "stash", "rebase", "diff", "log", "status", "remote", "fetch", "tag",
            "inicializa", "iniciar", "inicializar", "deploy", "desplegar",
            # System info keywords
            "stats", "stat", "cpu", "ram", "memoria", "memory", "disco", "disk",
            "gpu", "temperatura", "temperature", "bateria", "battery", "proceso",
            "rendimiento", "performance", "uso", "usage", "recursos", "resources",
            "info del pc", "info pc", "como esta el pc", "estado del pc",
        ],
        "file": [
            "file", "read", "write", "save", "directory", "folder",
            "archivo", "carpeta", "leer", "escribir", "guardar", "lista",
            "pdf", "excel", "word", "pptx", "powerpoint", "xlsx", "docx",
            "csv", "zip", "download", "descargar", "adjunto", "adjuntar",
            # Code editor tools
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
        "blender": [
            "blender", "3d", "model", "modelar", "modela", "mesh", "malla",
            "bpy", "glb", "gltf", "stl", "obj", "blend",
            "chess", "ajedrez", "pieza", "esfera", "cubo", "cilindro",
            "render", "renderizar", "three-dimensional", "sculpt", "esculp",
            "animate", "animacion", "rig", "skeleton", "esqueleto",
            "three dimensional", "tridimensional",
        ],
        "google": [
            "gmail", "email", "correo", "calendar", "calendario",
            "event", "evento", "drive", "youtube", "google",
        ],
        "meta": [
            "skill", "tool", "herramienta", "habilidad",
            "create_skill", "create_tool",
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
            "light", "lights", "luz", "luces", "lamp", "lampara", "bulb",
            "curtain", "curtains", "blind", "blinds", "persiana", "persianas",
            "cortina", "cortinas", "cover", "shutter",
            "tv", "television", "tele", "lg", "webos",
            "vacuum", "aspiradora", "robot", "xiaomi", "roborock",
            "switch", "enchufe", "plug", "outlet",
            "iot", "smart home", "domótica", "domotica",
            "tuya", "smartlife", "miio",
            "turn on", "turn off", "enciende", "apaga", "encender", "apagar",
            "dim", "brightness", "brillo", "color", "temperatura de color",
            "open", "close", "abre", "cierra", "abrir", "cerrar",
            "volume", "volumen", "channel", "canal", "mute", "silencio",
            "netflix", "youtube", "hdmi",
            "scan devices", "escanear dispositivos",
        ],
    }

    def register_plugin_keywords(self, keywords: dict[str, list[str]]) -> None:
        """Allow plugins to register their own intent keyword categories at runtime."""
        for category, kws in keywords.items():
            if category in self.INTENT_KEYWORDS:
                self.INTENT_KEYWORDS[category] = list(self.INTENT_KEYWORDS[category]) + list(kws)
            else:
                self.INTENT_KEYWORDS[category] = list(kws)

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI function calling format."""
        return [tool.to_openai_schema() for tool in self.tools.values()]

    @staticmethod
    def _kw_match(msg: str, kw: str) -> bool:
        """Word-boundary aware keyword match.

        Prevents subword false positives like 'ui' matching inside 'quieres',
        or 'ai' matching inside 'said', 'ram' inside 'programa', etc.
        Falls back to plain substring for keywords that contain non-word chars
        (file extensions like '.glb', multi-symbol patterns).
        """
        if re.fullmatch(r'[\w\s]+', kw):
            # Pure word/space keyword → require word boundaries
            return bool(re.search(r'(?<!\w)' + re.escape(kw) + r'(?!\w)', msg))
        # Keyword has special chars (e.g. '.glb', ':') → substring is fine
        return kw in msg

    # Short conversational messages that need no tools at all.
    # These are detected BEFORE keyword matching so they never trigger a tool call.
    _CONVERSATIONAL_PREFIXES = (
        # English
        "hi", "hey", "hello", "sup", "what's up", "wassup", "yo",
        "good morning", "good afternoon", "good evening", "good night",
        "thanks", "thank you", "thx", "ty", "cheers",
        "bye", "goodbye", "see you", "later",
        "ok", "okay", "cool", "got it", "understood", "nice", "great", "perfect",
        "lol", "haha", "hehe",
        # Spanish
        "hola", "holis", "buenas", "buenos días", "buenas tardes", "buenas noches",
        "qué tal", "qué onda", "qué pasa", "cómo estás", "cómo te va",
        "gracias", "grac", "grax",
        "adiós", "adios", "bye", "chao", "hasta luego", "hasta pronto",
        "ok", "dale", "claro", "perfecto", "entendido", "sí", "si", "no",
        "jaja", "jeje", "xd", ":)", ":d",
    )

    def _is_conversational(self, message: str) -> bool:
        """Return True if the message is purely conversational and needs no tools."""
        msg = message.strip().lower()
        # Only apply to short messages — longer ones might mix chat + action
        if len(msg) > 80:
            return False
        # Check if any action keyword appears as a whole word in the message
        for keywords in self.INTENT_KEYWORDS.values():
            if any(self._kw_match(msg, kw) for kw in keywords):
                return False
        # No action keywords found in a short message → conversational
        return True

    def get_tools_by_intent(self, message: str) -> list[dict[str, Any]]:
        """Return only tools relevant to the user's message.

        Strategy (in order):
        1. Semantic similarity (if model available) → precise multilingual matching.
           If semantic returns tools → use them.
           If semantic returns [] on a short message → trust it (conversational).
           If semantic returns [] on a long message → keyword fallback as safety net.
        2. Conversational heuristic (only when model unavailable) → no tools for short chat.
        3. Keyword fallback → category-based matching.
        """
        msg_lower = message.lower()

        # Try semantic first — it handles both conversational and action intents better
        # than keyword heuristics, and works in any language.
        semantic_result = self.get_tools_semantic(message)
        if semantic_result is not None:
            if len(semantic_result) > 0:
                return semantic_result
            # Semantic returned 0 matches.
            # Short messages with no matches are genuinely conversational → trust it.
            # Long messages may use domain-specific verbs not in the embedding space
            # (e.g. git commit, inicializa, push) → fall through to keyword fallback.
            if len(msg_lower) <= 60:
                log.debug("Short message, semantic 0 matches — conversational", message=message[:60])
                return []
            log.debug("Long message, semantic 0 matches — keyword fallback", message=message[:60])
        else:
            log.debug("Semantic model unavailable, using keyword fallback")
            # Only apply conversational heuristic when model is not available
            if self._is_conversational(msg_lower):
                log.debug("Conversational message detected — sending no tools", message=message[:60])
                return []

        # Start with general + mcp only (NOT meta by default)
        matched_categories: set[str] = {"general", "mcp"}

        for cat, keywords in self.INTENT_KEYWORDS.items():
            if any(self._kw_match(msg_lower, kw) for kw in keywords):
                matched_categories.add(cat)

        # No specific intent detected in a longer message → general tools as safety net
        if matched_categories == {"general", "mcp"}:
            return [
                t.to_slim_schema()
                for t in self.tools.values()
                if t.category in ("general", "mcp")
            ]

        filtered = [
            t.to_slim_schema()
            for t in self.tools.values()
            if t.category in matched_categories or t.category == "general"
        ]

        log.debug(
            "Keyword tool filtering applied",
            categories=sorted(matched_categories),
            total_tools=len(self.tools),
            filtered_tools=len(filtered),
        )

        return filtered

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str = "",
        channel_id: str = "",
        channel_type: str = "web",
        _brain=None,
    ) -> str:
        """
        Execute a tool by name with the given arguments.

        Injects sandbox, brain, and other context into the tool handler.
        Logs execution to database.
        """
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found"


        tool = self.tools[tool_name]
        start_time = time.time()
        success = True

        try:
            # Inject context into tool call
            result = await tool.handler(
                **arguments,
                _sandbox=self.sandbox,
                _event_bus=self.event_bus,
                _brain=_brain,
                _user_id=user_id,
                _channel_id=channel_id,
                _channel_type=channel_type,
            )
            result_str = str(result)
        except Exception as e:
            result_str = f"Error: {str(e)}"
            success = False
            log.error("Tool execution failed", tool=tool_name, error=str(e))

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Log to database
        try:
            await self.database.log_tool_execution(
                user_id=user_id,
                channel_id=channel_id,
                tool_name=tool_name,
                arguments=json.dumps(arguments, default=str),
                result=result_str[:5000],  # truncate for storage
                success=success,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            log.error("Failed to log tool execution", error=str(e))

        return result_str
