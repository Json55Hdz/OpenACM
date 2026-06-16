"""Tests for knowledge_file text extractor."""
import pytest
from unittest.mock import patch, MagicMock


class TestExtractText:
    async def test_plain_text_file(self):
        from openacm.utils.knowledge_file import extract_text
        result = await extract_text("notes.txt", b"Hello world")
        assert result == "Hello world"

    async def test_markdown_file(self):
        from openacm.utils.knowledge_file import extract_text
        result = await extract_text("readme.md", b"# Title\n\nContent here")
        assert result == "# Title\n\nContent here"

    async def test_csv_file(self):
        from openacm.utils.knowledge_file import extract_text
        result = await extract_text("data.csv", b"a,b,c\n1,2,3")
        assert result == "a,b,c\n1,2,3"

    async def test_json_file(self):
        from openacm.utils.knowledge_file import extract_text
        result = await extract_text("config.json", b'{"key": "value"}')
        assert result == '{"key": "value"}'

    async def test_binary_file_uses_markitdown(self):
        from openacm.utils.knowledge_file import extract_text

        with patch("openacm.utils.knowledge_file._convert_with_markitdown") as mock_conv:
            mock_conv.return_value = "Extracted PDF content"
            result = await extract_text("doc.pdf", b"%PDF-fake")
        assert result == "Extracted PDF content"

    async def test_unsupported_extension_uses_markitdown(self):
        from openacm.utils.knowledge_file import extract_text

        with patch("openacm.utils.knowledge_file._convert_with_markitdown") as mock_conv:
            mock_conv.return_value = "some content"
            result = await extract_text("file.docx", b"PK fake docx bytes")
        assert result == "some content"

    async def test_utf8_decoding_with_replacement(self):
        from openacm.utils.knowledge_file import extract_text
        # Invalid UTF-8 bytes should not raise, use replacement char
        result = await extract_text("file.txt", b"Hello \xff world")
        assert "Hello" in result
        assert "world" in result
