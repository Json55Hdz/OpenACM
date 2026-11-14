"""
Install a pip-installable OpenACM plugin from a public GitHub repository.

Installing a plugin means running someone else's code with the same access OpenACM
has, so this module is deliberately narrow:

- the only accepted source is ``https://github.com/<owner>/<repo>`` (nothing else is
  ever handed to the package installer, so no flags, local paths or other hosts);
- the repository is fetched as GitHub's source archive, so ``git`` is not needed;
- the caller (the dashboard) is responsible for asking the user to confirm first.

The new plugin is picked up through the ``openacm.plugins`` entry point group on the
next start of OpenACM.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys

import structlog

from openacm.core import messages as M
from openacm.plugins import plugins_dir

log = structlog.get_logger()

INSTALL_TIMEOUT_SECONDS = 900
_OUTPUT_TAIL_CHARS = 4000

# GitHub: owner is alphanumeric with inner hyphens (max 39); repo is letters, digits, . _ -
_SOURCE_RE = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100})$"
)

_lock = asyncio.Lock()


class PluginInstallError(Exception):
    """The install could not be started or the installer reported a failure."""

    def __init__(self, message: str, output: str = "", status: int = 400):
        super().__init__(message)
        self.output = output
        self.status = status


def parse_source(source: str) -> tuple[str, str]:
    """Return (owner, repo) for a GitHub repository URL, or raise PluginInstallError."""
    text = str(source or "").strip()
    if text.endswith("/"):
        text = text[:-1]
    if text.endswith(".git"):
        text = text[:-4]
    match = _SOURCE_RE.match(text)
    if not match or match["repo"] in {".", ".."}:
        raise PluginInstallError(M.MSG_PLUGIN_INSTALL_BAD_SOURCE)
    return match["owner"], match["repo"]


def archive_url(owner: str, repo: str) -> str:
    """Source archive of the default branch (no git needed)."""
    return f"https://github.com/{owner}/{repo}/archive/HEAD.zip"


def installer_command(url: str) -> list[str]:
    """Install into the interpreter OpenACM is running on (uv if present, else pip).

    When OPENACM_PLUGINS_DIR is set (Docker), the plugin goes into that folder instead,
    so it survives the container being rebuilt.
    """
    target = plugins_dir()
    where = ["--target", str(target), "--upgrade"] if target else []
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable, *where, url]
    return [sys.executable, "-m", "pip", "install", *where, url]


async def install_plugin(source: str, timeout: float = INSTALL_TIMEOUT_SECONDS) -> dict:
    """Install the plugin at `source`. Returns {source, package_url, output}."""
    owner, repo = parse_source(source)
    url = archive_url(owner, repo)
    if _lock.locked():
        raise PluginInstallError(M.MSG_PLUGIN_INSTALL_BUSY, status=409)

    async with _lock:
        target = plugins_dir()
        if target:
            target.mkdir(parents=True, exist_ok=True)
        cmd = installer_command(url)
        log.info("plugin.install.start", owner=owner, repo=repo, installer=cmd[0])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise PluginInstallError(
                M.MSG_PLUGIN_INSTALL_FAILED, output=str(exc), status=500
            ) from exc
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise PluginInstallError(M.MSG_PLUGIN_INSTALL_TIMEOUT, status=504) from exc

        output = raw.decode("utf-8", errors="replace")[-_OUTPUT_TAIL_CHARS:]
        if proc.returncode != 0:
            log.warning("plugin.install.failed", owner=owner, repo=repo, code=proc.returncode)
            raise PluginInstallError(M.MSG_PLUGIN_INSTALL_FAILED, output=output, status=500)

        log.info("plugin.install.done", owner=owner, repo=repo)
        return {
            "source": f"https://github.com/{owner}/{repo}",
            "package_url": url,
            "output": output,
        }
