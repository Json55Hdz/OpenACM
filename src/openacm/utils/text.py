import re


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
