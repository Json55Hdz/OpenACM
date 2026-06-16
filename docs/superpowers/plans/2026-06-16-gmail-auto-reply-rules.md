# Gmail Auto-Reply Rules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable auto-reply rules that fire automatically when an incoming email matches exactly one rule with ≥ 90% LLM confidence and contains a single request.

**Architecture:** `AutoReplyRulesEngine` (new class) runs after each classifier batch. Keywords filter candidate rules cheaply, then one LLM call per qualifying email returns a structured confidence+single-request verdict. On pass, the reply is sent via Gmail API and logged. The processor receives the engine as an optional dependency so existing tests are unaffected.

**Tech Stack:** Python/FastAPI (backend), aiosqlite, structlog, Next.js/TypeScript (frontend), lucide-react.

**Spec:** `docs/superpowers/specs/2026-06-16-gmail-auto-reply-rules-design.md`

---

## File Map

| Action | Path |
|--------|------|
| Create | `src/openacm/plugins/gmail_classifier/auto_reply_rules.py` |
| Create | `tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py` |
| Create | `frontend/app/gmail-classifier/components/AutoReplyRulesPanel.tsx` |
| Modify | `src/openacm/storage/database.py` |
| Modify | `src/openacm/plugins/gmail_classifier/processor.py` |
| Modify | `src/openacm/plugins/gmail_classifier/router.py` |
| Modify | `src/openacm/plugins/gmail_classifier/__init__.py` |
| Modify | `frontend/app/gmail-classifier/page.tsx` |

---

## Task 1: DB Migration 27 — two new tables

**Files:**
- Modify: `src/openacm/storage/database.py`

- [ ] **Step 1: Open `database.py` and find the last migration block**

  Look for `if current < 26:` — the new block goes immediately after it, before `await self._db.execute("PRAGMA user_version = ...")`.

- [ ] **Step 2: Add migration 27**

  ```python
  if current < 27:
      await self._db.executescript("""
          CREATE TABLE IF NOT EXISTS gmail_auto_reply_rules (
              id             INTEGER PRIMARY KEY AUTOINCREMENT,
              name           TEXT    NOT NULL,
              keywords       TEXT    NOT NULL DEFAULT '[]',
              description    TEXT    NOT NULL,
              reply_template TEXT    NOT NULL,
              enabled        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
          );
          CREATE TABLE IF NOT EXISTS gmail_auto_reply_log (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              rule_id     INTEGER REFERENCES gmail_auto_reply_rules(id) ON DELETE SET NULL,
              email_id    INTEGER NOT NULL REFERENCES gmail_emails(id),
              confidence  REAL    NOT NULL,
              reasoning   TEXT    NOT NULL DEFAULT '',
              reply_body  TEXT    NOT NULL,
              sent_at     TEXT    NOT NULL DEFAULT (datetime('now'))
          );
      """)
  ```

- [ ] **Step 3: Bump `_SCHEMA_VERSION` from 26 to 27**

  ```python
  _SCHEMA_VERSION = 27
  ```

- [ ] **Step 4: Verify migration runs cleanly**

  ```bash
  pytest tests/unit/test_database.py -v
  ```

  Expected: all existing database tests pass (the new tables are additive).

- [ ] **Step 5: Commit**

  ```bash
  git add src/openacm/storage/database.py
  git commit -m "feat(gmail): db migration 27 — auto_reply_rules and auto_reply_log tables"
  ```

---

## Task 2: AutoReplyRulesEngine — skeleton + keyword filter

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/auto_reply_rules.py`
- Create: `tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py`

- [ ] **Step 1: Write failing tests for `_keyword_filter`**

  Create `tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py`:

  ```python
  """Tests for AutoReplyRulesEngine."""
  from __future__ import annotations
  import pytest
  from unittest.mock import AsyncMock, MagicMock, patch
  from openacm.plugins.gmail_classifier.auto_reply_rules import AutoReplyRulesEngine


  def _make_engine(db=None, llm=None):
      return AutoReplyRulesEngine(db=db, llm_router=llm)


  def _rule(keywords, rule_id=1):
      return {
          "id": rule_id,
          "name": "Test rule",
          "keywords": keywords,
          "description": "desc",
          "reply_template": "Thanks",
      }


  class TestKeywordFilter:
      def test_matches_subject(self):
          engine = _make_engine()
          email = {"subject": "Estado de cuenta", "body_text": ""}
          rules = [_rule(["estado de cuenta"])]
          assert engine._keyword_filter(email, rules) == rules

      def test_matches_body(self):
          engine = _make_engine()
          email = {"subject": "Hola", "body_text": "necesito el estado de cuenta"}
          rules = [_rule(["estado de cuenta"])]
          assert engine._keyword_filter(email, rules) == rules

      def test_case_insensitive(self):
          engine = _make_engine()
          email = {"subject": "ESTADO DE CUENTA", "body_text": ""}
          rules = [_rule(["estado de cuenta"])]
          assert engine._keyword_filter(email, rules) == rules

      def test_no_match(self):
          engine = _make_engine()
          email = {"subject": "Hola", "body_text": "¿Cómo estás?"}
          rules = [_rule(["estado de cuenta"])]
          assert engine._keyword_filter(email, rules) == []

      def test_multiple_rules_only_matching_returned(self):
          engine = _make_engine()
          email = {"subject": "factura duplicada", "body_text": ""}
          rule_a = _rule(["estado de cuenta"], rule_id=1)
          rule_b = _rule(["factura", "duplicada"], rule_id=2)
          result = engine._keyword_filter(email, [rule_a, rule_b])
          assert result == [rule_b]

      def test_empty_keywords_never_matches(self):
          engine = _make_engine()
          email = {"subject": "cualquier cosa", "body_text": "texto"}
          rules = [_rule([])]
          assert engine._keyword_filter(email, rules) == []
  ```

- [ ] **Step 2: Run — verify they fail**

  ```bash
  pytest tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py -v
  ```

  Expected: `ImportError` or `ModuleNotFoundError` (file doesn't exist yet).

- [ ] **Step 3: Create `auto_reply_rules.py` with skeleton + `_keyword_filter`**

  ```python
  """AutoReplyRulesEngine — automatic rule-based email replies."""
  from __future__ import annotations

  import base64
  import json
  import re
  from email.mime.text import MIMEText
  from typing import Any

  import structlog

  log = structlog.get_logger()

  CONFIDENCE_THRESHOLD = 0.90

  _EVAL_PROMPT = """\
  You are deciding whether an incoming email matches one of the auto-reply rules below.

  EMAIL
  Subject: {subject}
  Body:
  {body}

  RULES
  {rules_block}

  Respond with ONLY a JSON object (no markdown, no code fences):
  {{
    "matched_rule_id": <integer or null>,
    "confidence": <float 0.0-1.0>,
    "is_single_request": <true or false>,
    "reasoning": "<1-2 sentence explanation>"
  }}

  Instructions:
  - matched_rule_id: id of the rule whose description best fits the email, or null.
  - confidence: your certainty. Use < 0.90 if there is any doubt at all.
  - is_single_request: true ONLY if the email asks about exactly one topic or action.
  """


  class _EvalResult:
      __slots__ = ("matched_rule_id", "confidence", "is_single_request", "reasoning")

      def __init__(self, matched_rule_id, confidence, is_single_request, reasoning):
          self.matched_rule_id = matched_rule_id
          self.confidence = float(confidence)
          self.is_single_request = bool(is_single_request)
          self.reasoning = reasoning or ""


  class AutoReplyRulesEngine:
      def __init__(self, db: Any, llm_router: Any):
          self._db = db
          self._llm = llm_router

      # ------------------------------------------------------------------ #
      #  Public                                                              #
      # ------------------------------------------------------------------ #

      async def evaluate_batch(self, emails: list[dict]) -> None:
          """Called after each classifier batch. Sends auto-replies where eligible."""
          if not emails:
              return
          rules = await self._load_enabled_rules()
          if not rules:
              return
          for email in emails:
              if email.get("is_replied"):
                  continue
              candidates = self._keyword_filter(email, rules)
              if not candidates:
                  continue
              result = await self._llm_evaluate(email, candidates)
              if result is None:
                  continue
              if result.matched_rule_id is None:
                  continue
              if result.confidence < CONFIDENCE_THRESHOLD or not result.is_single_request:
                  continue
              rule = next((r for r in candidates if r["id"] == result.matched_rule_id), None)
              if rule is None:
                  continue
              cursor = await self._db._db.execute(
                  "SELECT id FROM gmail_emails WHERE gmail_id = ?", (email["gmail_id"],)
              )
              row = await cursor.fetchone()
              if not row:
                  continue
              await self._send_and_log(email, row["id"], rule, result)

      # ------------------------------------------------------------------ #
      #  Internal                                                            #
      # ------------------------------------------------------------------ #

      async def _load_enabled_rules(self) -> list[dict]:
          cursor = await self._db._db.execute(
              "SELECT id, name, keywords, description, reply_template "
              "FROM gmail_auto_reply_rules WHERE enabled = 1"
          )
          rows = await cursor.fetchall()
          result = []
          for r in rows:
              try:
                  kw = json.loads(r["keywords"])
              except Exception:
                  kw = []
              result.append({
                  "id": r["id"],
                  "name": r["name"],
                  "keywords": kw,
                  "description": r["description"],
                  "reply_template": r["reply_template"],
              })
          return result

      def _keyword_filter(self, email: dict, rules: list[dict]) -> list[dict]:
          text = f"{email.get('subject', '')} {email.get('body_text', '')}".lower()
          return [r for r in rules if r["keywords"] and any(kw.lower() in text for kw in r["keywords"])]

      async def _llm_evaluate(self, email: dict, candidate_rules: list[dict]) -> _EvalResult | None:
          rules_block = "\n".join(
              f"Rule {r['id']} — {r['name']}: {r['description']}"
              for r in candidate_rules
          )
          body = (email.get("body_text") or "")[:1500]
          prompt = _EVAL_PROMPT.format(
              subject=email.get("subject", ""),
              body=body,
              rules_block=rules_block,
          )
          try:
              raw = await self._llm.chat(messages=[{"role": "user", "content": prompt}])
              cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
              data = json.loads(cleaned)
              return _EvalResult(
                  matched_rule_id=data.get("matched_rule_id"),
                  confidence=data.get("confidence", 0.0),
                  is_single_request=data.get("is_single_request", False),
                  reasoning=data.get("reasoning", ""),
              )
          except Exception as exc:
              log.warning("AutoReplyRulesEngine LLM eval failed", error=str(exc))
              return None

      async def _send_and_log(
          self,
          email: dict,
          local_email_id: int,
          rule: dict,
          result: _EvalResult,
      ) -> None:
          try:
              from openacm.tools.google_services import _get_google_service
              service = await _get_google_service("gmail", "v1")
              subject = email.get("subject", "")
              if not subject.lower().startswith("re:"):
                  subject = f"Re: {subject}"
              msg = MIMEText(rule["reply_template"])
              msg["to"] = email["sender_email"]
              msg["subject"] = subject
              raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
              service.users().messages().send(userId="me", body={"raw": raw}).execute()
          except Exception as exc:
              log.error("AutoReplyRulesEngine send failed", rule_id=rule["id"], error=str(exc))
              return  # no log row — email not marked replied
          try:
              await self._db._db.execute(
                  "INSERT INTO gmail_auto_reply_log "
                  "(rule_id, email_id, confidence, reasoning, reply_body) VALUES (?, ?, ?, ?, ?)",
                  (rule["id"], local_email_id, result.confidence, result.reasoning, rule["reply_template"]),
              )
              await self._db._db.execute(
                  "UPDATE gmail_emails SET is_replied = 1 WHERE id = ?", (local_email_id,)
              )
              await self._db._db.commit()
              log.info("Auto-reply sent", rule_id=rule["id"], email_id=local_email_id,
                       confidence=result.confidence)
          except Exception as exc:
              log.error("AutoReplyRulesEngine log/update failed", error=str(exc))
  ```

- [ ] **Step 4: Run keyword filter tests**

  ```bash
  pytest tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py::TestKeywordFilter -v
  ```

  Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add src/openacm/plugins/gmail_classifier/auto_reply_rules.py \
          tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py
  git commit -m "feat(gmail): AutoReplyRulesEngine skeleton + keyword filter"
  ```

---

## Task 3: AutoReplyRulesEngine — LLM evaluation

**Files:**
- Modify: `tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py`
- (no implementation changes needed — `_llm_evaluate` already written)

- [ ] **Step 1: Add `TestLlmEvaluate` class to the test file**

  Append below `TestKeywordFilter`:

  ```python
  class TestLlmEvaluate:
      def _mock_llm(self, response: str):
          llm = MagicMock()
          llm.chat = AsyncMock(return_value=response)
          return llm

      async def test_returns_eval_result_on_valid_json(self):
          llm = self._mock_llm(
              '{"matched_rule_id": 1, "confidence": 0.95, '
              '"is_single_request": true, "reasoning": "Single clear request."}'
          )
          engine = _make_engine(llm=llm)
          email = {"subject": "Estado de cuenta", "body_text": "Necesito mi estado de cuenta."}
          result = await engine._llm_evaluate(email, [_rule(["estado de cuenta"])])
          assert result is not None
          assert result.matched_rule_id == 1
          assert result.confidence == 0.95
          assert result.is_single_request is True
          assert "Single" in result.reasoning

      async def test_strips_markdown_code_fences(self):
          llm = self._mock_llm(
              '```json\n{"matched_rule_id": 2, "confidence": 0.91, '
              '"is_single_request": true, "reasoning": "ok"}\n```'
          )
          engine = _make_engine(llm=llm)
          result = await engine._llm_evaluate(
              {"subject": "x", "body_text": "y"}, [_rule(["x"], rule_id=2)]
          )
          assert result is not None
          assert result.matched_rule_id == 2

      async def test_returns_none_on_llm_failure(self):
          llm = MagicMock()
          llm.chat = AsyncMock(side_effect=RuntimeError("API error"))
          engine = _make_engine(llm=llm)
          result = await engine._llm_evaluate({"subject": "x", "body_text": ""}, [_rule(["x"])])
          assert result is None

      async def test_returns_none_on_invalid_json(self):
          llm = self._mock_llm("not json at all")
          engine = _make_engine(llm=llm)
          result = await engine._llm_evaluate({"subject": "x", "body_text": ""}, [_rule(["x"])])
          assert result is None

      async def test_null_matched_rule_id_preserved(self):
          llm = self._mock_llm(
              '{"matched_rule_id": null, "confidence": 0.4, '
              '"is_single_request": false, "reasoning": "no match"}'
          )
          engine = _make_engine(llm=llm)
          result = await engine._llm_evaluate({"subject": "x", "body_text": ""}, [_rule(["x"])])
          assert result is not None
          assert result.matched_rule_id is None
  ```

- [ ] **Step 2: Run LLM evaluation tests**

  ```bash
  pytest tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py::TestLlmEvaluate -v
  ```

  Expected: 5 tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py
  git commit -m "test(gmail): LLM evaluation tests for AutoReplyRulesEngine"
  ```

---

## Task 4: AutoReplyRulesEngine — send and log

**Files:**
- Modify: `tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py`

- [ ] **Step 1: Add `TestSendAndLog` class**

  Append below `TestLlmEvaluate`:

  ```python
  class TestSendAndLog:
      def _make_db_with_email(self, db):
          """Insert a minimal email row and return its id."""
          # The `db` fixture has the full schema after migration 27.
          return db

      async def test_writes_log_row_and_marks_replied(self, db):
          # Seed category and email
          await db._db.execute(
              "INSERT INTO gmail_categories (id, name) VALUES (1, 'Test')"
          )
          await db._db.execute(
              "INSERT INTO gmail_emails (id, gmail_id, thread_id, subject, sender_name, "
              "sender_email, snippet, body_text, body_html, category_id, is_read, is_replied, "
              "ai_classified, received_at) VALUES "
              "(1, 'gid1', 'tid1', 'Asunto', 'Alice', 'alice@example.com', '', '', '', 1, 0, 0, 1, '2026-01-01')"
          )
          await db._db.execute(
              "INSERT INTO gmail_auto_reply_rules (id, name, keywords, description, reply_template, enabled) "
              "VALUES (1, 'Rule A', '[\"test\"]', 'desc', 'Auto-reply text', 1)"
          )
          await db._db.commit()

          engine = _make_engine(db=db)
          email = {"subject": "Asunto", "sender_email": "alice@example.com", "body_text": "test"}
          rule = {"id": 1, "name": "Rule A", "keywords": ["test"],
                  "description": "desc", "reply_template": "Auto-reply text"}
          from openacm.plugins.gmail_classifier.auto_reply_rules import _EvalResult
          result = _EvalResult(matched_rule_id=1, confidence=0.95,
                               is_single_request=True, reasoning="clear")

          with patch(
              "openacm.tools.google_services._get_google_service",
              new_callable=AsyncMock,
          ) as mock_svc:
              mock_service = MagicMock()
              mock_svc.return_value = mock_service
              mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {}
              await engine._send_and_log(email, 1, rule, result)

          cursor = await db._db.execute("SELECT * FROM gmail_auto_reply_log WHERE email_id = 1")
          log_row = await cursor.fetchone()
          assert log_row is not None
          assert log_row["rule_id"] == 1
          assert log_row["confidence"] == 0.95
          assert log_row["reply_body"] == "Auto-reply text"

          cursor2 = await db._db.execute("SELECT is_replied FROM gmail_emails WHERE id = 1")
          email_row = await cursor2.fetchone()
          assert email_row["is_replied"] == 1

      async def test_no_log_row_when_send_fails(self, db):
          await db._db.execute(
              "INSERT INTO gmail_categories (id, name) VALUES (1, 'Test')"
          )
          await db._db.execute(
              "INSERT INTO gmail_emails (id, gmail_id, thread_id, subject, sender_name, "
              "sender_email, snippet, body_text, body_html, category_id, is_read, is_replied, "
              "ai_classified, received_at) VALUES "
              "(2, 'gid2', 'tid2', 'Asunto2', 'Bob', 'bob@example.com', '', '', '', 1, 0, 0, 1, '2026-01-01')"
          )
          await db._db.execute(
              "INSERT INTO gmail_auto_reply_rules (id, name, keywords, description, reply_template, enabled) "
              "VALUES (2, 'Rule B', '[\"test\"]', 'desc', 'Reply', 1)"
          )
          await db._db.commit()

          engine = _make_engine(db=db)
          email = {"subject": "Asunto2", "sender_email": "bob@example.com", "body_text": "test"}
          rule = {"id": 2, "name": "Rule B", "keywords": ["test"],
                  "description": "desc", "reply_template": "Reply"}
          from openacm.plugins.gmail_classifier.auto_reply_rules import _EvalResult
          result = _EvalResult(matched_rule_id=2, confidence=0.95,
                               is_single_request=True, reasoning="ok")

          with patch(
              "openacm.tools.google_services._get_google_service",
              side_effect=RuntimeError("Gmail down"),
          ):
              await engine._send_and_log(email, 2, rule, result)

          cursor = await db._db.execute("SELECT COUNT(*) as cnt FROM gmail_auto_reply_log WHERE email_id = 2")
          row = await cursor.fetchone()
          assert row["cnt"] == 0

          cursor2 = await db._db.execute("SELECT is_replied FROM gmail_emails WHERE id = 2")
          email_row = await cursor2.fetchone()
          assert email_row["is_replied"] == 0
  ```

- [ ] **Step 2: Run send/log tests**

  ```bash
  pytest tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py::TestSendAndLog -v
  ```

  Expected: 2 tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py
  git commit -m "test(gmail): send-and-log tests for AutoReplyRulesEngine"
  ```

---

## Task 5: AutoReplyRulesEngine — evaluate_batch integration

**Files:**
- Modify: `tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py`

- [ ] **Step 1: Add `TestEvaluateBatch` class**

  Append below `TestSendAndLog`:

  ```python
  class TestEvaluateBatch:
      def _mock_llm_response(self, rule_id, confidence, is_single):
          resp = json.dumps({
              "matched_rule_id": rule_id,
              "confidence": confidence,
              "is_single_request": is_single,
              "reasoning": "test",
          })
          llm = MagicMock()
          llm.chat = AsyncMock(return_value=resp)
          return llm

      async def _seed(self, db):
          await db._db.execute("INSERT INTO gmail_categories (id, name) VALUES (1, 'Cat')")
          await db._db.execute(
              "INSERT INTO gmail_emails (id, gmail_id, thread_id, subject, sender_name, "
              "sender_email, snippet, body_text, body_html, category_id, is_read, is_replied, "
              "ai_classified, received_at) VALUES "
              "(10, 'g10', 't10', 'Estado cuenta', 'X', 'x@y.com', '', 'estado de cuenta info', '', 1, 0, 0, 1, '2026-01-01')"
          )
          await db._db.execute(
              "INSERT INTO gmail_auto_reply_rules (id, name, keywords, description, reply_template, enabled) "
              "VALUES (1, 'Rule', '[\"estado de cuenta\"]', 'desc', 'Auto-reply', 1)"
          )
          await db._db.commit()

      async def test_sends_on_high_confidence_single_request(self, db):
          await self._seed(db)
          llm = self._mock_llm_response(rule_id=1, confidence=0.95, is_single=True)
          engine = _make_engine(db=db, llm=llm)
          email = {"gmail_id": "g10", "subject": "Estado cuenta",
                   "body_text": "estado de cuenta info",
                   "sender_email": "x@y.com", "is_replied": 0}

          with patch(
              "openacm.tools.google_services._get_google_service",
              new_callable=AsyncMock,
          ) as mock_svc:
              mock_service = MagicMock()
              mock_svc.return_value = mock_service
              mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {}
              await engine.evaluate_batch([email])

          cursor = await db._db.execute("SELECT COUNT(*) as cnt FROM gmail_auto_reply_log")
          row = await cursor.fetchone()
          assert row["cnt"] == 1

      async def test_skips_low_confidence(self, db):
          await self._seed(db)
          llm = self._mock_llm_response(rule_id=1, confidence=0.75, is_single=True)
          engine = _make_engine(db=db, llm=llm)
          email = {"gmail_id": "g10", "subject": "Estado cuenta",
                   "body_text": "estado de cuenta info",
                   "sender_email": "x@y.com", "is_replied": 0}
          await engine.evaluate_batch([email])
          cursor = await db._db.execute("SELECT COUNT(*) as cnt FROM gmail_auto_reply_log")
          row = await cursor.fetchone()
          assert row["cnt"] == 0

      async def test_skips_multiple_requests(self, db):
          await self._seed(db)
          llm = self._mock_llm_response(rule_id=1, confidence=0.95, is_single=False)
          engine = _make_engine(db=db, llm=llm)
          email = {"gmail_id": "g10", "subject": "Estado cuenta",
                   "body_text": "estado de cuenta info",
                   "sender_email": "x@y.com", "is_replied": 0}
          await engine.evaluate_batch([email])
          cursor = await db._db.execute("SELECT COUNT(*) as cnt FROM gmail_auto_reply_log")
          row = await cursor.fetchone()
          assert row["cnt"] == 0

      async def test_skips_already_replied(self, db):
          await self._seed(db)
          llm = self._mock_llm_response(rule_id=1, confidence=0.95, is_single=True)
          engine = _make_engine(db=db, llm=llm)
          email = {"gmail_id": "g10", "subject": "Estado cuenta",
                   "body_text": "estado de cuenta",
                   "sender_email": "x@y.com", "is_replied": 1}
          await engine.evaluate_batch([email])
          assert llm.chat.call_count == 0  # LLM never called

      async def test_skips_no_keyword_match(self, db):
          await self._seed(db)
          llm = self._mock_llm_response(rule_id=1, confidence=0.95, is_single=True)
          engine = _make_engine(db=db, llm=llm)
          email = {"gmail_id": "g10", "subject": "Hola mundo",
                   "body_text": "sin palabras clave",
                   "sender_email": "x@y.com", "is_replied": 0}
          await engine.evaluate_batch([email])
          assert llm.chat.call_count == 0

      async def test_empty_batch_noop(self, db):
          engine = _make_engine(db=db, llm=MagicMock())
          await engine.evaluate_batch([])  # must not raise
  ```

  Also add to the top of the file:

  ```python
  import json
  ```

- [ ] **Step 2: Run evaluate_batch tests**

  ```bash
  pytest tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py::TestEvaluateBatch -v
  ```

  Expected: 6 tests PASS.

- [ ] **Step 3: Run full test file**

  ```bash
  pytest tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py -v
  ```

  Expected: all 19 tests PASS.

- [ ] **Step 4: Commit**

  ```bash
  git add tests/unit/plugins/gmail_classifier/test_auto_reply_rules.py
  git commit -m "test(gmail): evaluate_batch integration tests for AutoReplyRulesEngine"
  ```

---

## Task 6: Processor — hook evaluate_batch after _upsert

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/processor.py`

- [ ] **Step 1: Add `auto_reply_rules` param to `GmailBatchProcessor.__init__`**

  Find line 168: `def __init__(self, db: Any, llm_router: Any, event_bus: Any):`

  Replace with:

  ```python
  def __init__(self, db: Any, llm_router: Any, event_bus: Any, auto_reply_rules: Any = None):
  ```

  And in the body of `__init__` (after `self._event_bus = event_bus`), add:

  ```python
  self._auto_reply_rules = auto_reply_rules
  ```

- [ ] **Step 2: Call `evaluate_batch` after `_upsert` in the batch loop**

  Find the line `saved = await self._upsert(emails, classifications, categories, force=force)` in the `process()` method.

  Immediately after it, add:

  ```python
  if self._auto_reply_rules:
      try:
          await self._auto_reply_rules.evaluate_batch([e for e, _ in saved])
      except Exception as _exc:
          log.warning("AutoReplyRulesEngine batch failed", error=str(_exc))
  ```

- [ ] **Step 3: Run the full test suite to catch regressions**

  ```bash
  pytest tests/unit/test_gmail_classifier.py -v
  ```

  Expected: all existing tests PASS (the new param defaults to None, changing nothing).

- [ ] **Step 4: Commit**

  ```bash
  git add src/openacm/plugins/gmail_classifier/processor.py
  git commit -m "feat(gmail): hook AutoReplyRulesEngine into processor batch loop"
  ```

---

## Task 7: API — rules CRUD endpoints

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`

- [ ] **Step 1: Add module-level variable and Pydantic model**

  Near the other module-level `_xxx: Any = None` variables (around line 24), add:

  ```python
  _auto_reply_rules: Any = None
  ```

  Near the other `BaseModel` classes, add:

  ```python
  class AutoReplyRuleBody(BaseModel):
      name: str
      keywords: list[str] = Field(default_factory=list)
      description: str
      reply_template: str
      enabled: bool = True
  ```

- [ ] **Step 2: Add the 4 rules endpoints**

  Add after the existing `/settings` endpoints section (or at the end before the attachment helpers):

  ```python
  # ── Auto-reply rules ──────────────────────────────────────────────────

  def _rule_row_to_dict(row) -> dict:
      return {
          "id": row["id"],
          "name": row["name"],
          "keywords": json.loads(row["keywords"] or "[]"),
          "description": row["description"],
          "reply_template": row["reply_template"],
          "enabled": bool(row["enabled"]),
          "created_at": row["created_at"],
      }


  @router.get("/auto-reply-rules")
  async def list_auto_reply_rules():
      db = _require_db()
      cursor = await db._db.execute(
          "SELECT id, name, keywords, description, reply_template, enabled, created_at "
          "FROM gmail_auto_reply_rules ORDER BY created_at DESC"
      )
      rows = await cursor.fetchall()
      return {"items": [_rule_row_to_dict(r) for r in rows]}


  @router.post("/auto-reply-rules")
  async def create_auto_reply_rule(body: AutoReplyRuleBody):
      db = _require_db()
      if not body.name.strip():
          raise HTTPException(status_code=400, detail="name is required")
      if not body.description.strip():
          raise HTTPException(status_code=400, detail="description is required")
      if not body.reply_template.strip():
          raise HTTPException(status_code=400, detail="reply_template is required")
      cursor = await db._db.execute(
          "INSERT INTO gmail_auto_reply_rules "
          "(name, keywords, description, reply_template, enabled) VALUES (?, ?, ?, ?, ?)",
          (body.name.strip(), json.dumps(body.keywords), body.description.strip(),
           body.reply_template.strip(), 1 if body.enabled else 0),
      )
      await db._db.commit()
      row_c = await db._db.execute(
          "SELECT id, name, keywords, description, reply_template, enabled, created_at "
          "FROM gmail_auto_reply_rules WHERE id = ?", (cursor.lastrowid,)
      )
      return _rule_row_to_dict(await row_c.fetchone())


  @router.put("/auto-reply-rules/{rule_id}")
  async def update_auto_reply_rule(rule_id: int, body: AutoReplyRuleBody):
      db = _require_db()
      await db._db.execute(
          "UPDATE gmail_auto_reply_rules "
          "SET name=?, keywords=?, description=?, reply_template=?, enabled=? WHERE id=?",
          (body.name.strip(), json.dumps(body.keywords), body.description.strip(),
           body.reply_template.strip(), 1 if body.enabled else 0, rule_id),
      )
      await db._db.commit()
      row_c = await db._db.execute(
          "SELECT id, name, keywords, description, reply_template, enabled, created_at "
          "FROM gmail_auto_reply_rules WHERE id = ?", (rule_id,)
      )
      row = await row_c.fetchone()
      if not row:
          raise HTTPException(status_code=404, detail="Rule not found")
      return _rule_row_to_dict(row)


  @router.delete("/auto-reply-rules/{rule_id}")
  async def delete_auto_reply_rule(rule_id: int):
      db = _require_db()
      await db._db.execute("DELETE FROM gmail_auto_reply_rules WHERE id = ?", (rule_id,))
      await db._db.commit()
      return {"success": True}
  ```

- [ ] **Step 3: Run tests**

  ```bash
  pytest tests/ -v -k "gmail"
  ```

  Expected: all PASS.

- [ ] **Step 4: Commit**

  ```bash
  git add src/openacm/plugins/gmail_classifier/router.py
  git commit -m "feat(gmail): rules CRUD endpoints (GET/POST/PUT/DELETE /auto-reply-rules)"
  ```

---

## Task 8: API — log endpoint

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`

- [ ] **Step 1: Add the log endpoint** (append after the DELETE rule endpoint)

  ```python
  @router.get("/auto-reply-log")
  async def list_auto_reply_log(
      rule_id: int | None = None,
      limit: int = 50,
      offset: int = 0,
  ):
      db = _require_db()
      base_q = """
          SELECT l.id, l.rule_id, l.email_id, l.confidence, l.reasoning,
                 l.reply_body, l.sent_at,
                 r.name  AS rule_name,
                 e.subject, e.sender_name, e.sender_email, e.snippet
          FROM gmail_auto_reply_log l
          LEFT JOIN gmail_auto_reply_rules r ON r.id = l.rule_id
          LEFT JOIN gmail_emails e ON e.id = l.email_id
      """
      if rule_id is not None:
          cursor = await db._db.execute(
              base_q + " WHERE l.rule_id = ? ORDER BY l.sent_at DESC LIMIT ? OFFSET ?",
              (rule_id, limit, offset),
          )
      else:
          cursor = await db._db.execute(
              base_q + " ORDER BY l.sent_at DESC LIMIT ? OFFSET ?",
              (limit, offset),
          )
      rows = await cursor.fetchall()
      return {"items": [dict(r) for r in rows]}
  ```

- [ ] **Step 2: Run tests**

  ```bash
  pytest tests/ -v -k "gmail"
  ```

  Expected: all PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add src/openacm/plugins/gmail_classifier/router.py
  git commit -m "feat(gmail): GET /auto-reply-log endpoint with rule/email join"
  ```

---

## Task 9: Plugin wiring — instantiate engine and wire to processor + router

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/__init__.py`

- [ ] **Step 1: Import and instantiate the engine**

  Find the block (around line 187) that imports and creates `AutoReplyGenerator`:

  ```python
  from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
  from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager

  auto_reply = AutoReplyGenerator(db=database, llm_router=llm_router)
  learning = ReplyLearningManager(db=database, llm_router=llm_router)
  _router_mod._auto_reply = auto_reply
  _router_mod._learning = learning
  ```

  Add immediately after `_router_mod._learning = learning`:

  ```python
  from openacm.plugins.gmail_classifier.auto_reply_rules import AutoReplyRulesEngine
  auto_reply_rules_engine = AutoReplyRulesEngine(db=database, llm_router=llm_router)
  _router_mod._auto_reply_rules = auto_reply_rules_engine
  ```

- [ ] **Step 2: Pass the engine to the processor constructor**

  Find lines 178-182:

  ```python
  self._processor = _proc_mod.GmailBatchProcessor(
      db=database,
      llm_router=llm_router,
      event_bus=event_bus,
  )
  ```

  Replace with:

  ```python
  self._processor = _proc_mod.GmailBatchProcessor(
      db=database,
      llm_router=llm_router,
      event_bus=event_bus,
      auto_reply_rules=auto_reply_rules_engine,
  )
  ```

  Note: `auto_reply_rules_engine` must be instantiated before this block. Move the import/instantiation to just before the processor creation if needed (the `AutoReplyGenerator` block is already at line 187, which is after the processor at line 178 — swap order so the engine is ready when the processor is created).

  Reorder so the full block looks like:

  ```python
  from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
  from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager
  from openacm.plugins.gmail_classifier.auto_reply_rules import AutoReplyRulesEngine

  auto_reply = AutoReplyGenerator(db=database, llm_router=llm_router)
  learning = ReplyLearningManager(db=database, llm_router=llm_router)
  auto_reply_rules_engine = AutoReplyRulesEngine(db=database, llm_router=llm_router)

  self._processor = _proc_mod.GmailBatchProcessor(
      db=database,
      llm_router=llm_router,
      event_bus=event_bus,
      auto_reply_rules=auto_reply_rules_engine,
  )
  _proc_mod._processor = self._processor
  _router_mod._db = database
  _router_mod._processor = self._processor
  _router_mod._auto_reply = auto_reply
  _router_mod._learning = learning
  _router_mod._auto_reply_rules = auto_reply_rules_engine
  _router_mod._llm_router = llm_router
  _router_mod._event_bus = event_bus
  _router_mod._plugin = self
  ```

- [ ] **Step 3: Run full test suite**

  ```bash
  pytest tests/ -v
  ```

  Expected: all PASS.

- [ ] **Step 4: Commit**

  ```bash
  git add src/openacm/plugins/gmail_classifier/__init__.py
  git commit -m "feat(gmail): wire AutoReplyRulesEngine into plugin startup and processor"
  ```

---

## Task 10: Frontend — AutoReplyRulesPanel component

**Files:**
- Create: `frontend/app/gmail-classifier/components/AutoReplyRulesPanel.tsx`

- [ ] **Step 1: Create the component**

  ```tsx
  'use client'

  import { useState, useEffect, useCallback } from 'react'
  import { X, Plus, Pencil, Trash2, Eye, ToggleLeft, ToggleRight, ChevronDown, ChevronUp } from 'lucide-react'

  interface Rule {
    id: number
    name: string
    keywords: string[]
    description: string
    reply_template: string
    enabled: boolean
    created_at: string
  }

  interface LogEntry {
    id: number
    rule_id: number | null
    email_id: number
    confidence: number
    reasoning: string
    reply_body: string
    sent_at: string
    rule_name: string | null
    subject: string
    sender_name: string
    sender_email: string
    snippet: string
  }

  interface Props {
    token: string
    onClose: () => void
  }

  const EMPTY_FORM = {
    name: '',
    keywords: [] as string[],
    description: '',
    reply_template: '',
    enabled: true,
  }

  export function AutoReplyRulesPanel({ token, onClose }: Props) {
    const [rules, setRules] = useState<Rule[]>([])
    const [log, setLog] = useState<LogEntry[]>([])
    const [editingRule, setEditingRule] = useState<Rule | null>(null)
    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState(EMPTY_FORM)
    const [keywordInput, setKeywordInput] = useState('')
    const [saving, setSaving] = useState(false)
    const [viewEntry, setViewEntry] = useState<LogEntry | null>(null)
    const [logExpanded, setLogExpanded] = useState(true)

    const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

    const loadRules = useCallback(async () => {
      const res = await fetch('/api/gmail-classifier/auto-reply-rules', { headers })
      if (res.ok) {
        const data = await res.json()
        setRules(data.items ?? [])
      }
    }, [token])

    const loadLog = useCallback(async () => {
      const res = await fetch('/api/gmail-classifier/auto-reply-log?limit=30', { headers })
      if (res.ok) {
        const data = await res.json()
        setLog(data.items ?? [])
      }
    }, [token])

    useEffect(() => {
      loadRules()
      loadLog()
    }, [loadRules, loadLog])

    function openCreate() {
      setEditingRule(null)
      setForm(EMPTY_FORM)
      setKeywordInput('')
      setShowForm(true)
    }

    function openEdit(rule: Rule) {
      setEditingRule(rule)
      setForm({
        name: rule.name,
        keywords: rule.keywords,
        description: rule.description,
        reply_template: rule.reply_template,
        enabled: rule.enabled,
      })
      setKeywordInput('')
      setShowForm(true)
    }

    function addKeyword() {
      const kw = keywordInput.trim()
      if (!kw || form.keywords.includes(kw)) return
      setForm(f => ({ ...f, keywords: [...f.keywords, kw] }))
      setKeywordInput('')
    }

    function removeKeyword(kw: string) {
      setForm(f => ({ ...f, keywords: f.keywords.filter(k => k !== kw) }))
    }

    async function saveRule() {
      setSaving(true)
      try {
        const url = editingRule
          ? `/api/gmail-classifier/auto-reply-rules/${editingRule.id}`
          : '/api/gmail-classifier/auto-reply-rules'
        const method = editingRule ? 'PUT' : 'POST'
        const res = await fetch(url, { method, headers, body: JSON.stringify(form) })
        if (res.ok) {
          setShowForm(false)
          await loadRules()
        }
      } finally {
        setSaving(false)
      }
    }

    async function toggleRule(rule: Rule) {
      await fetch(`/api/gmail-classifier/auto-reply-rules/${rule.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ ...rule, enabled: !rule.enabled }),
      })
      await loadRules()
    }

    async function deleteRule(rule: Rule) {
      if (!confirm(`¿Eliminar la regla "${rule.name}"?`)) return
      await fetch(`/api/gmail-classifier/auto-reply-rules/${rule.id}`, { method: 'DELETE', headers })
      await loadRules()
    }

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-[var(--acm-bg)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--acm-border)] flex-shrink-0">
            <span className="text-[13px] font-semibold text-[var(--acm-fg)]">Auto-respuestas</span>
            <button onClick={onClose} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors">
              <X size={16} />
            </button>
          </div>

          <div className="overflow-y-auto acm-scroll flex-1 px-5 py-4 space-y-6">
            {/* Rules */}
            <section>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--acm-fg-4)]">Reglas activas</span>
                <button
                  onClick={openCreate}
                  className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-[var(--acm-radius)] bg-[var(--acm-accent)] text-white hover:opacity-90 transition-opacity"
                >
                  <Plus size={12} /> Nueva regla
                </button>
              </div>

              {rules.length === 0 && !showForm && (
                <p className="text-[12px] text-[var(--acm-fg-4)] italic">Sin reglas configuradas.</p>
              )}

              <div className="space-y-2">
                {rules.map(rule => (
                  <div
                    key={rule.id}
                    className="flex items-start gap-3 p-3 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)]"
                  >
                    <button onClick={() => toggleRule(rule)} className="mt-0.5 flex-shrink-0 text-[var(--acm-accent)]">
                      {rule.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} className="text-[var(--acm-fg-4)]" />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <span className={`text-[12px] font-medium ${rule.enabled ? 'text-[var(--acm-fg)]' : 'text-[var(--acm-fg-4)]'}`}>
                        {rule.name}
                      </span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {rule.keywords.map(kw => (
                          <span
                            key={kw}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--acm-accent)]/10 text-[var(--acm-accent)] border border-[var(--acm-accent)]/20"
                          >
                            {kw}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex gap-1 flex-shrink-0">
                      <button onClick={() => openEdit(rule)} className="p-1 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors">
                        <Pencil size={13} />
                      </button>
                      <button onClick={() => deleteRule(rule)} className="p-1 text-[var(--acm-fg-4)] hover:text-red-400 transition-colors">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Create / Edit Form */}
              {showForm && (
                <div className="mt-3 p-4 bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] space-y-3">
                  <span className="text-[11px] font-semibold text-[var(--acm-fg)]">
                    {editingRule ? 'Editar regla' : 'Nueva regla'}
                  </span>

                  <div>
                    <label className="text-[10px] text-[var(--acm-fg-4)] uppercase tracking-wider">Nombre</label>
                    <input
                      value={form.name}
                      onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                      placeholder="Ej: Solicitudes de apartamento"
                      className="mt-1 w-full bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-3 py-1.5 text-[12px] text-[var(--acm-fg)] outline-none focus:border-[var(--acm-accent)]"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-[var(--acm-fg-4)] uppercase tracking-wider">Keywords (filtro rápido)</label>
                    <div className="flex gap-2 mt-1">
                      <input
                        value={keywordInput}
                        onChange={e => setKeywordInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addKeyword())}
                        placeholder="Escribe y presiona Enter"
                        className="flex-1 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-3 py-1.5 text-[12px] text-[var(--acm-fg)] outline-none focus:border-[var(--acm-accent)]"
                      />
                      <button onClick={addKeyword} className="px-3 py-1.5 text-[11px] bg-[var(--acm-accent)]/10 text-[var(--acm-accent)] rounded-[var(--acm-radius)] hover:bg-[var(--acm-accent)]/20 transition-colors">
                        <Plus size={12} />
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {form.keywords.map(kw => (
                        <span
                          key={kw}
                          className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-[var(--acm-accent)]/10 text-[var(--acm-accent)] border border-[var(--acm-accent)]/20 cursor-pointer hover:bg-red-500/10 hover:text-red-400 hover:border-red-400/20 transition-colors"
                          onClick={() => removeKeyword(kw)}
                        >
                          {kw} <X size={9} />
                        </span>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-[10px] text-[var(--acm-fg-4)] uppercase tracking-wider">
                      Descripción <span className="normal-case">(el LLM usa esto para confirmar si el correo aplica)</span>
                    </label>
                    <textarea
                      value={form.description}
                      onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                      rows={2}
                      placeholder="Ej: El remitente pide un estado de cuenta o información sobre el apartamento"
                      className="mt-1 w-full bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-3 py-1.5 text-[12px] text-[var(--acm-fg)] outline-none focus:border-[var(--acm-accent)] resize-none"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-[var(--acm-fg-4)] uppercase tracking-wider">Respuesta automática</label>
                    <textarea
                      value={form.reply_template}
                      onChange={e => setForm(f => ({ ...f, reply_template: e.target.value }))}
                      rows={4}
                      placeholder="Texto que se enviará automáticamente..."
                      className="mt-1 w-full bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-3 py-1.5 text-[12px] text-[var(--acm-fg)] outline-none focus:border-[var(--acm-accent)] resize-none"
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="rule-enabled"
                      checked={form.enabled}
                      onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
                    />
                    <label htmlFor="rule-enabled" className="text-[12px] text-[var(--acm-fg-2)]">Activa</label>
                  </div>

                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={saveRule}
                      disabled={saving || !form.name.trim() || !form.description.trim() || !form.reply_template.trim()}
                      className="px-3 py-1.5 text-[11px] bg-[var(--acm-accent)] text-white rounded-[var(--acm-radius)] hover:opacity-90 transition-opacity disabled:opacity-40"
                    >
                      {saving ? 'Guardando…' : 'Guardar'}
                    </button>
                    <button
                      onClick={() => setShowForm(false)}
                      className="px-3 py-1.5 text-[11px] bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-2)] rounded-[var(--acm-radius)] hover:border-[var(--acm-accent)] transition-colors"
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </section>

            {/* Log */}
            <section>
              <button
                onClick={() => setLogExpanded(v => !v)}
                className="flex items-center gap-2 w-full text-left mb-3"
              >
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--acm-fg-4)]">
                  Historial de auto-respuestas
                </span>
                {logExpanded ? <ChevronUp size={13} className="text-[var(--acm-fg-4)]" /> : <ChevronDown size={13} className="text-[var(--acm-fg-4)]" />}
              </button>

              {logExpanded && (
                log.length === 0
                  ? <p className="text-[12px] text-[var(--acm-fg-4)] italic">Sin auto-respuestas enviadas aún.</p>
                  : (
                    <div className="border border-[var(--acm-border)] rounded-[var(--acm-radius)] overflow-hidden">
                      <table className="w-full text-[11px]">
                        <thead>
                          <tr className="bg-[var(--acm-elev)] border-b border-[var(--acm-border)]">
                            <th className="text-left px-3 py-2 text-[var(--acm-fg-4)] font-medium">Fecha</th>
                            <th className="text-left px-3 py-2 text-[var(--acm-fg-4)] font-medium">Asunto</th>
                            <th className="text-left px-3 py-2 text-[var(--acm-fg-4)] font-medium">Regla</th>
                            <th className="text-right px-3 py-2 text-[var(--acm-fg-4)] font-medium">Conf.</th>
                            <th className="px-3 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {log.map(entry => (
                            <tr key={entry.id} className="border-b border-[var(--acm-border)] last:border-0 hover:bg-[var(--acm-elev)] transition-colors">
                              <td className="px-3 py-2 text-[var(--acm-fg-4)] whitespace-nowrap">
                                {new Date(entry.sent_at).toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' })}
                              </td>
                              <td className="px-3 py-2 text-[var(--acm-fg-2)] max-w-[160px] truncate">{entry.subject}</td>
                              <td className="px-3 py-2 text-[var(--acm-fg-2)]">{entry.rule_name ?? 'Regla eliminada'}</td>
                              <td className="px-3 py-2 text-right">
                                <span className={`font-medium ${entry.confidence >= 0.95 ? 'text-green-400' : 'text-yellow-400'}`}>
                                  {Math.round(entry.confidence * 100)}%
                                </span>
                              </td>
                              <td className="px-3 py-2">
                                <button
                                  onClick={() => setViewEntry(entry)}
                                  className="text-[var(--acm-fg-4)] hover:text-[var(--acm-accent)] transition-colors"
                                >
                                  <Eye size={13} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
              )}
            </section>
          </div>
        </div>

        {/* Detail modal */}
        {viewEntry && (
          <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60" onClick={() => setViewEntry(null)}>
            <div
              className="bg-[var(--acm-bg)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-lg p-5 space-y-3 shadow-2xl"
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-semibold text-[var(--acm-fg)]">Detalle auto-respuesta</span>
                <button onClick={() => setViewEntry(null)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)]"><X size={14} /></button>
              </div>
              <div className="space-y-2 text-[12px]">
                <div><span className="text-[var(--acm-fg-4)]">De: </span><span className="text-[var(--acm-fg)]">{viewEntry.sender_name} &lt;{viewEntry.sender_email}&gt;</span></div>
                <div><span className="text-[var(--acm-fg-4)]">Asunto: </span><span className="text-[var(--acm-fg)]">{viewEntry.subject}</span></div>
                <div><span className="text-[var(--acm-fg-4)]">Regla: </span><span className="text-[var(--acm-fg)]">{viewEntry.rule_name ?? 'Eliminada'}</span></div>
                <div><span className="text-[var(--acm-fg-4)]">Confianza: </span><span className="text-[var(--acm-fg)] font-medium">{Math.round(viewEntry.confidence * 100)}%</span></div>
                {viewEntry.reasoning && (
                  <div><span className="text-[var(--acm-fg-4)]">Razonamiento: </span><span className="text-[var(--acm-fg-2)] italic">{viewEntry.reasoning}</span></div>
                )}
                <div className="pt-2">
                  <span className="text-[10px] text-[var(--acm-fg-4)] uppercase tracking-wider">Respuesta enviada</span>
                  <div className="mt-1 p-3 bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] text-[var(--acm-fg-2)] whitespace-pre-wrap">
                    {viewEntry.reply_body}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add frontend/app/gmail-classifier/components/AutoReplyRulesPanel.tsx
  git commit -m "feat(gmail): AutoReplyRulesPanel component — rules CRUD + log table + detail modal"
  ```

---

## Task 11: Frontend — wire panel into Gmail Classifier page

**Files:**
- Modify: `frontend/app/gmail-classifier/page.tsx`

- [ ] **Step 1: Import the panel and add state**

  At the top imports (around line 11, with the other component imports):

  ```tsx
  import { AutoReplyRulesPanel } from './components/AutoReplyRulesPanel';
  ```

  After `const [showSettings, setShowSettings] = useState(false);` (around line 145):

  ```tsx
  const [showAutoReplyRules, setShowAutoReplyRules] = useState(false);
  ```

- [ ] **Step 2: Add toolbar button**

  Find the button that triggers `setShowSettings(true)` (around line 477). Add a sibling button immediately before or after it:

  ```tsx
  <button
    onClick={() => setShowAutoReplyRules(true)}
    title="Auto-respuestas"
    className="flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-[var(--acm-radius)] bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-2)] hover:border-[var(--acm-accent)] hover:text-[var(--acm-fg)] transition-colors"
  >
    <Sparkles size={13} />
    Auto-respuestas
  </button>
  ```

  (`Sparkles` is already imported on line 4.)

- [ ] **Step 3: Render the panel**

  After the `{showSettings && <PluginSettings ... />}` block (around line 597), add:

  ```tsx
  {showAutoReplyRules && (
    <AutoReplyRulesPanel
      token={token ?? ''}
      onClose={() => setShowAutoReplyRules(false)}
    />
  )}
  ```

- [ ] **Step 4: Build and verify**

  ```bash
  cd frontend && npm run build
  ```

  Expected: build succeeds with no type errors.

- [ ] **Step 5: Run full backend tests one last time**

  ```bash
  cd .. && pytest tests/ -v
  ```

  Expected: all PASS.

- [ ] **Step 6: Final commit**

  ```bash
  git add frontend/app/gmail-classifier/page.tsx
  git commit -m "feat(gmail): wire AutoReplyRulesPanel into Gmail Classifier page"
  ```

---

## Summary

| Task | What it delivers |
|------|-----------------|
| 1 | DB migration — two new tables |
| 2 | Engine + keyword filter (tested) |
| 3 | LLM eval with confidence threshold (tested) |
| 4 | Send via Gmail API + log/mark replied (tested) |
| 5 | evaluate_batch full flow (tested) |
| 6 | Processor wired to engine |
| 7 | Rules CRUD API (5 endpoints) |
| 8 | Log API endpoint |
| 9 | Plugin startup wiring |
| 10 | UI panel — rules list, CRUD form, log table, detail modal |
| 11 | Panel button in Gmail Classifier page |
