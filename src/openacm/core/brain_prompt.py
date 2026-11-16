"""System prompt building and RAG context injection for Brain."""

import structlog

from openacm.core.acm_context import get_openacm_context, get_short_context
from openacm.core.events import EVENT_SKILL_ACTIVE
from openacm.core.messages import PROMPT_GUEST_NOTICE, PROMPT_SETUP_MODE

log = structlog.get_logger()

# Each long-term memory fragment shown to the model is cut here, with an ellipsis when it is
RAG_FRAGMENT_CHARS = 600


class BrainPromptMixin:

    async def _build_system_prompt(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str,
    ) -> tuple[str, list]:
        """Build the system prompt and return (system_prompt, messages)."""
        system_prompt = self.config.system_prompt

        if not getattr(self.config, "onboarding_completed", False):
            system_prompt = PROMPT_SETUP_MODE

        # Someone who is not the owner gets the persona and nothing of the owner's world: no profile,
        # workspace, terminal history, skills or plugin context.
        if not getattr(self.config, "is_agent", False) and \
                not self.channel_access.resolve(channel_type, user_id, channel_id).owner:
            system_prompt = f"{system_prompt}\n\n{PROMPT_GUEST_NOTICE}"
            ttl_hours = getattr(self.config, "memory_ttl_hours", None)
            messages = await self.memory.get_or_create(user_id, channel_id, system_prompt, ttl_hours=ttl_hours)
            return system_prompt, messages

        existing_messages = await self.memory.get_messages(user_id, channel_id)
        is_new_conversation = len(existing_messages) == 0
        openacm_context = get_openacm_context() if is_new_conversation else get_short_context()

        # Per-conversation workspace override — prepended before everything else so it
        # takes precedence over the global default in every message of this session.
        conv_workspace = self.memory.get_conversation_workspace(user_id, channel_id)
        if conv_workspace:
            workspace_pin = (
                f"# 📁 WORKSPACE FOR THIS CONVERSATION: `{conv_workspace}`\n"
                f"ALL file operations MUST use `{conv_workspace}`. "
                f"This overrides the global default. Do NOT use any other path unless "
                f"the user explicitly says so in this message.\n\n"
            )
            system_prompt = f"{workspace_pin}{openacm_context}\n\n{system_prompt}"
        else:
            system_prompt = f"{openacm_context}\n\n{system_prompt}"

        if self.terminal_history:
            recent = [e for e in self.terminal_history[-5:] if e.get("command")]
            if recent:
                term_lines = []
                for e in recent:
                    output = e.get("output", "").strip()
                    if output:
                        term_lines.append(f"$ {e['command']}\n{output[:200]}")
                    else:
                        term_lines.append(f"$ {e['command']}")
                terminal_ctx = "\n".join(term_lines)
                system_prompt += (
                    f"\n\n## User's Recent Terminal Activity\n"
                    f"The user has an interactive terminal open. "
                    f"These are their recent commands and outputs:\n"
                    f"```\n{terminal_ctx}\n```\n"
                    f"Use this context to understand what the user is working on. "
                    f"You can reference these results in your responses."
                )

        if self.skill_manager:
            skills_prompt = await self.skill_manager.get_active_skills_prompt(content)
            if skills_prompt:
                system_prompt = f"{system_prompt}\n\n{skills_prompt}"
                matched = self.skill_manager.last_matched_skill_names
                if matched:
                    await self.event_bus.emit(EVENT_SKILL_ACTIVE, {
                        "skills": matched,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                    })

        if self.tool_registry:
            mcp_tools = [t for t in self.tool_registry.tools.values() if t.category == "mcp"]
            if mcp_tools:
                servers: dict[str, list[str]] = {}
                for t in mcp_tools:
                    parts = t.name.split("__", 2)
                    server = parts[1] if len(parts) >= 3 else "unknown"
                    servers.setdefault(server, []).append(f"`{t.name}`")
                srv_list = ", ".join(f"{srv}: {', '.join(names)}" for srv, names in servers.items())
                system_prompt = f"{system_prompt}\n\nMCP servers connected: {srv_list}"

        try:
            from openacm.plugins import plugin_manager
            for ext in plugin_manager.get_context_extensions():
                system_prompt = f"{system_prompt}\n\n{ext}"
        except Exception as e:
            log.debug("Plugin context extension failed", error=str(e))

        _sp_key = f"{channel_id}:{user_id}"
        _sp_hash = hash(system_prompt)
        if _sp_hash != self._system_prompt_hash.get(_sp_key):
            ttl_hours = getattr(self.config, "memory_ttl_hours", None)
            messages = await self.memory.get_or_create(user_id, channel_id, system_prompt, ttl_hours=ttl_hours)
            self._system_prompt_hash[_sp_key] = _sp_hash
        else:
            messages = await self.memory.get_messages(user_id, channel_id)

        return system_prompt, messages

    @staticmethod
    def _with_rag_message(messages: list, rag_msg: dict | None) -> list:
        """A copy of `messages` with the long-term memory block right after the system prompt.

        The block is never stored in the conversation: it is added on every read of the history,
        because the agent loop re-reads the history from memory on each iteration.
        """
        if not rag_msg or not messages or messages[0].get("role") != "system":
            return messages
        kept = [
            m for m in messages
            if not (m.get("role") == "system" and "Long-term memory" in str(m.get("content", "")))
        ]
        return kept[:1] + [rag_msg] + kept[1:]

    async def _rag_message(
        self,
        content: str,
        channel_id: str,
        channel_type: str,
    ) -> dict | None:
        """Query RAG long-term memory and build the system message that carries the fragments."""
        # The long-term memory holds what the owner told the assistant. A customer-facing agent
        # talks to other people, so it must never be shown any of it.
        if getattr(self.config, "is_agent", False):
            return None
        rag_msg: dict | None = None
        try:
            from openacm.core.rag import _rag_engine
            from openacm.core.events import EVENT_MEMORY_RECALL

            if not (_rag_engine and _rag_engine.is_ready and content):
                return None

            _rag_key = f"{channel_id}"
            _prev_query, _cached_memories = self._rag_cache.get(_rag_key, ("", []))

            def _word_overlap(a: str, b: str) -> float:
                wa, wb = set(a.lower().split()), set(b.lower().split())
                return len(wa & wb) / max(len(wa | wb), 1)

            if bool(_cached_memories) and _word_overlap(content, _prev_query) >= 0.6:
                memories = _cached_memories
                log.debug("RAG cache hit", channel=channel_id)
            else:
                await self.event_bus.emit(EVENT_MEMORY_RECALL, {
                    "status": "searching",
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "count": 0,
                })
                scored_results = await _rag_engine.query_with_scores(content, top_k=5)
                _threshold = getattr(self.config, "rag_relevance_threshold", 0.5)
                memories = [doc for doc, dist in scored_results if dist < _threshold][:2]
                self._rag_cache[_rag_key] = (content, memories)

            if memories:
                await self.event_bus.emit(EVENT_MEMORY_RECALL, {
                    "status": "found",
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "count": len(memories),
                })
                memory_block = "\n".join(
                    f"- {m[:RAG_FRAGMENT_CHARS]}{'…' if len(m) > RAG_FRAGMENT_CHARS else ''}"
                    for m in memories
                )
                rag_msg = {
                    "role": "system",
                    "content": (
                        f"[Long-term memory — relevant fragments retrieved]:\n"
                        f"{memory_block}\n"
                        f"[Use this information if relevant to the current conversation.]\n"
                        f"***\n"
                        f"[MEMORIA DE CÓDIGO PASADO]: Si lo recuperado arriba contiene código "
                        f"de proyectos antiguos escritos por el humano, IMPORTANTE: "
                        f"Tú eres un Senior Developer. Analiza este código primero. Podría estar desactualizado "
                        f"o contener malas prácticas o bugs de cuando el usuario era Junior. "
                        f"EXTRAE la lógica de negocio y su intención, pero RE-ESCRÍBELO aplicando "
                        f"principios limpios, modernos y robustos antes de usarlo o dárselo."
                    ),
                }
            else:
                await self.event_bus.emit(EVENT_MEMORY_RECALL, {
                    "status": "empty",
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "count": 0,
                })
        except Exception as e:
            # RAG is optional and must never break the turn, but say that memory was not used
            log.warning("Long-term memory lookup failed; answering without it", error=str(e))
            return None

        return rag_msg
