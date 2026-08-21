# Flow Editor Chat Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user describe a flow in plain language inside the flow editor itself — a small embedded chat, scoped to that one flow, that calls the agent (its real persona) which builds/edits the flow via the existing `create_or_update_agent_flow` tool, with the canvas refreshing live to show progress.

**Architecture:** Two small backend additions (an optional `channel_id` + `extra_system_context` on the existing dashboard `/test` endpoint and `AgentRunner.run()`, both no-ops when omitted) plus one new frontend component (`FlowChatPanel`) that reuses the existing conversation-history hook and mirrors the existing "Test this agent" panel's send/pending pattern, plus a one-line change so the canvas remounts when the flow's `updated_at` changes.

**Tech Stack:** FastAPI + `httpx.AsyncClient`/`ASGITransport` tests (backend), Next.js/React + `@tanstack/react-query` (frontend), pytest with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).

**Spec:** `docs/superpowers/specs/2026-08-21-flow-editor-chat-builder-design.md`

## Global Constraints

- Both new backend params (`channel_id` on `/test`'s body, `extra_system_context` on both `/test`'s body and `AgentRunner.run()`) are optional and default to `None`. Omitting them must be byte-identical to today's existing behavior — this is a hard requirement verified by tests in Task 1.
- `extra_system_context` is appended to the system prompt for that one call only — it is never persisted to the `messages` table and is recomputed fresh on every call.
- `channel_id` isolation relies entirely on the string itself being unique per flow (`agent_{agentId}_flow_{flow.id}`) — `user_id` stays the existing hardcoded `'dashboard_test'` value everywhere, it is not made configurable (unnecessary: `(user_id, channel_id)` is already a unique pair once `channel_id` varies).
- This repo has no frontend unit-test runner (confirmed: no jest/vitest config or test files exist under `frontend/`) — the frontend task is verified with `npx tsc --noEmit` plus the plan's final manual browser verification, not unit tests.
- No changes to the public webhook (`POST /api/agents/{id}/chat`) — only the dashboard-authenticated `/test` path is touched.

---

### Task 1: Backend — `extra_system_context` + `channel_id` on `/test` and `AgentRunner.run()`

**Files:**
- Modify: `src/openacm/web/routers/agents.py:829-852` (`test_agent`)
- Modify: `src/openacm/core/agent_runner.py:136-245` (`AgentRunner.run()`)
- Test: `tests/unit/test_agents_test_endpoint.py` (new file)
- Test: `tests/unit/test_agent_runner_extra_context.py` (new file)

**Interfaces:**
- Produces: `AgentRunner.run(..., extra_system_context: str | None = None)` — appended to the built system prompt when truthy, otherwise a no-op. `POST /api/agents/{agent_id}/test`'s request body gains two optional fields, `channel_id` and `extra_system_context`, forwarded straight into `runner.run(...)`.
- Consumes: nothing new from other tasks — this task has no dependency on Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_agents_test_endpoint.py`:

```python
"""Tests for POST /api/agents/{agent_id}/test — dashboard test-chat endpoint."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from openacm.web.routers import agents as agents_router
from openacm.web.state import _state


@pytest.fixture
def app_client():
    app = FastAPI()
    agents_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


AGENT_ROW = {"id": 5, "name": "TestAgent", "system_prompt": "Base.", "allowed_tools": "all"}


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_agent = AsyncMock(return_value=AGENT_ROW)
    brain = MagicMock()
    monkeypatch.setattr(_state, "database", db)
    monkeypatch.setattr(_state, "brain", brain)
    yield db
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestTestAgentEndpoint:
    async def test_default_behavior_unchanged_when_fields_omitted(self, app_client, _mock_state):
        mock_run = AsyncMock(return_value="hola")
        with patch("openacm.core.agent_runner.AgentRunner.run", mock_run):
            async with app_client as ac:
                resp = await ac.post("/api/agents/5/test", json={"message": "hi"})
        assert resp.status_code == 200
        assert resp.json() == {"response": "hola"}
        mock_run.assert_awaited_once()
        kwargs = mock_run.await_args.kwargs
        assert kwargs.get("channel_id") is None
        assert kwargs.get("extra_system_context") is None
        assert kwargs["user_id"] == "dashboard_test"

    async def test_channel_id_and_extra_system_context_forwarded(self, app_client, _mock_state):
        mock_run = AsyncMock(return_value="ok")
        with patch("openacm.core.agent_runner.AgentRunner.run", mock_run):
            async with app_client as ac:
                resp = await ac.post(
                    "/api/agents/5/test",
                    json={
                        "message": "hi",
                        "channel_id": "agent_5_flow_12",
                        "extra_system_context": "editas el flujo X",
                    },
                )
        assert resp.status_code == 200
        kwargs = mock_run.await_args.kwargs
        assert kwargs["channel_id"] == "agent_5_flow_12"
        assert kwargs["extra_system_context"] == "editas el flujo X"

    async def test_missing_message_still_rejected(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/5/test", json={})
        assert resp.status_code == 400
```

Create `tests/unit/test_agent_runner_extra_context.py`:

```python
"""Tests for AgentRunner.run()'s optional extra_system_context parameter."""
from unittest.mock import MagicMock, patch

from openacm.core.agent_runner import AgentRunner

AGENT = {
    "id": 42, "name": "TestAgent", "description": "d",
    "system_prompt": "Base agent prompt.", "allowed_tools": "all",
}


def _make_runner():
    return AgentRunner(
        llm_router=MagicMock(), tool_registry=MagicMock(), memory=MagicMock(),
        event_bus=MagicMock(), database=None, skill_manager=None,
    )


class TestExtraSystemContext:
    async def test_appended_to_system_prompt_when_provided(self):
        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        runner = _make_runner()
        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi", extra_system_context="Estás editando el flujo X.")

        assert "Base agent prompt." in captured["system_prompt"]
        assert "Estás editando el flujo X." in captured["system_prompt"]

    async def test_not_appended_when_omitted(self):
        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        runner = _make_runner()
        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert captured["system_prompt"] == "Base agent prompt."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_agents_test_endpoint.py tests/unit/test_agent_runner_extra_context.py -v`
Expected: FAIL — `test_agents_test_endpoint.py`'s two "forwarded" assertions fail because the endpoint doesn't read/forward `channel_id`/`extra_system_context` yet (the `user_id` assertion in the first test may already pass — that's fine, unrelated to this change); `test_agent_runner_extra_context.py`'s first test fails with a `TypeError: run() got an unexpected keyword argument 'extra_system_context'`.

- [ ] **Step 3: Implement — `agents.py`**

Replace the `test_agent` endpoint (currently lines 829-852) with:

```python
    @app.post("/api/agents/{agent_id}/test")
    async def test_agent(agent_id: int, request: Request):
        """Test an agent from the UI (no secret needed, uses dashboard auth)."""
        if not _state.database or not _state.brain:
            raise HTTPException(status_code=503, detail="Service not ready")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        channel_id = data.get("channel_id")
        extra_system_context = data.get("extra_system_context")

        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(
            llm_router=_state.brain.llm_router,
            tool_registry=_state.brain.tool_registry,
            memory=_state.brain.memory,
            event_bus=_state.brain.event_bus,
            database=_state.database,
            skill_manager=_state.brain.skill_manager,
        )
        response = await runner.run(
            agent=agent, message=message, user_id="dashboard_test",
            channel_id=channel_id, extra_system_context=extra_system_context,
        )
        return {"response": response}
```

- [ ] **Step 4: Implement — `agent_runner.py`**

Change the `run()` signature (currently lines 136-143) from:

```python
    async def run(
        self,
        agent: dict[str, Any],
        message: str,
        user_id: str = "user",
        channel_id: str | None = None,
        channel_type: str = "agent",
    ) -> str:
```

to:

```python
    async def run(
        self,
        agent: dict[str, Any],
        message: str,
        user_id: str = "user",
        channel_id: str | None = None,
        channel_type: str = "agent",
        extra_system_context: str | None = None,
    ) -> str:
```

Then, immediately before the `config = AssistantConfig(...)` construction (currently lines 215-221), insert:

```python
        if extra_system_context:
            system_prompt = f"{system_prompt}\n\n{extra_system_context}"

```

(i.e. right after the flow-skills block ends, before `config = AssistantConfig(`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_agents_test_endpoint.py tests/unit/test_agent_runner_extra_context.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `pytest -q > /tmp/pytest_chatbuilder_task1.log 2>&1; echo DONE` (redirect to a file, do NOT pipe through `tail`, do NOT background — read the log directly once the command returns; a pytest process on this machine can sometimes not fully exit right away even after printing its full result, that's a known harmless environment quirk). Confirm pass count is the prior baseline plus these 5 new tests, with only the pre-existing unrelated `gmail_classifier` sqlite-column-mismatch errors as known-bad, nothing else new.

- [ ] **Step 7: Commit**

```bash
git add src/openacm/web/routers/agents.py src/openacm/core/agent_runner.py tests/unit/test_agents_test_endpoint.py tests/unit/test_agent_runner_extra_context.py
git commit -m "feat(agents): optional channel_id + extra_system_context on /test and AgentRunner.run()"
```

---

### Task 2: Frontend — `FlowChatPanel` + wiring + live canvas refresh

**Files:**
- Modify: `frontend/hooks/use-agents.ts` (the `test` mutation inside `useAgentMutations()`, currently lines 191-194)
- Create: `frontend/components/flow-editor/FlowChatPanel.tsx`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (toolbar button + panel render, near lines 583-590 and the existing `showSkillPanel` state declaration)
- Modify: `frontend/app/agents/page.tsx` (the `<FlowCanvas ... />` render inside `FlowsTab`, currently lines 1831-1840)

**Interfaces:**
- Consumes: the extended `POST /api/agents/{id}/test` from Task 1 (accepts optional `channel_id`/`extra_system_context`); `useConversationHistory(channelId, userId)` from `frontend/hooks/use-api.ts:389-398` (existing, unchanged — already channel_id-agnostic); `AgentFlow` type from `frontend/hooks/use-agent-flows.ts:6-15` (existing, has `id`, `agent_id`, `name`, `updated_at`, all confirmed non-null).
- Produces: `FlowChatPanel({ agentId, flow }: { agentId: number; flow: AgentFlow })` — no other task consumes this.

- [ ] **Step 1: Extend `useAgentMutations()`'s `test` mutation**

In `frontend/hooks/use-agents.ts`, change the `test` mutation (currently lines 191-194):

```ts
  const test = useMutation({
    mutationFn: ({ id, message }: { id: number; message: string }) =>
      fetchAPI(`/api/agents/${id}/test`, { method: 'POST', body: JSON.stringify({ message }) }),
  });
```

to:

```ts
  const test = useMutation({
    mutationFn: ({ id, message, channel_id, extra_system_context }: {
      id: number; message: string; channel_id?: string; extra_system_context?: string;
    }) =>
      fetchAPI(`/api/agents/${id}/test`, {
        method: 'POST',
        body: JSON.stringify({
          message,
          ...(channel_id && { channel_id }),
          ...(extra_system_context && { extra_system_context }),
        }),
      }),
  });
```

This is additive-only — the existing `TestPanel` component's call site (`test.mutateAsync({ id: agent.id, message: msg })`) keeps working unchanged, since the two new fields are optional.

- [ ] **Step 2: Create `frontend/components/flow-editor/FlowChatPanel.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, Send } from 'lucide-react';
import { useAgentMutations } from '@/hooks/use-agents';
import { useConversationHistory } from '@/hooks/use-api';
import type { AgentFlow } from '@/hooks/use-agent-flows';

interface HistoryItem {
  role: string;
  content: string;
  timestamp: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

export function FlowChatPanel({ agentId, flow }: { agentId: number; flow: AgentFlow }) {
  const { test } = useAgentMutations();
  const qc = useQueryClient();
  const channelId = `agent_${agentId}_flow_${flow.id}`;
  const { data: history } = useConversationHistory(channelId, 'dashboard_test');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (hydrated || !history) return;
    setMessages(
      (history as HistoryItem[])
        .filter(h => h.role === 'user' || h.role === 'assistant')
        .map(h => ({ role: h.role as 'user' | 'assistant', text: h.content }))
    );
    setHydrated(true);
  }, [history, hydrated]);

  const send = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    setMessages(m => [...m, { role: 'user', text: msg }]);
    const extraSystemContext =
      `Estás editando el flujo "${flow.name}" (id=${flow.id}) del agente. Si el usuario te pide crear ` +
      `o modificar este flujo, llama a create_or_update_agent_flow con flow_id=${flow.id} para EDITARLO ` +
      `directamente — no crees un flujo nuevo salvo que el usuario lo pida explícitamente.`;
    try {
      const res = await test.mutateAsync({
        id: agentId, message: msg, channel_id: channelId, extra_system_context: extraSystemContext,
      });
      setMessages(m => [...m, { role: 'assistant', text: res.response }]);
      qc.invalidateQueries({ queryKey: ['agent-flow', flow.id] });
      qc.invalidateQueries({ queryKey: ['agent-flows', agentId] });
    } catch {
      setMessages(m => [...m, { role: 'assistant', text: '⚠️ Error al obtener respuesta.' }]);
    }
  };

  return (
    <div
      className="flex flex-col gap-2 p-3 rounded shrink-0"
      style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', width: 320 }}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em]" style={{ color: 'var(--acm-fg-4)' }}>
        Chat con IA — construir este flujo
      </div>
      {messages.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto acm-scroll">
          {messages.map((m, i) => (
            <div
              key={i}
              className="text-[12px] px-3 py-2 rounded-lg max-w-[90%]"
              style={
                m.role === 'user'
                  ? { background: 'var(--acm-accent-tint)', borderLeft: '2px solid var(--acm-accent)', color: 'var(--acm-fg-2)', marginLeft: 'auto' }
                  : { background: 'var(--acm-base)', color: 'var(--acm-fg-3)' }
              }
            >
              {m.text}
            </div>
          ))}
          {test.isPending && (
            <div className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
              <Loader2 size={11} className="animate-spin" /> Pensando...
            </div>
          )}
        </div>
      )}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Describe el flujo que quieres..."
          disabled={test.isPending}
          className="acm-input flex-1 text-[13px] disabled:opacity-50"
        />
        <button onClick={send} disabled={test.isPending || !input.trim()} className="btn-primary px-2.5 py-2 disabled:opacity-50">
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire the toggle button and panel into `FlowCanvas.tsx`**

Read `frontend/components/flow-editor/FlowCanvas.tsx` first to find:
(a) the existing `const [showSkillPanel, setShowSkillPanel] = useState(false);` declaration (add a new `const [showChatPanel, setShowChatPanel] = useState(false);` right next to it), and
(b) the import block at the top of the file (add `import { FlowChatPanel } from './FlowChatPanel';`).

Then, in the left toolbar column (currently around lines 583-590 — confirm exact current text before editing, it may have shifted slightly), immediately after the "+ Skill" button's closing `</button>`, add a fourth button:

```tsx
        <button onClick={() => setShowChatPanel(v => !v)} className="btn-secondary text-[11px] px-2 py-1 mt-1">
          💬 Chat con IA
        </button>
```

Then, immediately after the toolbar `<div>` closes (i.e. as a new sibling between the 120px-wide toolbar column and the ReactFlow canvas div, inside the outer `<div className="flex gap-2" style={{ height: 500 }}>`), add:

```tsx
      {showChatPanel && <FlowChatPanel agentId={agentId} flow={flow} />}
```

`agentId` and `flow` are both already in scope as `FlowCanvasInner`'s destructured props at this point in the file — no new props/plumbing needed.

- [ ] **Step 4: Live canvas refresh — `page.tsx`**

In `frontend/app/agents/page.tsx`, in `FlowsTab`'s render of `<FlowCanvas ... />` (currently lines 1831-1840), add a `key` prop:

```tsx
        <FlowCanvas
          key={editingFlow.updated_at}
          agentId={agentId}
          flow={editingFlow}
          onSave={(graphJson) => {
```

(i.e. insert `key={editingFlow.updated_at}` as the first prop, right after `<FlowCanvas`.)

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: clean, no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/hooks/use-agents.ts frontend/components/flow-editor/FlowChatPanel.tsx frontend/components/flow-editor/FlowCanvas.tsx frontend/app/agents/page.tsx
git commit -m "feat(agents): embedded chat panel in the flow editor to build/edit flows conversationally"
```

---

## Final manual verification (after both tasks)

Per the spec's Testing section — build+deploy the frontend, start the backend (app-level Telegram/Discord tokens disabled, per this session's established consent), and using the real UI:

1. Open a flow (existing or via "+ Nuevo flujo"), click "💬 Chat con IA", confirm the panel opens with an empty history (first time) or the same conversation you had before (if reopening a flow you already chatted about).
2. Describe a simple flow in Spanish, confirm the agent replies (using its own real persona, not a generic bot), confirm it calls `create_or_update_agent_flow` with this flow's `flow_id` (not a new one), and confirm the canvas visibly updates with the new nodes right after the reply.
3. Close and reopen the same flow's chat panel — confirm the conversation history is still there (persistence works).
4. Open a *different* flow's chat panel — confirm it starts with a clean/empty history (channel isolation actually works, not just claimed).
5. Clean up any test flows/agents created during verification; stop the backend afterward.
