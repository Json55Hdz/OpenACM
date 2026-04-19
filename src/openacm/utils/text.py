def truncate(text: str, max_len: int, suffix: str = "...[truncated]") -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + suffix
