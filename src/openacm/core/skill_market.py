"""
Skill marketplace: find, read, check and install skills made by other people.

A skill is a Markdown document the assistant reads as instructions. It cannot run code by itself,
but it DOES steer the assistant, so a hostile one could try to talk it into leaking data or running
commands. Installing therefore always goes through three steps the owner sees:

1. fetch - only from https hosts on an allow list, no redirects, size capped, optional SHA-256 pin;
2. check - a reading aid that flags the usual tricks (override phrases, hidden characters, pipes to a
   shell, data leaving the machine); it never decides on its own;
3. approve - the owner reads the full text and confirms; a skill with serious findings also needs its
   name typed.

Anyone can publish: open a pull request adding a ``.md`` file to ``marketplace/skills`` and running
``python marketplace/build_index.py``, or just share a raw GitHub link and install it by URL.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger()

DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/Json55Hdz/OpenACM/main/marketplace/skills/index.json"
ALLOWED_HOSTS = ("raw.githubusercontent.com", "gist.githubusercontent.com")
MAX_SKILL_BYTES = 60_000
MAX_CATALOG_BYTES = 1_000_000
FETCH_TIMEOUT_S = 15

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,59}$")
CATEGORY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")


class MarketError(ValueError):
    """The skill or the catalog cannot be used (message is safe to show)."""


@dataclass
class ParsedSkill:
    name: str
    description: str
    category: str
    content: str
    author: str = ""
    sha256: str = ""
    findings: list[dict[str, str]] = field(default_factory=list)
    raw: str = ""  # the whole file as read, front matter included: what install receives back

    @property
    def risky(self) -> bool:
        return any(f["level"] == "high" for f in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "description": self.description, "category": self.category,
            "author": self.author, "content": self.content, "sha256": self.sha256,
            "findings": self.findings, "risky": self.risky, "raw": self.raw, "size": len(self.content.encode("utf-8")),
        }


# ── reading aid ──────────────────────────────────────────────────────────────

_CHECKS: list[tuple[str, str, str]] = [
    ("high", r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)|ignora (todas )?las instrucciones anteriores",
     "Intenta anular las instrucciones del asistente."),
    ("high", r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b|powershell[^\n]*-enc(odedcommand)?\b|iex\s*\(",
     "Descarga y ejecuta código directamente."),
    ("high", r"(send|upload|post|exfiltrate|envía|envia|sube)[^\n]{0,60}(api[_ -]?key|token|password|contraseñ|\.env|id_rsa|credentials|secret)",
     "Pide enviar claves, contraseñas o secretos a algún sitio."),
    ("high", r"do not (tell|inform|show)[^\n]{0,30}(user|owner)|no (le )?(digas|avises|muestres)[^\n]{0,30}(al )?(usuario|dueño)",
     "Pide ocultarle cosas al propietario."),
    ("high", r"rm\s+-rf\s+(/|~|\$HOME)|format\s+[a-z]:|mkfs\.|dd\s+if=.*of=/dev/",
     "Contiene comandos destructivos."),
    ("warn", r"https?://(?!(github\.com|raw\.githubusercontent\.com|docs\.|developer\.))\S+",
     "Menciona direcciones web externas: revisa a dónde apuntan."),
    ("warn", r"\b(sudo|chmod\s+777|chown\s+-R|reg add|schtasks|crontab)\b",
     "Incluye comandos con privilegios o que cambian el sistema."),
    ("warn", r"base64\s+(-d|--decode)|atob\(|fromCharCode",
     "Contiene texto codificado que oculta su contenido."),
]
_HIDDEN = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")


def scan(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if _HIDDEN.search(text):
        out.append({"level": "high", "message": "Tiene caracteres invisibles o que invierten el texto: pueden esconder instrucciones."})
    for level, pattern, message in _CHECKS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            snippet = text[max(0, m.start() - 30): m.end() + 30].replace("\n", " ")
            out.append({"level": level, "message": message, "snippet": snippet[:160]})
    return out


# ── parsing ──────────────────────────────────────────────────────────────────

def parse_skill(text: str, expected_sha: str | None = None) -> ParsedSkill:
    raw = text.replace("\r\n", "\n")
    data = raw.encode("utf-8")
    if len(data) > MAX_SKILL_BYTES:
        raise MarketError(f"La skill pesa {len(data) // 1000} KB; el máximo es {MAX_SKILL_BYTES // 1000} KB.")
    if "\x00" in raw:
        raise MarketError("El archivo no es texto.")
    sha = hashlib.sha256(text.encode("utf-8") if "\r\n" not in text else data).hexdigest()
    if expected_sha and sha.lower() != expected_sha.lower():
        raise MarketError("El contenido no coincide con el que anuncia el marketplace (SHA-256 distinto).")

    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    if not m:
        raise MarketError("Falta el encabezado «---» con name y description al inicio del archivo.")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    name = meta.get("name", "")
    if not NAME_RE.match(name):
        raise MarketError("name debe usar solo minúsculas, números, guiones y guion bajo (2 a 60 caracteres).")
    description = meta.get("description", "").strip()
    if not description:
        raise MarketError("Falta la description.")
    category = meta.get("category", "community")
    if not CATEGORY_RE.match(category):
        category = "community"
    body = m.group(2).strip()
    if len(body) < 40:
        raise MarketError("La skill casi no tiene contenido.")
    description = description.replace('"', "'")
    return ParsedSkill(
        name=name, description=description[:500], category=category, content=body,
        author=meta.get("author", "")[:80], sha256=sha, findings=scan(raw), raw=raw,
    )


# ── fetching ─────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """A github.com/…/blob/… page link becomes its raw file link."""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/(.+)$", url.strip())
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else url.strip()


def check_url(url: str) -> str:
    url = _normalize_url(url)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise MarketError(
            "Solo se instala desde enlaces https de GitHub (raw.githubusercontent.com o gist). "
            "Para otra fuente, pega el contenido del archivo."
        )
    return url


async def _get(url: str, limit: int) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise MarketError(f"No se pudo descargar (HTTP {resp.status_code}).")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if len(buf) > limit:
                        raise MarketError("El archivo es demasiado grande.")
                return bytes(buf)
    except httpx.HTTPError as exc:
        raise MarketError(f"No se pudo descargar: {type(exc).__name__}.") from exc


async def fetch_skill(url: str, sha256: str | None = None) -> ParsedSkill:
    data = await _get(check_url(url), MAX_SKILL_BYTES + 1)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MarketError("El archivo no es texto UTF-8.") from exc
    return parse_skill(text, expected_sha=sha256)


async def fetch_catalog(url: str = DEFAULT_CATALOG_URL) -> list[dict[str, Any]]:
    data = await _get(check_url(url), MAX_CATALOG_BYTES)
    try:
        doc = json.loads(data)
        items = doc["skills"] if isinstance(doc, dict) else doc
    except (ValueError, KeyError) as exc:
        raise MarketError("El catálogo no tiene el formato esperado.") from exc
    clean: list[dict[str, Any]] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        name, link = str(it.get("name", "")), str(it.get("url", ""))
        if not NAME_RE.match(name):
            continue
        try:
            check_url(link)
        except MarketError:
            continue  # an entry pointing outside the allowed hosts is dropped, not trusted
        clean.append({
            "name": name,
            "description": str(it.get("description", ""))[:500],
            "category": str(it.get("category", "community"))[:30],
            "author": str(it.get("author", "community"))[:80],
            "url": _normalize_url(link),
            "sha256": str(it.get("sha256", ""))[:64],
            "size": int(it.get("size", 0) or 0),
        })
    return clean
