"""
LocalRouter — ultra-fast local intent classifier.

Uses sentence-transformers (already installed for RAG) to classify
user intents via cosine similarity. Runs in OBSERVATION MODE by default:
classifies silently in the background, never blocks the main LLM flow.

Architecture:
- Lazy model load on first use (runs in thread pool, non-blocking)
- Uses all-MiniLM-L6-v2 — already downloaded for RAG, no new download
- Fire-and-forget observation: accumulates stats, never changes behavior
- Zero risk to existing functionality until fast-path mode is explicitly enabled
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from openacm.constants import LOCAL_ROUTER_CONFIDENCE_THRESHOLD

log = structlog.get_logger()

# Where learned examples are persisted across restarts
LEARNED_EXAMPLES_PATH = Path(__file__).parent.parent.parent.parent / "data" / "router_learned.json"

# Where learned phrase→action mappings are persisted
LEARNED_ACTIONS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "router_actions.json"

# Minimum similarity to replay a learned action (stricter than intent classification)
ACTION_LOOKUP_THRESHOLD = 0.90

# Tools allowed to be stored as learned actions (safety whitelist)
# run_command is only stored when the LLM used it for OPEN_APP — see brain._maybe_learn_action
LEARNABLE_TOOLS = {"open_url", "run_command"}

# Tool name → intent mapping for passive learning
# When the LLM calls one of these tools on the first iteration,
# we infer the user's message had this intent.
TOOL_TO_INTENT: dict[str, str] = {
    "system_info":    "SYSTEM_INFO",
    "take_screenshot": "SCREENSHOT",   # tool is named take_screenshot, not screenshot
    "web_search":     "WEB_SEARCH_SIMPLE",
    "open_url":       "OPEN_APP",
}

# run_command hints: if the command contains these keywords → infer intent
RUN_COMMAND_HINTS: dict[str, str] = {
    # App launching
    "chrome":    "OPEN_APP",
    "firefox":   "OPEN_APP",
    "spotify":   "OPEN_APP",
    "discord":   "OPEN_APP",
    "whatsapp":  "OPEN_APP",
    "notepad":   "OPEN_APP",
    "explorer":  "OPEN_APP",
    "start ":    "OPEN_APP",
    "open ":     "OPEN_APP",
    # Media
    "youtube":   "PLAY_MEDIA",
    "music":     "PLAY_MEDIA",
    "musica":    "PLAY_MEDIA",
}

# Intent definitions: label → example phrases
# Cosine similarity is computed between the user message and ALL examples.
# The intent with the highest-scoring example wins.
INTENT_DEFINITIONS: dict[str, list[str]] = {
    "OPEN_APP": [
        "abre chrome", "abre el navegador", "abre firefox", "abre spotify",
        "abre word", "abre excel", "abre discord", "abre whatsapp",
        "open chrome", "launch spotify", "abre el gugel", "abre google",
        "lanza la aplicación", "ejecuta el programa", "abre notepad",
        # Peticiones indirectas / corteses
        "que tal si me abres google en mi navegador",
        "podrías abrirme el navegador",
        "me abres chrome por favor",
        "puedes abrir spotify",
        "abre google en el navegador",
        "me puedes abrir el gugel",
        "podrías lanzar el navegador",
        # English informal / casual
        "can you open google please",
        "can u open google pls",
        "hey can you open chrome for me",
        "could you open the browser",
        "open google for me please",
        "can you launch spotify",
        "please open chrome",
        "open google in my browser",
    ],
    "PLAY_MEDIA": [
        "ponme música", "reproduce música", "pon una canción", "play music",
        "ponme algo en youtube", "reproduce en spotify", "quiero escuchar música",
        "pon algo de música", "coloca música", "play a song for me",
        # Sin tildes (como escribe la gente rápido)
        "ponme musica en spotify",
        "pon musica",
        "reproduce musica",
        "ponme una cancion",
        "quiero escuchar musica",
    ],
    "SYSTEM_INFO": [
        "cuánta RAM tengo", "cómo está el CPU", "qué está usando la memoria",
        "muéstrame el uso del disco", "how much ram do I have",
        "check cpu usage", "ver procesos activos", "uso de recursos del sistema",
        "temperatura del procesador", "espacio libre en disco",
        # Coloquial / informal
        "muestrame los stats del pc",
        "stats del pc",
        "cómo está el pc",
        "como esta el pc wey",
        "qué tal está el pc",
        "info del sistema",
        "info del pc",
        "cuánto ram tengo libre",
        "cuanto disco me queda",
        "cómo va la cpu",
        "show me the pc stats",
        "how is the pc doing",
        "system stats",
        "pc stats",
    ],
    "SCREENSHOT": [
        "toma una captura de pantalla", "screenshot", "captura la pantalla",
        "toma un screenshot", "take a screenshot", "captura de pantalla ahora",
        "fotografía la pantalla", "toma una foto de la pantalla",
        # Coloquial / rápido
        "captura", "toma captura", "ponme un screenshot",
        "toma un screen", "mándame un screenshot", "hazme un screenshot",
        "captura la panta", "quiero ver la pantalla", "foto de la pantalla",
        "haz un screenshot", "dame una captura", "grábame la pantalla",
        # English casual
        "snap a screenshot", "take a screen", "grab a screenshot",
        "show me the screen", "capture the screen", "get a screenshot",
        "screenshot please", "can you screenshot", "take screenshot now",
    ],
    "FILE_SIMPLE": [
        "crea una carpeta nueva", "crea un archivo de texto", "mueve este archivo",
        "borra esta carpeta", "renombra el archivo", "lista los archivos aquí",
        "qué hay en la carpeta descargas", "create a folder", "delete the file",
    ],
    "WEB_SEARCH_SIMPLE": [
        "busca en google", "qué es exactamente", "busca información sobre esto",
        "google search", "busca esto en internet", "quiero saber qué es",
        "search for this online", "buscar en internet",
    ],
    "COMPLEX_TASK": [
        "redáctame un correo profesional", "escribe un ensayo detallado",
        "analiza este documento a fondo", "explícame cómo funciona este algoritmo",
        "resume este texto largo", "crea un plan de negocios completo",
        "ayúdame a programar esta función", "necesito que pienses en esto",
        "escribe código para resolver", "genera un informe completo sobre",
        "investiga y dame un análisis profundo",
    ],
}

# Re-export for backwards compatibility with any caller that imported this directly.
DEFAULT_CONFIDENCE_THRESHOLD = LOCAL_ROUTER_CONFIDENCE_THRESHOLD


@dataclass
class IntentResult:
    intent: str
    confidence: float
    matched_example: str
    latency_ms: float
    is_fast_path_eligible: bool


@dataclass
class LocalRouterStats:
    total_classified: int = 0
    fast_path_eligible: int = 0
    intent_counts: dict[str, int] = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    _latency_samples: list[float] = field(default_factory=list)

    def record(self, result: IntentResult) -> None:
        self.total_classified += 1
        self.intent_counts[result.intent] = self.intent_counts.get(result.intent, 0) + 1
        if result.is_fast_path_eligible:
            self.fast_path_eligible += 1
        self._latency_samples.append(result.latency_ms)
        if len(self._latency_samples) > 100:
            self._latency_samples = self._latency_samples[-100:]
        self.avg_latency_ms = sum(self._latency_samples) / len(self._latency_samples)

    def to_dict(self) -> dict:
        return {
            "total_classified": self.total_classified,
            "fast_path_eligible": self.fast_path_eligible,
            "potential_savings_pct": (
                round(self.fast_path_eligible / self.total_classified * 100, 1)
                if self.total_classified > 0 else 0.0
            ),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "intent_counts": dict(self.intent_counts),
        }


class LocalRouter:
    """
    Semantic intent classifier using sentence-transformers.

    Lazy-loads the model in a thread pool on first use.
    Falls back silently if the model is unavailable.

    Usage:
        router = LocalRouter()
        # Fire-and-forget in observation mode (brain.py):
        asyncio.create_task(router.observe(user_message))
        # Check accumulated stats later:
        stats = router.get_stats()
    """

    # Class-level cache so the model is only loaded once per process
    _model: Any = None
    _intent_embeddings: dict[str, Any] = {}
    _intent_examples: dict[str, list[str]] = {}  # mirrors _intent_embeddings, used for label lookup
    _model_loaded: bool = False
    _model_failed: bool = False

    # Learned action cache: phrase embeddings + parallel action list
    _action_embeddings: Any = None   # numpy array shape (N, dim) or None
    _action_list: list[dict] = []    # [{phrase, tool, args, intent, response}, ...]

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        observation_mode: bool = True,
    ):
        self.confidence_threshold = confidence_threshold
        self.observation_mode = observation_mode
        self.stats = LocalRouterStats()
        self._load_lock = asyncio.Lock()

    async def warm_up(self) -> None:
        """Pre-load the model in the background at app startup. Non-blocking."""
        await self._ensure_model_loaded()

    async def _ensure_model_loaded(self) -> bool:
        if LocalRouter._model_loaded:
            return True
        if LocalRouter._model_failed:
            return False

        async with self._load_lock:
            # Double-check after acquiring lock
            if LocalRouter._model_loaded or LocalRouter._model_failed:
                return LocalRouter._model_loaded
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._load_model_sync)
                LocalRouter._model_loaded = True
                log.info("LocalRouter: model loaded and ready")
                return True
            except Exception as e:
                LocalRouter._model_failed = True
                log.warning("LocalRouter: model load failed, router disabled", error=str(e))
                return False

    def _load_model_sync(self) -> None:
        """Load model and pre-compute intent embeddings. Runs in thread pool."""
        from sentence_transformers import SentenceTransformer

        # Multilingual model: supports 50+ languages, examples in any language
        # generalize automatically — no need to add translations manually.
        # ~470MB download on first use, cached forever after.
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        LocalRouter._model = model

        # Merge hardcoded examples with learned examples from disk
        all_examples = {k: list(v) for k, v in INTENT_DEFINITIONS.items()}
        learned = self._load_learned_examples()
        for intent, phrases in learned.items():
            if intent in all_examples:
                # Deduplicate
                existing = set(all_examples[intent])
                all_examples[intent].extend(p for p in phrases if p not in existing)

        for intent, examples in all_examples.items():
            LocalRouter._intent_embeddings[intent] = model.encode(
                examples, convert_to_numpy=True, show_progress_bar=False
            )
            LocalRouter._intent_examples[intent] = examples

        total_learned = sum(len(v) for v in learned.values())
        if total_learned:
            log.info("LocalRouter: loaded learned examples", count=total_learned)

        # Pre-compute embeddings for learned actions
        self._reload_action_embeddings_sync()

    def _load_learned_examples(self) -> dict[str, list[str]]:
        """Load previously learned examples from disk."""
        try:
            if LEARNED_EXAMPLES_PATH.exists():
                return json.loads(LEARNED_EXAMPLES_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("LocalRouter: could not load learned examples", path=str(LEARNED_EXAMPLES_PATH), error=str(e))
        return {}

    def _save_learned_examples(self, learned: dict[str, list[str]]) -> None:
        """Persist learned examples to disk."""
        try:
            LEARNED_EXAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
            LEARNED_EXAMPLES_PATH.write_text(
                json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("LocalRouter: could not save learned examples", error=str(e))

    async def learn(self, message: str, intent: str) -> bool:
        """
        Add a new example for an intent (passive learning from LLM feedback).
        Persists to disk and hot-reloads embeddings — no restart needed.
        """
        if not LocalRouter._model_loaded or intent not in INTENT_DEFINITIONS:
            return False

        message = message.strip()
        if not message or len(message) < 4:
            return False

        # Don't learn if already an example (hardcoded or learned)
        existing = set(INTENT_DEFINITIONS.get(intent, []))
        learned_on_disk = self._load_learned_examples()
        existing.update(learned_on_disk.get(intent, []))
        if message.lower() in {e.lower() for e in existing}:
            return False

        # Add to disk
        if intent not in learned_on_disk:
            learned_on_disk[intent] = []
        learned_on_disk[intent].append(message)
        self._save_learned_examples(learned_on_disk)

        # Hot-reload: re-encode embeddings for this intent only
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._reload_intent_embeddings, intent, learned_on_disk)
            log.info("LocalRouter: learned new example", intent=intent, message=message)
            return True
        except Exception as e:
            log.warning("LocalRouter: failed to reload embeddings", error=str(e))
            return False

    def _reload_intent_embeddings(self, intent: str, learned: dict[str, list[str]]) -> None:
        """Re-encode embeddings for a single intent after learning. Thread pool."""
        model = LocalRouter._model
        if model is None:
            return
        existing = list(INTENT_DEFINITIONS.get(intent, []))
        extra = [p for p in learned.get(intent, []) if p not in set(existing)]
        all_examples = existing + extra
        LocalRouter._intent_embeddings[intent] = model.encode(
            all_examples, convert_to_numpy=True, show_progress_bar=False
        )
        LocalRouter._intent_examples[intent] = all_examples

    # ── Action learning ────────────────────────────────────────────────────

    def _load_actions(self) -> list[dict]:
        """Load learned actions from disk."""
        try:
            if LEARNED_ACTIONS_PATH.exists():
                return json.loads(LEARNED_ACTIONS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("LocalRouter: could not load learned actions", path=str(LEARNED_ACTIONS_PATH), error=str(e))
        return []

    def _save_actions(self, actions: list[dict]) -> None:
        """Persist learned actions to disk."""
        try:
            LEARNED_ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
            LEARNED_ACTIONS_PATH.write_text(
                json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("LocalRouter: could not save actions", error=str(e))

    def _reload_action_embeddings_sync(self) -> None:
        """Re-encode all stored action phrases. Runs in thread pool (or at load time)."""
        actions = self._load_actions()
        if not actions:
            LocalRouter._action_list = []
            LocalRouter._action_embeddings = None
            return
        model = LocalRouter._model
        if model is None:
            return
        phrases = [a["phrase"] for a in actions]
        LocalRouter._action_embeddings = model.encode(
            phrases, convert_to_numpy=True, show_progress_bar=False
        )
        LocalRouter._action_list = actions

    async def learn_action(
        self,
        phrase: str,
        tool_name: str,
        tool_args: dict,
        intent: str,
        response: str = "",
    ) -> bool:
        """
        Store a phrase → concrete tool call mapping.
        On future requests with similar phrasing, fast_path will replay the action
        directly, skipping the LLM entirely.
        """
        if not LocalRouter._model_loaded:
            return False
        if tool_name not in LEARNABLE_TOOLS:
            return False

        phrase = phrase.strip()
        if not phrase:
            return False

        actions = self._load_actions()

        # Deduplicate: exact same phrase already stored
        if any(a["phrase"].lower() == phrase.lower() for a in actions):
            return False

        actions.append({
            "phrase": phrase,
            "tool": tool_name,
            "args": tool_args,
            "intent": intent,
            "response": response,
        })
        self._save_actions(actions)

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._reload_action_embeddings_sync)
            log.info("LocalRouter: learned new action", tool=tool_name, phrase=phrase)
            return True
        except Exception as e:
            log.warning("LocalRouter: failed to reload action embeddings", error=str(e))
            return False

    def lookup_action(self, message: str) -> dict | None:
        """
        Find the best matching learned action for a message via cosine similarity.
        Returns the action dict if similarity >= ACTION_LOOKUP_THRESHOLD, else None.
        Synchronous — safe to call from fast_path handlers.
        """
        if (
            not LocalRouter._model_loaded
            or LocalRouter._action_embeddings is None
            or not LocalRouter._action_list
        ):
            return None
        try:
            return self._lookup_action_sync(message)
        except Exception:
            return None

    def _lookup_action_sync(self, message: str) -> dict | None:
        """Cosine similarity lookup against stored action phrases. Thread-safe."""
        import numpy as np

        model = LocalRouter._model
        if model is None:
            return None

        msg_emb = model.encode([message], convert_to_numpy=True, show_progress_bar=False)
        msg_norm = msg_emb / (np.linalg.norm(msg_emb, axis=1, keepdims=True) + 1e-8)
        act_norm = LocalRouter._action_embeddings / (
            np.linalg.norm(LocalRouter._action_embeddings, axis=1, keepdims=True) + 1e-8
        )
        sims = (msg_norm @ act_norm.T)[0]
        max_idx = int(np.argmax(sims))
        max_score = float(sims[max_idx])

        if max_score >= ACTION_LOOKUP_THRESHOLD:
            log.info(
                "LocalRouter: action match",
                score=f"{max_score:.3f}",
                phrase=LocalRouter._action_list[max_idx]["phrase"],
                tool=LocalRouter._action_list[max_idx]["tool"],
            )
            return LocalRouter._action_list[max_idx]
        return None

    async def classify(self, message: str) -> IntentResult | None:
        """Classify a message. Returns None if model unavailable or message too short."""
        if not message or len(message.strip()) < 4:
            return None
        if not await self._ensure_model_loaded():
            return None

        start = time.perf_counter()
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, self._classify_sync, message)
        except Exception as e:
            log.debug("LocalRouter: classification error", error=str(e))
            return None

        elapsed_ms = (time.perf_counter() - start) * 1000
        if raw is None:
            return None

        intent, confidence, example = raw
        is_eligible = confidence >= self.confidence_threshold and intent != "COMPLEX_TASK"

        return IntentResult(
            intent=intent,
            confidence=confidence,
            matched_example=example,
            latency_ms=elapsed_ms,
            is_fast_path_eligible=is_eligible,
        )

    def _classify_sync(self, message: str) -> tuple[str, float, str] | None:
        """Cosine similarity classification. Runs in thread pool."""
        import numpy as np

        model = LocalRouter._model
        if model is None:
            return None

        msg_emb = model.encode([message], convert_to_numpy=True, show_progress_bar=False)
        msg_norm = msg_emb / (np.linalg.norm(msg_emb, axis=1, keepdims=True) + 1e-8)

        best_intent = None
        best_score = -1.0
        best_example = ""

        for intent, example_embeddings in LocalRouter._intent_embeddings.items():
            ex_norm = example_embeddings / (
                np.linalg.norm(example_embeddings, axis=1, keepdims=True) + 1e-8
            )
            sims = (msg_norm @ ex_norm.T)[0]
            max_idx = int(np.argmax(sims))
            max_score = float(sims[max_idx])

            if max_score > best_score:
                best_score = max_score
                best_intent = intent
                examples_list = LocalRouter._intent_examples.get(intent, INTENT_DEFINITIONS.get(intent, []))
                best_example = examples_list[max_idx] if max_idx < len(examples_list) else ""

        if best_intent is None:
            return None
        return best_intent, best_score, best_example

    async def observe(self, message: str) -> IntentResult | None:
        """
        Classify and record stats silently. Never raises, never blocks caller.
        Designed for fire-and-forget via asyncio.create_task().
        """
        try:
            result = await self.classify(message)
            if result:
                self.stats.record(result)
                log.info(
                    "LocalRouter",
                    intent=result.intent,
                    confidence=f"{result.confidence:.3f}",
                    fast_path=result.is_fast_path_eligible,
                    latency_ms=f"{result.latency_ms:.1f}ms",
                )
            return result
        except Exception as e:
            log.debug("LocalRouter: observe error", error=str(e))
            return None

    def get_stats(self) -> dict:
        return {
            **self.stats.to_dict(),
            "model_loaded": LocalRouter._model_loaded,
            "model_failed": LocalRouter._model_failed,
            "observation_mode": self.observation_mode,
            "confidence_threshold": self.confidence_threshold,
            "learned_actions": len(LocalRouter._action_list),
        }
