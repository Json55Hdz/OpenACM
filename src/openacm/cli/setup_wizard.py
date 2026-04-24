#!/usr/bin/env python3
"""
OpenACM CLI Setup Wizard
Configure the agent fully from the console, no browser required.

Usage:
  openacm-setup           → main menu (direct access to any section)
  openacm-setup --guided  → step-by-step guided setup with next/back navigation
  openacm-setup -g        → same as --guided
"""

from __future__ import annotations

import json
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from dotenv import dotenv_values, set_key
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table

console = Console()

# ─── Nav ──────────────────────────────────────────────────────────────────────

NEXT = "next"
PREV = "prev"
MENU = "menu"


# ─── Paths ────────────────────────────────────────────────────────────────────


def _find_root() -> Path:
    current = Path.cwd()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


ROOT = _find_root()
ENV_PATH = ROOT / "config" / ".env"
LOCAL_YAML = ROOT / "config" / "local.yaml"
DEFAULT_YAML = ROOT / "config" / "default.yaml"
CUSTOM_PROVIDERS_PATH = ROOT / "config" / "custom_providers.json"
DEBUG_MODE_FILE = ROOT / "data" / "debug_mode"


# ─── Config helpers ───────────────────────────────────────────────────────────


def read_env() -> dict[str, str]:
    if ENV_PATH.exists():
        return {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}
    return {}


def write_env(key: str, value: str) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), key, value)


def read_local() -> dict:
    if LOCAL_YAML.exists():
        return yaml.safe_load(LOCAL_YAML.read_text(encoding="utf-8")) or {}
    return {}


def write_local(data: dict) -> None:
    LOCAL_YAML.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_YAML.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def read_custom_providers() -> list[dict]:
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            return json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def write_custom_providers(providers: list[dict]) -> None:
    CUSTOM_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(providers, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ─── UI helpers ───────────────────────────────────────────────────────────────


def is_real_key(value: str | None) -> bool:
    if not value:
        return False
    return (
        value.strip().lower() not in {"", "your_key_here", "xxx", "placeholder"}
        and len(value.strip()) > 5
    )


def ok(flag: bool) -> str:
    return "[green]✓[/green]" if flag else "[red]✗[/red]"


def header(title: str, subtitle: str = "") -> None:
    console.clear()
    sub = f"\n[dim]{subtitle}[/dim]" if subtitle else ""
    console.print(Panel(
        f"[bold cyan]OpenACM Setup[/bold cyan]  [dim]>[/dim]  [bold]{title}[/bold]{sub}",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()


def nav_prompt(sequential: bool) -> str:
    """Show navigation footer and return NEXT / PREV / MENU."""
    console.print()
    console.print(Rule(style="dim"))
    if sequential:
        console.print(
            "  [cyan][N][/cyan] Next  "
            "[cyan][P][/cyan] Previous  "
            "[cyan][M][/cyan] Main menu\n"
        )
        choice = Prompt.ask("  Navigate", default="n", show_default=False).strip().lower()
        if choice == "p":
            return PREV
        if choice == "m":
            return MENU
        return NEXT
    else:
        Prompt.ask("  [dim]Press Enter to go back[/dim]", default="", show_default=False)
        return MENU


def input_or_skip(prompt: str, current: str = "", secret: bool = False) -> str | None:
    """
    Prompt for a value.
      Enter alone -> keep current (returns None)
      'x'         -> clear/delete (returns '')
      anything    -> new value
    """
    hint = f" [dim](current: {'***' + current[-4:] if secret and current else current or '-'})[/dim]"
    val = Prompt.ask(f"  {prompt}{hint}", default="", show_default=False)
    if val.strip() == "":
        return None
    if val.strip().lower() == "x":
        return ""
    return val.strip()


# ─── Status ───────────────────────────────────────────────────────────────────

BUILTIN_PROVIDERS = [
    ("openai",      "OpenAI",         "OPENAI_API_KEY"),
    ("anthropic",   "Anthropic",      "ANTHROPIC_API_KEY"),
    ("gemini",      "Google Gemini",  "GEMINI_API_KEY"),
    ("xai",         "xAI (Grok)",     "XAI_API_KEY"),
    ("openrouter",  "OpenRouter",     "OPENROUTER_API_KEY"),
    ("opencode_go", "OpenCode.GO",    "OPENCODE_GO_API_KEY"),
    ("ollama",      "Ollama (local)", None),
]

PROVIDER_MODELS: dict[str, list[str]] = {
    "openai":      ["gpt-4o", "gpt-4o-mini", "o3", "o4-mini"],
    "anthropic":   ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "gemini":      ["gemini-2.5-pro", "gemini-2.5-flash"],
    "xai":         ["grok-4.20-0309-non-reasoning", "grok-3"],
    "openrouter":  ["openrouter/auto"],
    "opencode_go": ["kimi-k2.5", "kimi-k1.5"],
    "ollama":      ["llama3.2", "llama3.1", "mistral", "phi4"],
}


def get_status() -> dict:
    env = read_env()
    local = read_local()
    profile = local.get("A", {})
    configured_providers = sum(
        1 for _, _, key in BUILTIN_PROVIDERS
        if key is None or is_real_key(env.get(key))
    )
    custom = read_custom_providers()
    debug_on = DEBUG_MODE_FILE.exists() and DEBUG_MODE_FILE.read_text().strip() == "true"
    return {
        "env": env,
        "local": local,
        "providers_count": configured_providers,
        "custom_providers_count": len(custom),
        "default_provider": local.get("llm", {}).get("default_provider", "-"),
        "telegram": is_real_key(env.get("TELEGRAM_TOKEN")),
        "discord": is_real_key(env.get("DISCORD_TOKEN")),
        "profile_done": bool(profile.get("onboarding_completed")),
        "profile_name": profile.get("name", ""),
        "google_credentials": (ROOT / "config" / "google_credentials.json").exists(),
        "google_token": (ROOT / "config" / "google_token.json").exists(),
        "dashboard_token": is_real_key(env.get("DASHBOARD_TOKEN")),
        "local_router_enabled": local.get("local_router", {}).get("enabled", True),
        "rag_threshold": local.get("A", {}).get(
            "rag_relevance_threshold",
            local.get("assistant", {}).get("rag_relevance_threshold", 0.5),
        ),
        "resurrection_paths": len(local.get("resurrection_paths", [])),
        "debug_mode": debug_on,
    }


# ─── Main menu ────────────────────────────────────────────────────────────────


def print_main_menu(s: dict) -> None:
    console.clear()
    console.print(Panel(
        "[bold cyan]OpenACM Setup Wizard[/bold cyan]\n"
        "[dim]Configure your agent without a browser[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("", width=3)
    t.add_column("Section", min_width=28)
    t.add_column("Status", style="dim")

    t.add_row(ok(s["providers_count"] > 0), "LLM Providers",
              f"{s['providers_count']} built-in + {s['custom_providers_count']} custom")
    t.add_row(ok(s["default_provider"] not in ("-", "")), "Default model",
              s["default_provider"])
    t.add_row(ok(s["telegram"] or s["discord"]), "Channels",
              ("Telegram " if s["telegram"] else "") + ("Discord" if s["discord"] else "") or "-")
    t.add_row(ok(s["profile_done"]), "User profile",
              s["profile_name"] or "-")
    t.add_row(ok(s["google_token"]), "Google Services",
              "OAuth OK" if s["google_token"] else ("creds OK" if s["google_credentials"] else "-"))
    t.add_row(ok(s["local_router_enabled"]), "Local Router",
              "enabled" if s["local_router_enabled"] else "disabled")
    t.add_row(ok(s["resurrection_paths"] > 0), "Code Resurrection",
              f"{s['resurrection_paths']} path(s)")
    t.add_row(ok(True), "RAG & Compaction",
              f"threshold: {s['rag_threshold']}")
    t.add_row(ok(s["dashboard_token"]), "Dashboard token",
              "generated" if s["dashboard_token"] else "-")

    console.print(t)
    console.print()
    console.print("  [bold green][G][/bold green]  Guided setup (step by step)\n")
    console.print("  [cyan][ 1][/cyan]  LLM Providers  (API keys)")
    console.print("  [cyan][ 2][/cyan]  Default model + parameters")
    console.print("  [cyan][ 3][/cyan]  Channels  (Telegram / Discord)")
    console.print("  [cyan][ 4][/cyan]  User profile")
    console.print("  [cyan][ 5][/cyan]  Google Services")
    console.print("  [cyan][ 6][/cyan]  Custom providers")
    console.print("  [cyan][ 7][/cyan]  Local Router")
    console.print("  [cyan][ 8][/cyan]  Code Resurrection")
    console.print("  [cyan][ 9][/cyan]  RAG & Compaction")
    console.print("  [cyan][10][/cyan]  Debug & Logging")
    console.print("  [cyan][11][/cyan]  Dashboard token")
    console.print()
    console.print("  [dim][0]  Exit[/dim]")
    console.print()


# ─── Section 1: Providers ─────────────────────────────────────────────────────


def setup_providers(sequential: bool = False) -> str:
    header("LLM Providers", "API keys for AI models")
    env = read_env()

    console.print("  [dim]Enter = keep current  |  'x' = clear[/dim]\n")

    for pid, name, env_key in BUILTIN_PROVIDERS:
        if env_key is None:
            console.print(f"  [dim]{name}[/dim] -- local instance, no API key needed\n")
            continue

        current = env.get(env_key, "")
        status = (
            f"[green]set (***{current[-4:]})[/green]"
            if is_real_key(current)
            else "[dim]not set[/dim]"
        )
        console.print(f"  [bold]{name}[/bold]  [dim]({env_key})[/dim]  ->  {status}")

        val = input_or_skip(env_key, current, secret=True)
        if val is None:
            pass
        elif val == "":
            write_env(env_key, "")
            console.print("  [yellow]  Cleared.[/yellow]")
        else:
            write_env(env_key, val)
            console.print("  [green]  Saved.[/green]")
        console.print()

    return nav_prompt(sequential)


# ─── Section 2: Model + params ────────────────────────────────────────────────


def setup_model(sequential: bool = False) -> str:
    header("Default model", "Choose the provider and model OpenACM will use")
    env = read_env()
    local = read_local()

    available = [
        (pid, name) for pid, name, key in BUILTIN_PROVIDERS
        if key is None or is_real_key(env.get(key))
    ] + [
        (p["id"], p["name"]) for p in read_custom_providers()
    ]

    if not available:
        console.print(
            "  [yellow]No providers configured.[/yellow]\n"
            "  Set up at least one provider first (section 1)."
        )
        return nav_prompt(sequential)

    current_pid = local.get("llm", {}).get("default_provider", "")
    console.print("  Available providers:\n")
    for i, (pid, name) in enumerate(available, 1):
        mark = "  [green]<- current[/green]" if pid == current_pid else ""
        console.print(f"  [cyan][{i:2}][/cyan]  {name}  [dim]({pid})[/dim]{mark}")
    console.print()

    default_idx = max(
        1, next((i for i, (pid, _) in enumerate(available, 1) if pid == current_pid), 1)
    )
    choice = IntPrompt.ask("  Provider", default=default_idx)
    if not (1 <= choice <= len(available)):
        console.print("  [red]Invalid choice.[/red]")
        return nav_prompt(sequential)

    pid, pname = available[choice - 1]
    models = PROVIDER_MODELS.get(pid, [])
    current_model = local.get("llm", {}).get("providers", {}).get(pid, {}).get("default_model", "")

    console.print(f"\n  Suggested models for [bold]{pname}[/bold]:\n")
    for i, m in enumerate(models, 1):
        mark = "  [green]<- current[/green]" if m == current_model else ""
        console.print(f"  [cyan][{i}][/cyan]  {m}{mark}")
    console.print(f"  [cyan][{len(models) + 1}][/cyan]  Enter manually\n")

    mc = IntPrompt.ask("  Model", default=1)
    if 1 <= mc <= len(models):
        model = models[mc - 1]
    else:
        model = Prompt.ask("  Custom model name")

    data = deep_merge(read_local(), {
        "llm": {"default_provider": pid, "providers": {pid: {"default_model": model}}}
    })

    # Model hyperparameters
    console.print(f"\n  [bold]Model parameters[/bold]  [dim](press Enter to skip)[/dim]\n")
    prov_params = data.get("llm", {}).get("providers", {}).get(pid, {})

    temp_cur = prov_params.get("temperature", "")
    temp_in = Prompt.ask(
        f"  Temperature  [dim](0.0-2.0, current: {temp_cur or 'default'})[/dim]",
        default="", show_default=False,
    )
    if temp_in.strip():
        try:
            data["llm"]["providers"][pid]["temperature"] = float(temp_in)
        except ValueError:
            console.print("  [yellow]  Invalid value, skipped.[/yellow]")

    tokens_cur = prov_params.get("max_tokens", "")
    tokens_in = Prompt.ask(
        f"  Max tokens   [dim](integer, current: {tokens_cur or 'default'})[/dim]",
        default="", show_default=False,
    )
    if tokens_in.strip():
        try:
            data["llm"]["providers"][pid]["max_tokens"] = int(tokens_in)
        except ValueError:
            console.print("  [yellow]  Invalid value, skipped.[/yellow]")

    topp_cur = prov_params.get("top_p", "")
    topp_in = Prompt.ask(
        f"  Top-p        [dim](0.0-1.0, current: {topp_cur or 'default'})[/dim]",
        default="", show_default=False,
    )
    if topp_in.strip():
        try:
            data["llm"]["providers"][pid]["top_p"] = float(topp_in)
        except ValueError:
            console.print("  [yellow]  Invalid value, skipped.[/yellow]")

    write_local(data)
    console.print(f"\n  [green]Saved:[/green]  {pid} / {model}")

    return nav_prompt(sequential)


# ─── Section 3: Channels ──────────────────────────────────────────────────────


def setup_channels(sequential: bool = False) -> str:
    header("Channels", "Connect OpenACM to Telegram and/or Discord")
    env = read_env()

    channels_info = [
        ("Telegram", "TELEGRAM_TOKEN",
         "Get the token from @BotFather -> /newbot on Telegram"),
        ("Discord",  "DISCORD_TOKEN",
         "discord.com/developers/applications -> Bot -> Token"),
    ]

    console.print("  [dim]Enter = keep current  |  'x' = clear[/dim]\n")

    for name, key, hint in channels_info:
        current = env.get(key, "")
        status = (
            f"[green]set (***{current[-6:]})[/green]"
            if is_real_key(current)
            else "[dim]not set[/dim]"
        )
        console.print(f"  [bold]{name}[/bold]  ->  {status}")
        console.print(f"  [dim]{hint}[/dim]")

        val = input_or_skip(key, current, secret=True)
        if val is None:
            pass
        elif val == "":
            write_env(key, "")
            console.print("  [yellow]  Cleared.[/yellow]")
        else:
            write_env(key, val)
            console.print("  [green]  Saved.[/green]")
        console.print()

    return nav_prompt(sequential)


# ─── Section 4: User profile ──────────────────────────────────────────────────


def setup_profile(sequential: bool = False) -> str:
    header("User profile", "Customize the assistant name and behavior")
    local = read_local()
    profile = local.get("A", {})

    current_assistant = profile.get("name", "ACM")
    current_prompt = profile.get("system_prompt", "")

    user_match = re.search(r"My user's name is ([^.]+)\.", current_prompt)
    current_user = user_match.group(1) if user_match else ""

    behavior_match = re.search(
        r"\[USER INSTRUCTIONS - BEHAVIOR MODE\]: [^.]*\. "
        r"You must try to adhere to this personality ALWAYS: (.+)$",
        current_prompt, re.DOTALL,
    )
    current_behavior = behavior_match.group(1).strip() if behavior_match else ""

    console.print(f"  Assistant name: [cyan]{current_assistant}[/cyan]")
    console.print(f"  Your name:      [cyan]{current_user or '-'}[/cyan]")
    console.print("\n  [dim]Press Enter to keep the current value[/dim]\n")

    assistant_name = Prompt.ask("  Assistant name", default=current_assistant)
    user_name = Prompt.ask("  Your name", default=current_user or "")

    if current_behavior:
        preview = current_behavior[:180] + ("..." if len(current_behavior) > 180 else "")
        console.print(f"\n  Current behavior:\n  [dim]{preview}[/dim]")

    console.print(
        "\n  [bold]Behavior / personality[/bold]\n"
        "  [dim]How you want it to respond, tone, language, etc.[/dim]"
    )
    behaviors = Prompt.ask(
        "  Behavior",
        default=current_behavior or "",
        show_default=False,
    )

    # Build system prompt
    base = re.sub(
        r"\n\n\[USER INSTRUCTIONS - BEHAVIOR MODE\].*$",
        "", current_prompt, flags=re.DOTALL,
    ).strip()

    if not base and DEFAULT_YAML.exists():
        default_cfg = yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8")) or {}
        base = default_cfg.get("assistant", {}).get("system_prompt", "")

    new_prompt = base
    if user_name or behaviors:
        parts: list[str] = []
        if user_name:
            parts.append(f"My user's name is {user_name}.")
        if behaviors:
            parts.append(f"You must try to adhere to this personality ALWAYS: {behaviors}")
        new_prompt += f"\n\n[USER INSTRUCTIONS - BEHAVIOR MODE]: {' '.join(parts)}"

    data = deep_merge(read_local(), {
        "A": {
            "name": assistant_name,
            "system_prompt": new_prompt,
            "onboarding_completed": True,
        }
    })
    write_local(data)
    console.print(f"\n  [green]Profile saved.[/green]  Assistant: [bold]{assistant_name}[/bold]")

    return nav_prompt(sequential)


# ─── Section 5: Google Services ───────────────────────────────────────────────


def setup_google(sequential: bool = False) -> str:
    header("Google Services", "Gmail, Drive, Calendar, Sheets -- OAuth2")
    creds_path = ROOT / "config" / "google_credentials.json"
    token_path = ROOT / "config" / "google_token.json"

    creds_ok = creds_path.exists()
    token_ok = token_path.exists()

    console.print(
        f"  {ok(creds_ok)} OAuth2 credentials  ->  "
        f"{'[green]found[/green]' if creds_ok else '[red]not found[/red]'}"
    )
    console.print(
        f"  {ok(token_ok)} Access token        ->  "
        f"{'[green]authorized[/green]' if token_ok else '[red]pending[/red]'}"
    )
    console.print()

    if not creds_ok:
        console.print(Panel(
            "[bold]Step 1 -- Get Google Cloud credentials[/bold]\n\n"
            "1. Go to [cyan]https://console.cloud.google.com[/cyan]\n"
            "2. Create or select a project\n"
            "3. Enable APIs: Gmail, Drive, Calendar, Sheets, YouTube\n"
            "4. Credentials -> Create -> OAuth 2.0 Client ID -> Desktop app\n"
            "5. Download the JSON and paste it below",
            border_style="yellow", padding=(0, 2),
        ))
        console.print("\n  Paste the credentials JSON  [dim](empty line to finish)[/dim]:\n")
        lines: list[str] = []
        try:
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
        except EOFError:
            pass

        if lines:
            try:
                content = "\n".join(lines)
                json.loads(content)
                creds_path.parent.mkdir(parents=True, exist_ok=True)
                creds_path.write_text(content, encoding="utf-8")
                console.print("  [green]Credentials saved.[/green]")
                creds_ok = True
            except json.JSONDecodeError:
                console.print("  [red]Invalid JSON, not saved.[/red]")

    if creds_ok and not token_ok:
        console.print(Panel(
            "[bold]Step 2 -- Authorize access (OAuth2)[/bold]\n\n"
            "[bold cyan]Option A[/bold cyan] -- SSH port-forward (recommended for servers):\n"
            "  On your local machine:  [cyan]ssh -L 47821:localhost:47821 user@server[/cyan]\n"
            "  Then open:              [cyan]http://localhost:47821[/cyan]\n"
            "  Complete the Google step in the web onboarding.\n\n"
            "[bold cyan]Option B[/bold cyan] -- Another device on the same network:\n"
            "  Open [cyan]http://SERVER-IP:47821[/cyan] from your phone or laptop.\n\n"
            "The token will be saved automatically to [dim]config/google_token.json[/dim].",
            border_style="yellow", padding=(0, 2),
        ))

    if token_ok:
        console.print()
        if Confirm.ask("  Revoke current token (disconnect Google)?", default=False):
            token_path.unlink()
            console.print("  [yellow]Token revoked.[/yellow]")

    return nav_prompt(sequential)


# ─── Section 6: Custom providers ──────────────────────────────────────────────


def setup_custom_providers(sequential: bool = False) -> str:
    while True:
        header("Custom providers", "Any OpenAI-compatible API")

        providers = read_custom_providers()

        if providers:
            t = Table(box=box.ROUNDED)
            t.add_column("#",        style="dim", width=4)
            t.add_column("Name",     min_width=16)
            t.add_column("Base URL")
            t.add_column("Model")
            t.add_column("Key", width=6)
            for i, p in enumerate(providers, 1):
                has_key = ok(bool(p.get("api_key")))
                t.add_row(
                    str(i), p.get("name", ""), p.get("base_url", ""),
                    p.get("default_model", ""), has_key,
                )
            console.print(t)
        else:
            console.print("  [dim]No custom providers yet.[/dim]\n")

        console.print("  [cyan][A][/cyan]  Add provider")
        if providers:
            console.print("  [cyan][E][/cyan]  Edit provider")
            console.print("  [cyan][D][/cyan]  Delete provider")
        console.print("  [cyan][0][/cyan]  Back / Continue\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break

        elif choice == "a":
            console.print()
            name = Prompt.ask("  Provider name")
            base_url = Prompt.ask("  Base URL  [dim](e.g. http://localhost:1234/v1)[/dim]")
            api_key = Prompt.ask(
                "  API Key  [dim](Enter to skip)[/dim]", default="", show_default=False
            )
            model = Prompt.ask("  Default model")
            extra = Prompt.ask(
                "  Additional models  [dim](comma-separated, Enter to skip)[/dim]",
                default="", show_default=False,
            )
            suggested = [m.strip() for m in extra.split(",") if m.strip()] or [model]
            providers.append({
                "id": re.sub(r"\W+", "_", name.lower()),
                "name": name,
                "base_url": base_url,
                "api_key": api_key,
                "default_model": model,
                "suggested_models": suggested,
            })
            write_custom_providers(providers)
            console.print(f"  [green]'{name}' added.[/green]")

        elif choice == "e" and providers:
            idx_s = Prompt.ask("  Number to edit")
            try:
                idx = int(idx_s) - 1
            except ValueError:
                continue
            if not (0 <= idx < len(providers)):
                continue
            p = providers[idx]
            console.print(f"\n  Editing: [bold]{p['name']}[/bold]  [dim](Enter = keep)[/dim]\n")
            new_name = Prompt.ask("  Name", default=p.get("name", ""))
            new_url = Prompt.ask("  Base URL", default=p.get("base_url", ""))
            new_key = Prompt.ask(
                "  API Key  [dim]('x' to clear)[/dim]",
                default=p.get("api_key", ""), show_default=False,
            )
            new_model = Prompt.ask("  Default model", default=p.get("default_model", ""))
            p.update({
                "name": new_name, "base_url": new_url,
                "api_key": "" if new_key == "x" else new_key,
                "default_model": new_model,
            })
            write_custom_providers(providers)
            console.print(f"  [green]'{new_name}' updated.[/green]")

        elif choice == "d" and providers:
            idx_s = Prompt.ask("  Number to delete")
            try:
                idx = int(idx_s) - 1
            except ValueError:
                continue
            if 0 <= idx < len(providers):
                removed = providers.pop(idx)
                write_custom_providers(providers)
                console.print(f"  [yellow]'{removed['name']}' deleted.[/yellow]")

    return nav_prompt(sequential)


# ─── Section 7: Local Router ──────────────────────────────────────────────────


def setup_local_router(sequential: bool = False) -> str:
    header("Local Router", "Fast intent classification without consuming LLM tokens")
    local = read_local()
    lr = local.get("local_router", {})

    enabled = lr.get("enabled", True)
    obs_mode = lr.get("observation_mode", False)
    threshold = lr.get("confidence_threshold", 0.88)

    console.print(
        "  The Local Router classifies short, repetitive messages locally\n"
        "  (without calling the LLM) using MiniLM embeddings (~5ms).\n"
    )

    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column("", width=3)
    t.add_column("Parameter", min_width=24)
    t.add_column("Value", style="cyan")
    t.add_row(ok(enabled), "Enabled", str(enabled))
    t.add_row("", "Observation mode", str(obs_mode))
    t.add_row("", "Confidence threshold", str(threshold))
    console.print(t)
    console.print()

    new_enabled = Confirm.ask("  Enable Local Router?", default=enabled)
    new_obs = Confirm.ask(
        "  Observation mode?  [dim](logs decisions only, does not route)[/dim]",
        default=obs_mode,
    )

    thresh_in = Prompt.ask(
        f"  Confidence threshold  [dim](0.5-1.0, current: {threshold})[/dim]",
        default=str(threshold), show_default=False,
    )
    try:
        new_threshold = max(0.5, min(1.0, float(thresh_in)))
    except ValueError:
        new_threshold = threshold
        console.print("  [yellow]Invalid value, keeping current.[/yellow]")

    data = deep_merge(read_local(), {
        "local_router": {
            "enabled": new_enabled,
            "observation_mode": new_obs,
            "confidence_threshold": new_threshold,
        }
    })
    write_local(data)
    console.print("\n  [green]Local Router saved.[/green]")

    return nav_prompt(sequential)


# ─── Section 8: Code Resurrection ────────────────────────────────────────────


def setup_resurrection(sequential: bool = False) -> str:
    header("Code Resurrection", "Paths OpenACM indexes to recover context from past sessions")
    local = read_local()
    paths: list[str] = local.get("resurrection_paths", [])

    while True:
        console.clear()
        console.print(Panel(
            "[bold]Code Resurrection[/bold]\n"
            "[dim]Indexed paths for past-session context recovery[/dim]",
            border_style="cyan", padding=(0, 2),
        ))

        if paths:
            t = Table(box=box.SIMPLE, show_header=False)
            t.add_column("#", style="dim", width=4)
            t.add_column("Path")
            for i, p in enumerate(paths, 1):
                t.add_row(str(i), p)
            console.print(t)
        else:
            console.print("  [dim]No paths configured.[/dim]\n")

        console.print("  [cyan][A][/cyan]  Add path")
        if paths:
            console.print("  [cyan][D][/cyan]  Delete path")
        console.print("  [cyan][0][/cyan]  Back / Continue\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break

        elif choice == "a":
            new_path = Prompt.ask("  Path  [dim](absolute or relative to project)[/dim]")
            if new_path and new_path not in paths:
                paths.append(new_path.strip())
                data = read_local()
                data["resurrection_paths"] = paths
                write_local(data)
                console.print(f"  [green]'{new_path}' added.[/green]")
            elif new_path in paths:
                console.print("  [yellow]Already exists.[/yellow]")

        elif choice == "d" and paths:
            idx_s = Prompt.ask("  Number to delete")
            try:
                idx = int(idx_s) - 1
            except ValueError:
                continue
            if 0 <= idx < len(paths):
                removed = paths.pop(idx)
                data = read_local()
                data["resurrection_paths"] = paths
                write_local(data)
                console.print(f"  [yellow]'{removed}' removed.[/yellow]")

    return nav_prompt(sequential)


# ─── Section 9: RAG & Compaction ──────────────────────────────────────────────


def setup_rag(sequential: bool = False) -> str:
    header("RAG & Compaction", "Relevance threshold and context compaction settings")
    local = read_local()
    profile = local.get("A", local.get("assistant", {}))

    rag_threshold = profile.get("rag_relevance_threshold", 0.5)
    compact_threshold = profile.get("compact_threshold", 25)
    compact_keep = profile.get("compact_keep_recent", 6)

    console.print("  [bold]RAG relevance threshold[/bold]")
    console.print(
        "  Controls how relevant a memory must be to be included in context.\n"
        "  [dim]Low (0.1) = include more memories  |  High (0.95) = only the most relevant[/dim]\n"
    )
    rag_in = Prompt.ask(
        f"  RAG threshold  [dim](0.1-0.95, current: {rag_threshold})[/dim]",
        default=str(rag_threshold), show_default=False,
    )
    try:
        new_rag = max(0.1, min(0.95, float(rag_in)))
    except ValueError:
        new_rag = rag_threshold
        console.print("  [yellow]Invalid value, keeping current.[/yellow]")

    console.print("\n  [bold]Conversation compaction[/bold]")
    console.print(
        "  When the conversation exceeds the threshold it is automatically summarized.\n"
        "  [dim]compact_threshold: messages before compacting  |  compact_keep_recent: messages kept in full[/dim]\n"
    )
    ct_in = Prompt.ask(
        f"  Compact threshold   [dim](5-200, current: {compact_threshold})[/dim]",
        default=str(compact_threshold), show_default=False,
    )
    try:
        new_ct = max(5, min(200, int(ct_in)))
    except ValueError:
        new_ct = compact_threshold

    ck_in = Prompt.ask(
        f"  Keep recent         [dim](2-20, current: {compact_keep})[/dim]",
        default=str(compact_keep), show_default=False,
    )
    try:
        new_ck = max(2, min(20, int(ck_in)))
    except ValueError:
        new_ck = compact_keep

    data = read_local()
    a = data.get("A", {})
    a["rag_relevance_threshold"] = new_rag
    a["compact_threshold"] = new_ct
    a["compact_keep_recent"] = new_ck
    data["A"] = a
    write_local(data)

    console.print(
        f"\n  [green]Saved.[/green]  "
        f"RAG: {new_rag}  |  Compact: {new_ct} msgs  |  Keep: {new_ck}"
    )
    return nav_prompt(sequential)


# ─── Section 10: Debug & Logging ──────────────────────────────────────────────


def setup_logging(sequential: bool = False) -> str:
    header("Debug & Logging", "Debug mode, verbose channels, execution mode")
    local = read_local()

    debug_on = DEBUG_MODE_FILE.exists() and DEBUG_MODE_FILE.read_text().strip() == "true"
    exec_mode = local.get("security", {}).get("execution_mode", "confirmation")
    verbose_env = read_env().get("VERBOSE_CHANNELS", "false")
    verbose_on = verbose_env.lower() == "true"

    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column("", width=3)
    t.add_column("Parameter", min_width=26)
    t.add_column("Value", style="cyan")
    t.add_row(ok(debug_on), "Debug mode", "on" if debug_on else "off")
    t.add_row("", "Verbose channels", "on" if verbose_on else "off")
    t.add_row("", "Execution mode", exec_mode)
    console.print(t)
    console.print()

    new_debug = Confirm.ask(
        "  Enable debug mode?  [dim](detailed logs in data/logs/)[/dim]",
        default=debug_on,
    )
    DEBUG_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_MODE_FILE.write_text("true" if new_debug else "false")

    new_verbose = Confirm.ask(
        "  Verbose channels?  [dim](log all Telegram/Discord messages)[/dim]",
        default=verbose_on,
    )
    write_env("VERBOSE_CHANNELS", "true" if new_verbose else "false")

    modes = ["confirmation", "auto", "yolo"]
    console.print("\n  [bold]Command execution mode[/bold]\n")
    console.print("  [cyan][1][/cyan]  confirmation -- asks for approval before each command")
    console.print("  [cyan][2][/cyan]  auto         -- executes non-blocked commands automatically")
    console.print("  [cyan][3][/cyan]  yolo         -- no restrictions  [red](use with care)[/red]\n")
    mode_choice = IntPrompt.ask("  Mode", default=modes.index(exec_mode) + 1)
    if 1 <= mode_choice <= 3:
        new_mode = modes[mode_choice - 1]
        data = deep_merge(read_local(), {"security": {"execution_mode": new_mode}})
        write_local(data)
    else:
        new_mode = exec_mode

    console.print(
        f"\n  [green]Saved.[/green]  "
        f"Debug: {'on' if new_debug else 'off'}  |  "
        f"Verbose: {'on' if new_verbose else 'off'}  |  "
        f"Mode: {new_mode}"
    )
    return nav_prompt(sequential)


# ─── Section 11: Dashboard token ──────────────────────────────────────────────


def setup_dashboard_token(sequential: bool = False) -> str:
    header("Dashboard token", "Authentication token for web UI and REPL")
    env = read_env()
    current = env.get("DASHBOARD_TOKEN", "")

    if is_real_key(current):
        console.print(f"  Current token:\n\n  [bold green]{current}[/bold green]\n")
        console.print(
            "  [dim]You need this token to:[/dim]\n"
            "  [dim]  - Access the web UI  (http://localhost:47821)[/dim]\n"
            "  [dim]  - Use the REPL       (openacm-cli)[/dim]\n"
        )
        if Confirm.ask("  Regenerate a new token?", default=False):
            new_token = secrets.token_hex(32)
            write_env("DASHBOARD_TOKEN", new_token)
            console.print(f"\n  New token:\n\n  [bold green]{new_token}[/bold green]")
            console.print("\n  [yellow]Update the token wherever you have it stored.[/yellow]")
    else:
        console.print("  [yellow]No token found. Generating one...[/yellow]\n")
        new_token = secrets.token_hex(32)
        write_env("DASHBOARD_TOKEN", new_token)
        console.print(f"  Generated token:\n\n  [bold green]{new_token}[/bold green]")
        console.print(
            "\n  [dim]Save it -- you need it for the web UI and REPL.[/dim]"
        )

    return nav_prompt(sequential)


# ─── Guided setup ─────────────────────────────────────────────────────────────


@dataclass
class Section:
    key: str
    title: str
    fn: Callable


SECTIONS: list[Section] = [
    Section("token",     "Dashboard token",            setup_dashboard_token),
    Section("providers", "LLM Providers",              setup_providers),
    Section("model",     "Default model + parameters", setup_model),
    Section("channels",  "Channels",                   setup_channels),
    Section("profile",   "User profile",               setup_profile),
    Section("google",    "Google Services",            setup_google),
    Section("custom",    "Custom providers",           setup_custom_providers),
    Section("router",    "Local Router",               setup_local_router),
    Section("resurrect", "Code Resurrection",          setup_resurrection),
    Section("rag",       "RAG & Compaction",           setup_rag),
    Section("logging",   "Debug & Logging",            setup_logging),
]


def guided_setup() -> None:
    console.clear()
    console.print(Panel(
        "[bold cyan]Guided setup[/bold cyan]\n\n"
        "We'll walk through all sections in order.\n"
        "[dim]In each section:  [cyan][N][/cyan] Next  [cyan][P][/cyan] Previous  [cyan][M][/cyan] Main menu[/dim]",
        border_style="cyan", padding=(1, 4),
    ))

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("#",       style="dim", width=4)
    t.add_column("Section")
    for i, s in enumerate(SECTIONS, 1):
        t.add_row(str(i), s.title)
    console.print(t)
    console.print()

    Prompt.ask("  [dim]Press Enter to start[/dim]", default="", show_default=False)

    idx = 0
    while 0 <= idx < len(SECTIONS):
        section = SECTIONS[idx]
        total = len(SECTIONS)

        console.clear()
        console.print(Panel(
            f"[dim]Step {idx + 1} of {total}[/dim]  |  [bold cyan]{section.title}[/bold cyan]",
            border_style="cyan", padding=(0, 2),
        ))
        console.print()

        result = section.fn(sequential=True)

        if result == NEXT:
            idx += 1
        elif result == PREV:
            idx = max(0, idx - 1)
        elif result == MENU:
            return

    console.clear()
    console.print(Panel(
        "[bold green]Setup complete![/bold green]\n\n"
        "OpenACM is ready to run:\n\n"
        "  [bold cyan]openacm[/bold cyan]        -> start the agent\n"
        "  [bold cyan]openacm-cli[/bold cyan]    -> interactive REPL\n"
        "  [bold cyan]openacm-manage[/bold cyan] -> manage swarms, cron, routines\n"
        "  [bold cyan]openacm-setup[/bold cyan]  -> come back to this wizard",
        border_style="green", padding=(1, 4),
    ))
    Prompt.ask("\n  [dim]Press Enter to exit[/dim]", default="", show_default=False)


# ─── Main ─────────────────────────────────────────────────────────────────────


_MENU_DISPATCH: dict[str, Callable] = {
    "1":  setup_providers,
    "2":  setup_model,
    "3":  setup_channels,
    "4":  setup_profile,
    "5":  setup_google,
    "6":  setup_custom_providers,
    "7":  setup_local_router,
    "8":  setup_resurrection,
    "9":  setup_rag,
    "10": setup_logging,
    "11": setup_dashboard_token,
}


def main() -> None:
    guided = "--guided" in sys.argv or "-g" in sys.argv

    if guided:
        guided_setup()
        return

    try:
        while True:
            status = get_status()
            print_main_menu(status)
            choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

            if choice == "0":
                console.print(
                    "\n  [dim]Done! Run [bold]openacm[/bold] to start the agent.[/dim]\n"
                )
                break
            elif choice == "g":
                guided_setup()
            else:
                fn = _MENU_DISPATCH.get(choice)
                if fn:
                    fn(sequential=False)
                else:
                    console.print("  [red]Invalid option.[/red]")
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n  [dim]Exiting...[/dim]\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
