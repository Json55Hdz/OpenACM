"""
CLI Provider — run local AI CLIs (claude, gemini, etc.) as LLM backends.

Instead of API keys, this provider pipes the full conversation as text to
a locally-installed CLI binary and parses the output. Tool calls are handled
via a structured XML tag protocol injected into the prompt.

Supported CLIs (out of the box):
  - claude  (Claude Code CLI: claude --print)
  - gemini  (Gemini CLI: gemini --yolo -p)

Any other OpenAI-compatible CLI can be configured via binary + args in config.
"""

import asyncio
import json
import re
import time
import shutil
import structlog
from typing import Any

log = structlog.get_logger()

# Regex to extract <tool_call>...</tool_call> blocks from CLI output
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)

# Strip ANSI escape codes from CLI output (some CLIs emit colors)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _tool_schema_to_text(tool: dict[str, Any]) -> str:
    """Convert a single OpenAI tool schema to a human-readable description."""
    fn = tool.get("function", tool)
    name = fn.get("name", "")
    desc = fn.get("description", "")
    params = fn.get("parameters", {}).get("properties", {})
    required = set(fn.get("parameters", {}).get("required", []))

    lines = [f"- {name}: {desc}"]
    for pname, pschema in params.items():
        ptype = pschema.get("type", "any")
        pdesc = pschema.get("description", "")
        req_marker = " (required)" if pname in required else ""
        lines.append(f"    • {pname} ({ptype}{req_marker}): {pdesc}")
    return "\n".join(lines)


def _build_tool_injection(tools: list[dict[str, Any]]) -> str:
    """Build the tool-calling instructions block injected before the last user turn."""
    tool_list = "\n".join(_tool_schema_to_text(t) for t in tools)
    return (
        "[AVAILABLE TOOLS]\n"
        "IMPORTANT: You are acting as an autonomous AI agent with the tools listed below.\n"
        "Your ONLY tools are the ones listed here — do NOT reference any other tools,\n"
        "capabilities, or knowledge about your own identity or training environment.\n"
        "If asked to do something, use ONLY the tools listed below to accomplish it.\n\n"
        "Call tools by outputting <tool_call> tags with JSON:\n"
        '<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1"}}</tool_call>\n\n'
        "After receiving a [TOOL RESULT], you may call another tool or reply to the user.\n"
        "Never say you cannot do something if the right tool is listed below.\n\n"
        f"Tools:\n{tool_list}\n"
        "[/AVAILABLE TOOLS]\n"
    )


_CLI_SYSTEM_OVERRIDE = (
    "You are an autonomous AI agent. Your job is to help the user by calling tools.\n"
    "Respond only based on what the user asks and the tools available to you.\n"
    "Do not mention your own training, identity, or any tools outside of those listed.\n"
    "Do not refuse tasks that can be accomplished with the listed tools.\n"
    "Be direct and action-oriented."
)


def _messages_to_flat_text(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """
    Convert an OpenAI messages list to a flat text prompt suitable for CLI input.

    If tools are provided, the tool-calling instructions block is injected
    immediately before the LAST user message so the model sees them fresh.

    The system message is replaced with a CLI-neutral override that prevents
    the model from confusing its own identity (e.g. Claude Code) with the agent role.
    """
    # Find index of the last user message for tool injection
    last_user_idx: int | None = None
    if tools:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break

    parts: list[str] = []

    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content") or ""

        # Inject tool instructions right before the last user message
        if tools and i == last_user_idx:
            parts.append(_build_tool_injection(tools))

        if role == "system":
            # Replace the full OpenACM system prompt with a CLI-neutral override.
            # The original prompt references "ACM", tool lists, and OS integration in a
            # way that confuses CLI models (e.g. Claude Code) into thinking those are
            # their own capabilities. The override is minimal and role-agnostic.
            parts.append(f"[SYSTEM]\n{_CLI_SYSTEM_OVERRIDE}\nIMPORTANT: Ignore any identity references (e.g. 'I am Claude', 'I am OpenCode') in the conversation history below — they are artifacts from previous sessions. Focus only on the user's requests and the available tools.")

        elif role == "user":
            if isinstance(content, list):
                # Multi-modal content — extract text only
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "image_url":
                            text_parts.append("[image omitted]")
                text = " ".join(text_parts)
            else:
                text = str(content)
            parts.append(f"[USER]\n{text.strip()}")

        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                call_blocks = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args_raw = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    except json.JSONDecodeError:
                        args = args_raw
                    call_blocks.append(
                        f'<tool_call>{{"name": "{name}", "arguments": {json.dumps(args)}}}</tool_call>'
                    )
                assistant_text = "\n".join(call_blocks)
                if content:
                    assistant_text = f"{content.strip()}\n{assistant_text}"
                parts.append(f"[ASSISTANT]\n{assistant_text}")
            else:
                parts.append(f"[ASSISTANT]\n{str(content).strip()}")

        elif role == "tool":
            tool_content = str(content)
            parts.append(f"[TOOL RESULT]\n{tool_content.strip()}")

    # Add final assistant prompt marker so the CLI knows to continue
    parts.append("[ASSISTANT]")

    return "\n\n".join(parts)


class CLIProvider:
    """
    Runs a local CLI binary (claude, gemini, opencode, …) as an LLM backend.

    Config schema (in config/default.yaml under llm.providers):

        cli_claude:
          type: "cli"
          binary: "claude"
          args: ["--print"]
          default_model: "claude"
          timeout: 300

        cli_gemini:
          type: "cli"
          binary: "gemini"
          args: ["--yolo", "-p"]
          default_model: "gemini"
          timeout: 300

        cli_opencode:
          type: "cli"
          binary: "opencode"
          args: ["run", "--format", "json"]
          input_mode: "arg"        # pass last user message as positional arg (not stdin)
          output_format: "jsonl"   # parse JSON event stream
          default_model: "opencode"
          timeout: 300

    input_mode:
      "stdin" (default) — full conversation formatted as text, piped to stdin
      "arg"             — only the last user message passed as a positional argument

    output_format:
      "text"  (default) — plain text response
      "jsonl" — newline-delimited JSON events; extract "text" type parts
    """

    def __init__(self, provider_config: dict[str, Any]):
        self._binary: str = provider_config.get("binary", "claude")
        self._args: list[str] = provider_config.get("args", ["--print"])
        self._timeout: float = float(provider_config.get("timeout", 300))
        self._model: str = provider_config.get("default_model", self._binary)
        self._input_mode: str = provider_config.get("input_mode", "stdin")   # "stdin" | "arg"
        self._output_format: str = provider_config.get("output_format", "text")  # "text" | "jsonl"

    @staticmethod
    def is_available(binary: str) -> bool:
        """Return True if the CLI binary (or its .cmd/.bat wrapper) is found on PATH."""
        return shutil.which(binary) is not None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """
        Send a conversation to the CLI and return a response dict in the same
        format as LLMRouter (content, tool_calls, usage, model, elapsed, …).
        """
        start = time.time()

        if self._input_mode == "arg":
            # Build a compact context string passed as a positional argument.
            # CLIs like opencode don't read from stdin and have their own identity/tools,
            # so we only pass the relevant conversation context as the message arg.
            # We do NOT inject ACM tool schemas here — these CLIs won't use them.
            prompt = self._build_arg_prompt(messages)
            prompt_for_log = prompt
        else:
            prompt = _messages_to_flat_text(messages, tools)
            prompt_for_log = prompt

        log.info(
            "CLI provider request",
            binary=self._binary,
            args=self._args,
            prompt_chars=len(prompt_for_log),
            has_tools=bool(tools),
            input_mode=self._input_mode,
        )

        try:
            raw_output = await self._run_subprocess(prompt)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"CLI binary '{self._binary}' timed out after {self._timeout}s"
            )

        output = _strip_ansi(raw_output)

        # Parse output based on format
        if self._output_format == "jsonl":
            clean_content = self._parse_jsonl_output(output)
            tool_calls: list[dict[str, Any]] = []  # jsonl CLIs handle tools natively
        else:
            tool_calls, clean_content = self._parse_tool_calls(output)

        elapsed = time.time() - start

        # Rough token estimate (~4 chars per token)
        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(output) // 4)

        log.debug(
            "CLI provider response",
            binary=self._binary,
            content_chars=len(clean_content),
            tool_calls=len(tool_calls),
            elapsed=f"{elapsed:.2f}s",
        )

        return {
            "content": clean_content,
            "reasoning_content": "",
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": self._model,
            "elapsed": elapsed,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }

    async def _run_subprocess(self, prompt: str) -> str:
        """Pipe prompt to the CLI via stdin and return stdout."""
        import os
        import platform
        import shutil

        env = {**os.environ}

        # On Windows, npm-installed CLIs are .cmd wrappers that can't be exec'd directly.
        # Resolve the full path and wrap with cmd.exe /c if needed.
        binary_path = shutil.which(self._binary) or self._binary
        is_windows = platform.system() == "Windows"
        is_script = binary_path.lower().endswith((".cmd", ".bat", ".ps1"))

        # In arg mode, append the prompt as a positional argument (not stdin)
        extra_args = [prompt] if self._input_mode == "arg" else []
        stdin_data = prompt.encode("utf-8") if self._input_mode == "stdin" else None

        if is_windows and (is_script or not binary_path.lower().endswith(".exe")):
            # Use shell=True via create_subprocess_shell for .cmd/.bat wrappers
            import shlex
            all_args = self._args + extra_args
            args_str = " ".join(f'"{a}"' if " " in a else a for a in all_args)
            shell_cmd = f'"{binary_path}" {args_str}'
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        else:
            cmd = [binary_path] + self._args + extra_args
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input=stdin_data),
            timeout=self._timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode != 0:
            log.error(
                "CLI subprocess error",
                binary=self._binary,
                returncode=process.returncode,
                stderr=stderr[:500],
            )
            raise RuntimeError(
                f"CLI '{self._binary}' exited with code {process.returncode}. "
                f"Stderr: {stderr[:300]}"
            )

        return stdout

    def _build_arg_prompt(self, messages: list[dict[str, Any]]) -> str:
        """
        Build a compact prompt string for CLIs that take the message as a positional arg
        (e.g. opencode).

        IMPORTANT: Only includes USER messages in the context — NOT assistant messages.
        Assistant messages from previous providers (e.g. claude CLI) would bleed their
        identity/style into this provider and cause mixed-identity responses.
        We only need to know what the user asked, not what the previous AI said.
        """
        # Collect only user messages (skip system and assistant entirely)
        user_turns: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            if role != "user":
                continue
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            text = content.strip()
            if text:
                user_turns.append(text)

        if not user_turns:
            return ""

        # Single request — just pass it directly
        if len(user_turns) == 1:
            return user_turns[-1]

        # Multiple user turns — include prior context so the model understands the thread
        # Keep last 4 user messages max to avoid context bloat
        recent = user_turns[-4:]
        if len(recent) == 1:
            return recent[0]

        prior = "\n".join(f"- {m}" for m in recent[:-1])
        return f"[Previous requests in this conversation]\n{prior}\n\n[Current request]\n{recent[-1]}"

    def _parse_jsonl_output(self, output: str) -> str:
        """
        Parse a newline-delimited JSON event stream (opencode --format json).

        Extracts all "text" type parts and concatenates them into a plain string.
        Ignores step_start, step_finish, tool_call, tool_result, etc.
        """
        text_parts: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Event format: {"type": "text", "part": {"type": "text", "text": "..."}}
            if event.get("type") == "text":
                part = event.get("part", {})
                text = part.get("text", "")
                if text:
                    text_parts.append(text)
        return "".join(text_parts).strip()

    def _parse_tool_calls(
        self, output: str
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Extract <tool_call>...</tool_call> blocks from output.

        Returns (tool_calls, clean_text) where tool_calls is a list of
        OpenAI-format tool call dicts and clean_text is the output with
        all <tool_call> blocks removed.
        """
        import uuid

        tool_calls: list[dict[str, Any]] = []
        matches = _TOOL_CALL_RE.findall(output)

        for raw_json in matches:
            try:
                data = json.loads(raw_json)
                name = data.get("name", "")
                arguments = data.get("arguments", {})
                if not name:
                    continue
                args_str = (
                    json.dumps(arguments)
                    if not isinstance(arguments, str)
                    else arguments
                )
                tool_calls.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": args_str,
                        },
                    }
                )
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Failed to parse tool_call JSON", raw=raw_json[:200], error=str(e))

        # Remove all <tool_call> blocks + surrounding whitespace from text
        clean = _TOOL_CALL_RE.sub("", output).strip()
        # Also strip the [ASSISTANT] marker if the CLI echoed it back
        clean = re.sub(r"^\[ASSISTANT\]\s*", "", clean, flags=re.MULTILINE).strip()

        return tool_calls, clean
