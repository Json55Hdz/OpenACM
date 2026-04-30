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

from openacm.constants import SEMANTIC_TOOL_THRESHOLD, TRUNCATE_TOOL_RESULT_CHARS
from openacm.utils.text import truncate
from openacm.core.events import EventBus
from openacm.security.sandbox import Sandbox
from openacm.storage.database import Database
from openacm.tools.base import ToolDefinition, get_registered_tools

log = structlog.get_logger()

# Re-export so callers that imported it from here don't break.
__all__ = ["SEMANTIC_TOOL_THRESHOLD"]

# Always include these tools regardless of similarity score
ALWAYS_INCLUDE_TOOLS = {
    "send_file_to_chat",
    "run_command",
    "read_file",
    "write_file",
    "edit_file",
    "web_search",
    "list_tools",  # always visible so the AI can answer "what can you do?"
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
        # Plugin-registered keyword categories — always checked alongside semantic
        self._plugin_categories: set[str] = set()
        # Callback injected by the web server to request user confirmation before
        # executing sensitive tools.  Signature: (tool, command, channel_id) -> bool
        self.confirm_callback = None

    def register(self, tool: ToolDefinition):
        """Register a single tool."""
        self.tools[tool.name] = tool
        # Invalidate the embedding cache so the next get_tools_semantic call
        # re-encodes the full tool list (including the newly added tool).
        if self._tool_embeddings is not None:
            self._tool_embeddings = None
            self._tool_names_order = []
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
        if self._semantic_model is None:
            return None
        # Embeddings were invalidated (new tools registered) → recompute lazily.
        if self._tool_embeddings is None:
            self.precompute_tool_embeddings(self._semantic_model)

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
            "gpu", "temperatura", "temperature", "bateria", "battery",
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
        """Allow plugins to register their own intent keyword categories at runtime.

        Plugin categories are tracked separately so get_tools_by_intent always
        checks them alongside semantic search (not just as fallback).
        """
        for category, kws in keywords.items():
            if category in self.INTENT_KEYWORDS:
                self.INTENT_KEYWORDS[category] = list(self.INTENT_KEYWORDS[category]) + list(kws)
            else:
                self.INTENT_KEYWORDS[category] = list(kws)
            self._plugin_categories.add(category)

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

    def _get_mcp_tools_slim(self) -> list[dict[str, Any]]:
        """Return slim schemas for all currently-registered MCP tools."""
        return [t.to_slim_schema() for t in self.tools.values() if t.category == "mcp"]

    def _merge_mcp(self, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append any MCP tools not already in *selected*.

        MCP tools are always included — they were deliberately connected and the
        LLM can't call them unless their schemas are in the tool list.
        """
        mcp = self._get_mcp_tools_slim()
        if not mcp:
            return selected
        existing = {t["function"]["name"] for t in selected}
        extras = [t for t in mcp if t["function"]["name"] not in existing]
        if extras:
            log.debug("MCP tools appended", count=len(extras))
        return selected + extras

    def get_tools_by_intent(self, message: str) -> list[dict[str, Any]]:
        """Return only tools relevant to the user's message.

        Strategy (in order):
        1. Semantic similarity (if model available) → precise multilingual matching.
           If semantic returns tools → use them.
           If semantic returns [] on a short message → trust it (conversational).
           If semantic returns [] on a long message → keyword fallback as safety net.
        2. Conversational heuristic (only when model unavailable) → no tools for short chat.
        3. Keyword fallback → category-based matching.

        MCP tools are always appended regardless of selection strategy — they are
        connected on purpose and the LLM must see their schemas to call them.
        """
        msg_lower = message.lower()

        # Always check plugin-registered keyword categories — these represent
        # proactive capabilities (e.g. content capture) that the LLM must see
        # even when semantic search already returned other tools.
        plugin_extras: list[dict[str, Any]] = []
        if self._plugin_categories:
            for cat in self._plugin_categories:
                kws = self.INTENT_KEYWORDS.get(cat, [])
                if any(self._kw_match(msg_lower, kw) for kw in kws):
                    plugin_extras.extend(
                        t.to_slim_schema()
                        for t in self.tools.values()
                        if t.category == cat
                    )

        # Try semantic first — it handles both conversational and action intents better
        # than keyword heuristics, and works in any language.
        semantic_result = self.get_tools_semantic(message)
        if semantic_result is not None:
            if len(semantic_result) > 0:
                # Merge plugin extras with semantic results (deduplicated by name)
                if plugin_extras:
                    seen = {t["function"]["name"] for t in semantic_result}
                    semantic_result = semantic_result + [
                        t for t in plugin_extras if t["function"]["name"] not in seen
                    ]
                return self._merge_mcp(semantic_result)
            # Semantic returned 0 matches.
            # Short messages with no matches are genuinely conversational → trust it.
            # Long messages may use domain-specific verbs not in the embedding space
            # (e.g. git commit, inicializa, push) → fall through to keyword fallback.
            if len(msg_lower) <= 60:
                log.debug("Short message, semantic 0 matches — conversational", message=message[:60])
                # Still return MCP tools + any plugin keyword matches
                mcp = self._get_mcp_tools_slim()
                if plugin_extras:
                    seen = {t["function"]["name"] for t in mcp}
                    mcp = mcp + [t for t in plugin_extras if t["function"]["name"] not in seen]
                return mcp
            log.debug("Long message, semantic 0 matches — keyword fallback", message=message[:60])
        else:
            log.debug("Semantic model unavailable, using keyword fallback")
            # Only apply conversational heuristic when model is not available
            if self._is_conversational(msg_lower):
                log.debug("Conversational message detected — sending no tools", message=message[:60])
                return self._get_mcp_tools_slim()

        # Start with general only (NOT meta by default — mcp handled via _merge_mcp)
        matched_categories: set[str] = {"general"}

        for cat, keywords in self.INTENT_KEYWORDS.items():
            if cat == "mcp":
                continue  # MCP tools are always included via _merge_mcp
            if any(self._kw_match(msg_lower, kw) for kw in keywords):
                matched_categories.add(cat)

        # No specific intent detected in a longer message → general tools as safety net
        if matched_categories == {"general"}:
            return self._merge_mcp([
                t.to_slim_schema()
                for t in self.tools.values()
                if t.category == "general"
            ])

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

        return self._merge_mcp(filtered)

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
                _confirm_callback=self.confirm_callback,
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
                result=truncate(result_str, TRUNCATE_TOOL_RESULT_CHARS),
                success=success,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            log.error("Failed to log tool execution", error=str(e))

        return result_str
