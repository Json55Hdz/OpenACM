"""
All user-facing strings and LLM prompts in one place.

Why: hardcoding strings across engine files makes them hard to find, change,
or translate. Import the constant you need instead of writing inline text.

Naming convention: MSG_<CONTEXT>_<DESCRIPTION>
"""

# ── Task control ─────────────────────────────────────────────────────────────

MSG_CANCELLED = "⏹ Cancelled."
MSG_CANCELLED_FOLLOWUP = "⏹ Cancelled — what else can I help you with?"
MSG_QUEUED_NOTIFY = "⏳ Processing previous task... your message will be sent when it finishes."
MSG_QUEUED_ACK = "⏳ Processing something, please wait... (type «cancel» to stop)"
MSG_QUEUED_DEQUEUED = "▶ Processing your message..."

# ── Progress / status ────────────────────────────────────────────────────────

MSG_THINKING = "🤔 Thinking..."
MSG_COMPACTING = "🗜️ Compacting context..."
# Use as: MSG_STEP.format(iterations=n, max_iterations=m)
MSG_STEP = "🔄 Step {iterations}/{max_iterations}..."
# Use as: MSG_TOOL_EXECUTING.format(tool_name=name)
MSG_TOOL_EXECUTING = "⚙️ Running {tool_name}..."

# ── Errors & fallbacks ───────────────────────────────────────────────────────

MSG_EMPTY_RESPONSE = (
    "⚠️ I ran several tools but didn't get a clear final response. "
    "The results are available in the history. Would you like to try a different approach?"
)
MSG_MAX_ITERATIONS = (
    "⚠️ I ran several tools but reached the step limit. "
    "Check the dashboard to see the full results, or try splitting your request into smaller steps."
)
MSG_TOOL_GEN_FAILED = "Couldn't generate the tool. Try manually with 'create a tool that...'."
# Use as: MSG_TOOL_GEN_SUCCESS.format(result=...)
MSG_TOOL_GEN_SUCCESS = "Based on your repeated workflows, I generated this tool:\n\n{result}"
# Use as: MSG_TOOL_GEN_ERROR.format(error=...)
MSG_TOOL_GEN_ERROR = "Error generating the tool automatically: {error}"
MSG_TOOL_REGISTRY_UNAVAILABLE = "Tool registry unavailable. Could not create the tool."

# ── Routine detection ────────────────────────────────────────────────────────

MSG_ROUTINES_HEADER = "📅 **I detected new routines in your activity:**"
MSG_ROUTINES_FOOTER = "You can view and run them in the **My Routines** tab."

# ── Fast-path responses ──────────────────────────────────────────────────────

MSG_FAST_DONE = "✅ Done."
# Use as: MSG_FAST_SYSINFO.format(raw=...)
MSG_FAST_SYSINFO = "Here's the system summary:\n\n{raw}"
# Use as: MSG_FAST_SCREENSHOT.format(raw=...)
MSG_FAST_SCREENSHOT = "Screenshot taken. {raw}"
# Use as: MSG_FAST_OPENING.format(name=...)
MSG_FAST_OPENING = "Opening {name}..."
MSG_FAST_MEDIA = "Let's go! Opening music..."

# ── Skill manager ────────────────────────────────────────────────────────────

MSG_SKILL_CONTEXT_HEADER = "\n# Specialized Context (for this query only):"
MSG_SKILL_CONTEXT_FOOTER = "\n[Use this context only if relevant to answering]"

# ── Commands (/reset, /compact, …) ───────────────────────────────────────────

MSG_CMD_RESET = (
    "🔄 Reset complete. Conversation history cleared.\n"
    "The AI is ready for a fresh start."
)
MSG_CMD_NO_LLM = "⚠️ No LLM available for compaction."
MSG_CMD_TOO_FEW = "ℹ️ Not enough messages to compact yet (need at least 4)."
# Use as: MSG_CMD_COMPACT_HEADER.format(before=n, after=m)
MSG_CMD_COMPACT_HEADER = "🗜️ Compacted {before} → {after} messages.\n\n"
# Use as: MSG_CMD_COMPACT_FAILED.format(error=e)
MSG_CMD_COMPACT_FAILED = "❌ Compaction failed: {error}"

# ── LLM system prompts ───────────────────────────────────────────────────────

PROMPT_SETUP_MODE = (
    "[SETUP MODE]: You are meeting your user for the first time. "
    "Be natural and conversational — no agendas, no lists, no robotic structure.\n"
    "You need to collect 3 things across the conversation, each one naturally:\n"
    "   1. Their name.\n"
    "   2. What they want to call you.\n"
    "   3. How they want you to behave (tone, style, personality).\n"
    "Collect them one at a time through normal conversation — never announce that you "
    "have 'N questions' or a setup process. "
    "Just chat, ask naturally, and wait for each answer before moving on.\n"
    "Do NOT help with unrelated tasks until you have all 3.\n"
    "Once you have all 3, call the `save_user_profile` tool to finish setup."
)

PROMPT_RESURRECTION_HINT = (
    "\n\n[SYSTEM]: You have the 'Code Resurrection' capability active, which indexes the user's old code. "
    "However, NO path is configured in the system yet. When you sense the current conversation is "
    "naturally wrapping up, offer very friendly to use Code Resurrection. "
    "Tell them they can paste the directory path in the chat so you can add it automatically "
    "(using the add_resurrection_path tool), or give them this exact markdown button link to do it "
    "manually: `[Go to Settings](/config)`."
)

PROMPT_COMPACT_SYSTEM = """\
You are compacting a conversation between a user and an AI assistant.

Produce a DETAILED summary that preserves everything needed to continue the work seamlessly.
Structure your response exactly like this (use the same language the user used):

## What was worked on
- Main goals, tasks, and requests from the user

## Actions taken
- Files created, edited, or deleted — with EXACT full paths
- Commands run and their output or result
- Tools used and what they produced or found
- Code written, bugs fixed, features added

## Key decisions and findings
- Technical decisions made and the reasoning behind them
- Bugs found and how they were fixed
- Important discoveries or constraints uncovered

## Current state
- What is done ✓
- What is pending / in progress (be specific)
- Any errors, blockers, or open questions remaining

Be thorough and specific — this summary permanently replaces the original messages \
and is the ONLY record of this work. Never truncate or omit paths, filenames, or outcomes.\
"""
