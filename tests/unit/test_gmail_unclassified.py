"""An email the classifier could not answer for must be retried, not filed under 'Otros' forever."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from openacm.plugins.gmail_classifier.processor import GmailBatchProcessor


async def test_emails_without_a_classification_are_not_saved():
    proc = GmailBatchProcessor.__new__(GmailBatchProcessor)
    execute = AsyncMock()
    proc._db = SimpleNamespace(_db=SimpleNamespace(execute=execute, commit=AsyncMock()))
    emails = [{"gmail_id": "g1", "thread_id": "t", "subject": "s", "sender_name": "n", "sender_email": "e",
               "snippet": "", "is_read": 0, "is_replied": 0, "received_at": "2026-01-01"}]
    saved = await proc._upsert(emails, {}, [{"id": 1, "name": "Otros"}])
    assert saved == []
    execute.assert_not_awaited()
