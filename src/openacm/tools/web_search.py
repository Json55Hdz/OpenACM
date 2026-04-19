"""
Web Search Tool — search the internet using DuckDuckGo.
No API key required.
"""

from openacm.tools.base import tool


@tool(
    name="web_search",
    description=(
        "Search the internet for information using DuckDuckGo. "
        "Returns relevant search results with titles, URLs, and snippets. "
        "Use this when you need current information or to look something up."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    risk_level="medium",
    category="web",
)
async def web_search(query: str, max_results: int = 5, **kwargs) -> str:
    """Search the web using DuckDuckGo."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            # Fallback to old import for backwards compatibility
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return f"No results found for: {query}"

        output_lines = [f"🔍 Search results for: {query}\n"]
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            url = result.get("href", result.get("link", ""))
            snippet = result.get("body", result.get("snippet", ""))
            output_lines.append(f"{i}. **{title}**")
            output_lines.append(f"   {url}")
            if snippet:
                output_lines.append(f"   {snippet}")
            output_lines.append("")

        return "\n".join(output_lines)
    except ImportError:
        return "Error: duckduckgo-search package not installed"
    except Exception as e:
        return f"Error searching the web: {str(e)}"


@tool(
    name="get_webpage",
    description=(
        "Fetch and read the text content of a webpage URL. "
        "Returns the main text content, stripped of HTML tags."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the webpage to read",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return (default: 5000)",
                "default": 5000,
            },
        },
        "required": ["url"],
    },
    risk_level="medium",
    category="web",
)
async def get_webpage(url: str, max_length: int = 5000, **kwargs) -> str:
    """Fetch and read a webpage."""
    try:
        import httpx
        import re

        # SECURITY: POR DISEÑO - HTTP client para búsqueda web
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; OpenACM/0.1)"}
            )
            response.raise_for_status()
            html = response.text

        # HTML → plain text via stdlib parser (safe, no regex bypass vectors)
        from html.parser import HTMLParser

        class _TextExtractor(HTMLParser):
            SKIP_TAGS = {"script", "style", "head", "noscript", "template"}

            def __init__(self):
                super().__init__(convert_charrefs=True)
                self._parts: list[str] = []
                self._skip: int = 0

            def handle_starttag(self, tag, attrs):
                if tag in self.SKIP_TAGS:
                    self._skip += 1

            def handle_endtag(self, tag):
                if tag in self.SKIP_TAGS and self._skip:
                    self._skip -= 1

            def handle_data(self, data):
                if not self._skip:
                    self._parts.append(data)

            def get_text(self):
                return " ".join(self._parts)

        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > max_length:
            text = text[:max_length] + "\n\n[... content truncated]"

        return f"📄 Content from {url}:\n\n{text}"
    except Exception as e:
        return f"Error fetching webpage: {str(e)}"
