"""Rebuild marketplace/skills/index.json from the skill files next to it.

    python marketplace/build_index.py

Every skill is one .md file with a frontmatter block (name, description, category, author).
The index lists them with the SHA-256 of the exact file, which OpenACM checks before installing.
"""
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).parent / "skills"
RAW = "https://raw.githubusercontent.com/Json55Hdz/OpenACM/main/marketplace/skills/"


def frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    out: dict[str, str] = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


entries = []
for path in sorted(BASE.glob("*.md")):
    data = path.read_bytes()
    fm = frontmatter(data.decode("utf-8").replace("\r\n", "\n"))
    entries.append({
        "name": fm.get("name") or path.stem,
        "description": fm.get("description", ""),
        "category": fm.get("category", "general"),
        "author": fm.get("author", "community"),
        "url": RAW + path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    })

(BASE / "index.json").write_text(json.dumps({"version": 1, "skills": entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(entries)} skills indexed")
