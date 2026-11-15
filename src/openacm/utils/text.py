import re


# An agent writes this marker where its reply should be cut into separate chat messages.
MESSAGE_SPLIT_MARKER = "<<MSG>>"
MESSAGE_GAP_SECONDS = 0.7  # pause between the parts of a split reply, keeps delivery order


def split_message_parts(text: str) -> list[str]:
    """Split a reply on MESSAGE_SPLIT_MARKER into non-empty, trimmed messages."""
    return [part.strip() for part in text.split(MESSAGE_SPLIT_MARKER) if part.strip()]


def join_message_parts(text: str) -> str:
    """For channels that cannot send several messages: replace the marker with a blank line."""
    return "\n\n".join(split_message_parts(text)) if MESSAGE_SPLIT_MARKER in text else text


SECRET_KEY_PARTS = ("token", "secret", "api_key", "apikey", "password", "passwd", "private_key", "credential")


def mask_secrets(value):
    """Copy of a config-like structure with every secret value replaced by '***'.

    A key counts as secret when its name contains token, secret, api_key, password... Empty
    values stay empty, so the UI can still tell "not set" from "set".
    """
    if isinstance(value, dict):
        return {
            k: ("***" if isinstance(k, str) and any(p in k.lower() for p in SECRET_KEY_PARTS)
                and isinstance(v, str) and v else mask_secrets(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    return value


CUSTOMER_NAME_MAX_CHARS = 40


def sanitize_customer_name(name: str) -> str:
    """A customer's name, safe to show to the model: letters, spaces, apostrophes, dots, hyphens.

    The customer types it themselves and it goes into the agent's prompt on every turn, so
    line breaks, symbols and long text (which could carry instructions) are removed.
    """
    import re

    cleaned = re.sub(r"[^\w .'’-]|[\d_]", "", str(name or ""))
    return " ".join(cleaned.split())[:CUSTOMER_NAME_MAX_CHARS].strip()


def chunk_text(text: str, limit: int) -> list[str]:
    """Split a long message into pieces of at most `limit` characters, nothing lost.

    Chat platforms refuse (or silently cut) messages over their size limit, so a long reply
    has to go out as several messages. Pieces break at a paragraph, then a line, then a space;
    only text with no break point at all is cut in the middle of a word.
    """
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut < limit // 2:  # no sensible break in the second half: fall back to the limit
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def truncate(text: str, max_len: int, suffix: str = "...[truncated]") -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + suffix


def extract_and_strip_thinking(content: str, existing_reasoning: str = "") -> tuple[str, str]:
    """Extract reasoning/thinking from model output content and strip all thinking tags and blocks.

    Handles:
    - Standard closed blocks: `<think>...</think>` or `<thinking>...</thinking>`
    - Orphan closing tags (prefilled prompt template): `draft thoughts...</think>real response`
    - Orphan opening tags (unfinished/truncated thinking): `<think>thoughts without end`
    - Rogue leftover tags: `<think>`, `</think>`, `<thinking>`, `</thinking>`
    - Preserves and aggregates any `existing_reasoning` passed in.

    Returns:
        tuple[clean_content, reasoning_text]
    """
    if not content:
        return "", (existing_reasoning or "").strip()

    extracted_parts: list[str] = []
    if existing_reasoning and existing_reasoning.strip():
        extracted_parts.append(existing_reasoning.strip())

    text = content

    # 1. Extract and remove closed <think>...</think> or <thinking>...</thinking> blocks
    closed_pattern = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
    for m in closed_pattern.finditer(text):
        inner = m.group(1).strip()
        if inner:
            extracted_parts.append(inner)
    text = closed_pattern.sub("", text)

    # 2. Check for orphan closing tags </think> or </thinking>
    # When the model provider prefilled `<think>` in the assistant prompt prefix,
    # the completion stream starts directly with reasoning and ends with `</think>`.
    # Everything before the `</think>` is reasoning.
    while True:
        orphan_close = re.search(r"^(.*?)</think(?:ing)?>\s*", text, re.DOTALL | re.IGNORECASE)
        if not orphan_close:
            break
        inner = orphan_close.group(1).strip()
        if inner:
            extracted_parts.append(inner)
        text = text[orphan_close.end():]

    # 3. Check for orphan opening tag <think> or <thinking> with no closing tag (truncated)
    orphan_open = re.search(r"<think(?:ing)?>(.*)$", text, re.DOTALL | re.IGNORECASE)
    if orphan_open:
        inner = orphan_open.group(1).strip()
        if inner:
            extracted_parts.append(inner)
        text = text[:orphan_open.start()]

    # 4. Remove any rogue leftover think tags
    text = re.sub(r"</?think(?:ing)?>", "", text, flags=re.IGNORECASE).strip()

    final_reasoning = "\n\n".join(extracted_parts).strip()
    return text, final_reasoning
