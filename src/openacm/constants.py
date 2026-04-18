"""
constants.py — Central definition of magic numbers and default values.

All hardcoded literals that appear in more than one place, or that represent
a tuneable threshold/limit, should live here. Import from this module instead
of scattering literals across the codebase.
"""

# ---------------------------------------------------------------------------
# Network defaults
# ---------------------------------------------------------------------------
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 47821

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_WHATSAPP_BRIDGE_URL = "http://localhost:3001"
DEFAULT_BLENDER_BRIDGE_PORT = 7395

# ---------------------------------------------------------------------------
# Text truncation limits (chars)
# These cap strings before they are stored, sent to the LLM, or returned as
# tool output, so large payloads don't blow context windows or DB columns.
# ---------------------------------------------------------------------------

# PDF / markdown file content injected into LLM messages
TRUNCATE_PDF_CHARS = 12_000
TRUNCATE_FILE_CONTEXT_CHARS = 12_000

# Browser tool page/HTML snippets
TRUNCATE_BROWSER_PAGE_CHARS = 8_000
TRUNCATE_BROWSER_HTML_CHARS = 4_000

# Individual tool execution result stored in the DB
TRUNCATE_TOOL_RESULT_CHARS = 5_000

# Per-task worker output surfaced back to the swarm orchestrator
TRUNCATE_SWARM_TASK_OUTPUT_CHARS = 3_000

# Cron job output stored/returned from scheduler
TRUNCATE_CRON_OUTPUT_CHARS = 2_000

# LLM provider error body logged on failure
TRUNCATE_LLM_ERROR_CHARS = 2_000

# Cron/routine output columns in the DB
TRUNCATE_DB_OUTPUT_CHARS = 4_000
TRUNCATE_DB_ERROR_CHARS = 2_000

# Behaviors string collected during onboarding interview
TRUNCATE_ONBOARDING_BEHAVIORS_CHARS = 1_000

# Stitch tool HTML preview
TRUNCATE_STITCH_PREVIEW_CHARS = 2_000

# RAG document context passed to LLM in /chat/rag endpoint
TRUNCATE_RAG_CONTEXT_CHARS = 12_000

# ---------------------------------------------------------------------------
# Swarm manager
# ---------------------------------------------------------------------------
SWARM_MAX_PARALLEL_WORKERS = 3
SWARM_MAX_TASK_RETRIES = 2      # extra retries; total attempts = retries + 1
SWARM_MAX_BUG_FIX_CYCLES = 5   # max self-correction loops in swarm_tools

# ---------------------------------------------------------------------------
# Local router (semantic routing)
# ---------------------------------------------------------------------------
LOCAL_ROUTER_CONFIDENCE_THRESHOLD = 0.88

# ---------------------------------------------------------------------------
# Tool registry (semantic tool selection)
# ---------------------------------------------------------------------------
SEMANTIC_TOOL_THRESHOLD = 0.28
