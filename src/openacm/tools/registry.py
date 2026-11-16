"""
Tool Registry — manages all available tools.

Handles tool registration, schema generation, and execution
with security policy enforcement.
"""

import asyncio
import json
import re
import time
import types
from typing import Any

import numpy as np
import structlog

from openacm.constants import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    SEMANTIC_TOOL_THRESHOLD,
    TRUNCATE_TOOL_RESULT_CHARS,
)
from openacm.core.messages import MSG_TOOL_TIMED_OUT
from openacm.utils.text import truncate
from openacm.core.events import EventBus
from openacm.security.sandbox import Sandbox
from openacm.storage.database import Database
from openacm.tools.base import ToolDefinition, get_registered_tools
from openacm.tools.intent_keywords import INTENT_KEYWORDS as _DEFAULT_INTENT_KEYWORDS

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
    "create_or_update_agent_flow",  # always available so an agent can build its own flows conversationally — see note below on why semantic scoring alone isn't reliable for this tool
}


# Tools that change things outside the chat, and what to tell the user when asking.
# A tool is listed here only for the calls that actually change something.
def is_sensitive_path(path: str, blocked_paths: list[str] | None = None) -> bool:
    """Is this file somewhere a write must never be waved through?

    OpenACM's own code, config and data, installed packages, dotfiles and dot-folders (ssh keys,
    shell profiles), autostart/startup folders, and the owner's configured blocked paths.
    """
    from pathlib import Path

    try:
        target = Path(str(path)).resolve()
    except (OSError, ValueError):
        return True
    low = str(target).lower().replace("\\", "/")
    parts = [p.lower() for p in target.parts]
    if any(p.startswith(".") and p not in (".", "..") for p in parts[1:]):
        return True
    if "site-packages" in parts or "startup" in parts or "autostart" in parts:
        return True
    for blocked in blocked_paths or []:
        b = str(blocked).lower().replace("\\", "/").rstrip("/")
        if b and (low == b or low.startswith(b + "/")):
            return True
    try:
        from openacm.core.config import _find_project_root

        root = _find_project_root().resolve()
        for sub in ("src", "config", "data", "docker"):
            if target == root / sub or (root / sub) in target.parents:
                return True
    except Exception:
        pass
    return False


def confirmation_text(
    tool_name: str,
    arguments: dict[str, Any],
    mode: str = "confirmation",
    blocked_paths: list[str] | None = None,
) -> str | None:
    """The question to show before running this tool call, or None when no approval is needed.

    Follows the owner's security mode like run_command does: "yolo" never asks; "auto" trusts
    plain file writes (the equivalent of a whitelisted command) but still asks for code
    execution, tool changes, security changes, posting and deletions; "confirmation" asks for all.

    The text doubles as the "allow for this session" key, so file tools name the folder:
    approving once covers that folder, not every file the model might write.
    """
    import hashlib
    from pathlib import Path

    if mode == "yolo":
        return None
    if mode == "auto" and tool_name in ("write_file", "edit_file"):
        # Plain file work is trusted in auto mode, but not in places that change how OpenACM
        # or the machine behaves: those are asked about even here.
        target = arguments.get("path") or arguments.get("file_path") or "."
        if not is_sensitive_path(target, blocked_paths):
            return None

    def folder(path: str) -> str:
        # Resolved exactly as the file tools resolve it (symlinks and ".." followed), so the
        # folder we ask about is the folder that is actually written to.
        try:
            return str(Path(str(path or ".")).resolve().parent)
        except (OSError, ValueError):
            return str(path)

    if tool_name in ("write_file", "edit_file"):
        return f"{tool_name} → {folder(arguments.get('path') or arguments.get('file_path'))}/*"
    if tool_name == "run_python":
        code = str(arguments.get("code", ""))
        # The text is also the "allow for this session" key: it carries a hash of the WHOLE
        # code, so approving one snippet can never approve another that starts the same way.
        digest = hashlib.sha256(code.encode("utf-8", "replace")).hexdigest()[:16]
        return f"run_python [{digest}]: {code[:300]}"
    if tool_name == "create_tool" and arguments.get("apply", False):  # without apply it is a preview
        return f"create_tool: {arguments.get('name', '')}"
    if tool_name in ("edit_tool", "delete_tool"):
        return f"{tool_name}: {arguments.get('name', '')}"
    if tool_name == "update_security_mode":
        return f"change the security mode to: {arguments.get('mode', '')}"
    if tool_name in ("post_to_facebook", "post_to_reddit"):
        return f"{tool_name}: " + str(arguments.get("message") or arguments.get("title") or arguments.get("text") or "")[:200]
    if tool_name == "save_social_credentials":
        return f"save credentials for: {arguments.get('platform', '')}"
    if tool_name in ("delete_agent", "delete_swarm"):
        return f"{tool_name}: {arguments.get('agent_id') or arguments.get('swarm_id') or arguments.get('name', '')}"
    return None


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
        # Optional manager references — set by app.py after startup
        self.cron_scheduler: Any = None
        self.swarm_manager: Any = None
        self.mcp_manager: Any = None
        self.app_config: Any = None

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

        # Remember per-tool scores so callers can rank tools by relevance.
        self._last_scores = {
            name: float(sim) for name, sim in zip(self._tool_names_order, similarities)
        }

        # Select tools above threshold + always-include tools.
        # ORDER MATTERS: providers with a tool cap (max_tools_per_call) truncate the
        # list from the end (brain_loop: tools[:cap]), so the most relevant tools must
        # come first — ranked by similarity — and "always include" tools that did not
        # match the message go last. Without this, tools registered late (every plugin)
        # fall off the end of the list and the model never sees them.
        relevant: list[tuple[float, str]] = []
        always_only: list[str] = []
        for name, sim in zip(self._tool_names_order, similarities):
            if sim >= SEMANTIC_TOOL_THRESHOLD:
                relevant.append((float(sim), name))
            elif name in ALWAYS_INCLUDE_TOOLS:
                always_only.append(name)
        relevant.sort(key=lambda t: -t[0])
        selected: list[dict[str, Any]] = [
            self.tools[name].to_slim_schema()
            for name in [n for _, n in relevant] + always_only
        ]

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

    def is_relevant(self, message: str, text: str) -> bool:
        """One-off semantic relevance check between an arbitrary message and
        an arbitrary text — for content that was never part of the
        precomputed tool-embedding matrix (e.g. a dynamically-registered
        flow tool's description), so get_tools_semantic's batch cosine
        similarity doesn't apply. Falls back to a keyword-overlap heuristic
        when the semantic model isn't loaded, same graceful-degradation
        shape as get_tools_by_intent uses for the static tool set."""
        if self._semantic_model is None:
            words = {w for w in re.findall(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]{3,}", text.lower())}
            msg_lower = message.lower()
            return any(self._kw_match(msg_lower, w) for w in words)

        embeddings = self._semantic_model.encode(
            [message, text], convert_to_numpy=True, show_progress_bar=False
        )
        norm = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8)
        similarity = float(norm[0] @ norm[1])
        return similarity >= SEMANTIC_TOOL_THRESHOLD

    # Keyword-to-category mapping for intent-based tool filtering
    INTENT_KEYWORDS: dict[str, list[str]] = _DEFAULT_INTENT_KEYWORDS

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

    def family_of(self, name: str) -> str | None:
        """The toolset a tool belongs to: the plugin package that defines it.
        Core tools have no family (they are selected one by one)."""
        td = self.tools.get(name)
        if td is None:
            return None
        pkg = (getattr(td.handler, "__module__", "") or "").split(".")[0]
        return pkg if pkg and pkg != "openacm" else None

    def expand_families(self, names: list[str]) -> list[str]:
        """`names` (known ones, order kept) followed by every other tool of the same
        families. A plugin's tools are a set: offering half of it leaves the model stuck."""
        out: list[str] = []
        fams: list[str] = []
        for n in names:
            if n in self.tools and n not in out:
                out.append(n)
                f = self.family_of(n)
                if f and f not in fams:
                    fams.append(f)
        if fams:
            for n in self.tools:
                if n not in out and self.family_of(n) in fams:
                    out.append(n)
        return out

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
                # Merge plugin extras with semantic results (deduplicated by name).
                # Keyword-matched plugin tools are a strong intent signal, so they go
                # FIRST (ranked by semantic score) — if the provider caps the tool
                # count, the tail is what gets dropped.
                if plugin_extras:
                    scores = getattr(self, "_last_scores", {}) or {}
                    extras: dict[str, dict[str, Any]] = {}
                    for t in plugin_extras:
                        extras.setdefault(t["function"]["name"], t)
                    ordered_extras = sorted(
                        extras.values(),
                        key=lambda t: -scores.get(t["function"]["name"], 0.0),
                    )
                    rest = [
                        t for t in semantic_result
                        if t["function"]["name"] not in extras
                    ]
                    semantic_result = ordered_extras + rest
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

        category_hits: dict[str, int] = {}
        for cat, keywords in self.INTENT_KEYWORDS.items():
            if cat == "mcp":
                continue  # MCP tools are always included via _merge_mcp
            hits = sum(1 for kw in keywords if self._kw_match(msg_lower, kw))
            if hits:
                matched_categories.add(cat)
                category_hits[cat] = hits

        # No specific intent detected in a longer message → general tools as safety net
        if matched_categories == {"general"}:
            return self._merge_mcp([
                t.to_slim_schema()
                for t in self.tools.values()
                if t.category == "general"
            ])

        # Rank by how strongly the message matched each category (most keyword hits
        # first, "general" last; ties keep registration order). Providers with a tool
        # cap truncate from the end (brain_loop: tools[:cap]), so relevance — not
        # registration order — must decide what survives.
        candidates = [
            t for t in self.tools.values()
            if t.category in matched_categories or t.category == "general"
        ]
        candidates.sort(key=lambda t: -category_hits.get(t.category, 0))  # stable
        filtered = [t.to_slim_schema() for t in candidates]

        log.debug(
            "Keyword tool filtering applied",
            categories=sorted(matched_categories),
            total_tools=len(self.tools),
            filtered_tools=len(filtered),
        )

        return self._merge_mcp(filtered)

    def _blocked_paths(self) -> list[str]:
        policy = getattr(getattr(self, "sandbox", None), "policy", None)
        return list(getattr(getattr(policy, "config", None), "blocked_paths", None) or [])

    def _execution_mode(self) -> str:
        """The owner's security mode: confirmation | auto | yolo (unknown = the strictest)."""
        policy = getattr(getattr(self, "sandbox", None), "policy", None)
        return getattr(policy, "execution_mode", "confirmation") or "confirmation"

    @staticmethod
    def _needs_owner_approval(brain, channel_id: str) -> bool:
        """Who is asking? The owner's own chats are asked; an agent's tools were chosen by the
        owner when configuring it, and a swarm's workers run unattended by design."""
        if getattr(getattr(brain, "config", None), "is_agent", False):
            return False
        return not (channel_id or "").startswith("swarm_")

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

        # People on an external channel only get what their profile allows (agents have their own list)
        access = getattr(_brain, "channel_access", None)
        if access is not None and not getattr(getattr(_brain, "config", None), "is_agent", False):
            if not access.resolve(channel_type, user_id, channel_id).allows(tool_name):
                log.warning("Tool refused by channel access", tool=tool_name, channel=channel_type, user=user_id)
                return f"Error: you do not have permission to use '{tool_name}' in this chat."

        # Blocked areas are blocked for writes in EVERY mode (yolo skips questions, not rules)
        if tool_name in ("write_file", "edit_file"):
            policy = getattr(getattr(self, "sandbox", None), "policy", None)
            target = arguments.get("path") or arguments.get("file_path")
            if target and callable(getattr(policy, "check_path", None)):
                allowed, reason = policy.check_path(str(target))
                if not allowed:
                    return f"Error: {reason}"

        # Powerful tools ask the owner first (the dashboard shows Allow / Deny).
        question = confirmation_text(
            tool_name, arguments, self._execution_mode(), self._blocked_paths()
        )
        if question and self.confirm_callback and self._needs_owner_approval(_brain, channel_id):
            try:
                approved = await self.confirm_callback(tool_name, question, channel_id)
            except Exception as e:
                log.warning("Tool confirmation failed — treating as denied", tool=tool_name, error=str(e))
                approved = False
            if not approved:
                return f"Not run: the user denied '{tool_name}'."

        start_time = time.time()
        success = True

        limit = DEFAULT_TOOL_TIMEOUT_SECONDS if tool.timeout_s is None else tool.timeout_s
        try:
            # Inject context into tool call. asyncio.timeout (not wait_for) so a timeout raised
            # by the tool itself is not mistaken for ours: only our own expiry is reported as one.
            async with asyncio.timeout(limit if limit and limit > 0 else None) as deadline:
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
        except TimeoutError as e:
            if not deadline.expired():
                result_str = f"Error: {e or 'timed out'}"
            else:
                result_str = MSG_TOOL_TIMED_OUT.format(tool_name=tool_name, seconds=int(limit))
                log.error("Tool timed out", tool=tool_name, seconds=limit)
            success = False
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
