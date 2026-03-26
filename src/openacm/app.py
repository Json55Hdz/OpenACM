"""
OpenACM Application Orchestrator.

Boots up all subsystems: config, database, LLM router, brain, 
channels, web dashboard, and the interactive console.
"""

import asyncio
import signal
import sys

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from openacm.core.config import load_config, AppConfig
from openacm.core.events import EventBus
from openacm.core.llm_router import LLMRouter
from openacm.core.brain import Brain
from openacm.core.memory import MemoryManager
from openacm.storage.database import Database
from openacm.tools.registry import ToolRegistry
from openacm.security.sandbox import Sandbox
from openacm.security.policies import SecurityPolicy

log = structlog.get_logger()
console = Console()

BANNER = r"""
   ____                      ___   ______ __  ___
  / __ \____  ___  ____     /   | / ____//  |/  /
 / / / / __ \/ _ \/ __ \   / /| |/ /    / /|_/ / 
/ /_/ / /_/ /  __/ / / /  / ___ / /___ / /  / /  
\____/ .___/\___/_/ /_/  /_/  |_\____//_/  /_/   
    /_/                                           
"""


class OpenACM:
    """Main application orchestrator."""

    def __init__(self):
        self.config: AppConfig | None = None
        self.event_bus: EventBus | None = None
        self.database: Database | None = None
        self.llm_router: LLMRouter | None = None
        self.memory: MemoryManager | None = None
        self.brain: Brain | None = None
        self.tool_registry: ToolRegistry | None = None
        self.sandbox: Sandbox | None = None
        self.security_policy: SecurityPolicy | None = None
        self._channels: list = []
        self._web_server = None
        self._shutdown_event = asyncio.Event()

    async def run(self):
        """Start OpenACM."""
        self._print_banner()
        
        # Phase 1: Load config
        console.print("[dim]Loading configuration...[/dim]")
        self.config = load_config()
        
        # Phase 2: Initialize core systems
        console.print("[dim]Initializing core systems...[/dim]")
        await self._init_core()
        
        # Phase 3: Register tools
        console.print("[dim]Registering tools...[/dim]")
        await self._init_tools()
        
        # Phase 4: Start channels
        console.print("[dim]Starting channels...[/dim]")
        await self._init_channels()
        
        # Phase 5: Generate dashboard token
        from openacm.security.crypto import get_or_create_dashboard_token
        dashboard_token = get_or_create_dashboard_token()
        
        # Phase 5.1: Start web dashboard
        console.print("[dim]Starting web dashboard...[/dim]")
        await self._init_web()
        
        console.print(Panel(
            f"[green bold]✅ OpenACM is running![/green bold]\n\n"
            f"  🧠 LLM: [cyan]{self.config.llm.default_provider}[/cyan] "
            f"([cyan]{self._get_default_model()}[/cyan])\n"
            f"  🖥️  Web: [cyan]http://{self.config.web.host}:{self.config.web.port}[/cyan]\n"
            f"  🔒 Security: [yellow]{self.config.security.execution_mode}[/yellow] mode\n"
            f"  📱 Channels: {self._get_active_channels_str()}\n\n"
            f"  🔑 Dashboard Token:\n"
            f"  [bold yellow]{dashboard_token}[/bold yellow]\n"
            f"  [dim](Cópialo la primera vez que abras el dashboard)[/dim]",
            title="[bold white]OpenACM v0.1.0[/bold white]",
            border_style="green",
        ))
        
        # Phase 6: Interactive console loop
        await self._console_loop()

    async def _init_core(self):
        """Initialize core subsystems."""
        # Event bus
        self.event_bus = EventBus()
        
        # Database
        self.database = Database(self.config.storage.database_path)
        await self.database.initialize()
        
        # Security
        self.security_policy = SecurityPolicy(self.config.security)
        self.sandbox = Sandbox(self.security_policy, self.event_bus)
        
        # LLM Router
        self.llm_router = LLMRouter(self.config.llm, self.event_bus)
        
        # Memory
        self.memory = MemoryManager(self.database, self.config.assistant)
        
        # RAG Engine
        try:
            import chromadb
            from openacm.core import rag
            rag._rag_engine = rag.RAGEngine()
            await rag._rag_engine.initialize()
            console.print("  [green]✓[/green] Optional RAG engine ready")
        except ImportError:
            console.print("  [yellow]⚠[/yellow] RAG engine dependencies missing (chromadb/sentence-transformers)")
        except Exception as e:
            console.print(f"  [yellow]⚠[/yellow] RAG engine initialization failed: {e}")
        
        # Brain
        self.brain = Brain(
            config=self.config.assistant,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=None,  # set after tools init
        )

    async def _init_tools(self):
        """Register all tools."""
        self.tool_registry = ToolRegistry(self.sandbox, self.event_bus, self.database)
        
        # Import and register all built-in tools
        from openacm.tools import system_cmd, file_ops, system_info, web_search, google_services, screenshot, rag_tools, browser_agent, python_kernel
        self.tool_registry.register_module(system_cmd)
        self.tool_registry.register_module(file_ops)
        self.tool_registry.register_module(system_info)
        self.tool_registry.register_module(web_search)
        self.tool_registry.register_module(google_services)
        self.tool_registry.register_module(screenshot)
        self.tool_registry.register_module(rag_tools)
        self.tool_registry.register_module(browser_agent)
        self.tool_registry.register_module(python_kernel)
        
        # Give brain access to tools
        self.brain.tool_registry = self.tool_registry
        
        tool_count = len(self.tool_registry.tools)
        console.print(f"  [green]✓[/green] {tool_count} tools registered")

    async def _init_channels(self):
        """Initialize messaging channels."""
        if self.config.channels.discord.enabled:
            try:
                from openacm.channels.discord_channel import DiscordChannel
                channel = DiscordChannel(self.config.channels.discord, self.brain, self.event_bus)
                self._channels.append(channel)
                asyncio.create_task(channel.start())
                console.print("  [green]✓[/green] Discord channel started")
            except Exception as e:
                console.print(f"  [red]✗[/red] Discord failed: {e}")

        if self.config.channels.telegram.enabled:
            try:
                from openacm.channels.telegram_channel import TelegramChannel
                channel = TelegramChannel(self.config.channels.telegram, self.brain, self.event_bus)
                self._channels.append(channel)
                asyncio.create_task(channel.start())
                console.print("  [green]✓[/green] Telegram channel started")
            except Exception as e:
                console.print(f"  [red]✗[/red] Telegram failed: {e}")

        if self.config.channels.whatsapp.enabled:
            try:
                from openacm.channels.whatsapp_channel import WhatsAppChannel
                channel = WhatsAppChannel(self.config.channels.whatsapp, self.brain, self.event_bus)
                self._channels.append(channel)
                asyncio.create_task(channel.start())
                console.print("  [green]✓[/green] WhatsApp channel started")
            except Exception as e:
                console.print(f"  [red]✗[/red] WhatsApp failed: {e}")

        if not self._channels:
            console.print("  [dim]No external channels enabled (edit config/default.yaml)[/dim]")

    async def _init_web(self):
        """Start the web dashboard."""
        try:
            from openacm.web.server import create_web_server
            self._web_server = await create_web_server(
                config=self.config,
                brain=self.brain,
                database=self.database,
                event_bus=self.event_bus,
                tool_registry=self.tool_registry,
            )
            console.print(
                f"  [green]✓[/green] Web dashboard at "
                f"[link=http://{self.config.web.host}:{self.config.web.port}]"
                f"http://{self.config.web.host}:{self.config.web.port}[/link]"
            )
        except Exception as e:
            console.print(f"  [red]✗[/red] Web dashboard failed: {e}")

    async def _console_loop(self):
        """Interactive console for direct chatting."""
        console.print("\n[dim]Type your message below (or 'quit' to exit, '/help' for commands):[/dim]\n")

        while not self._shutdown_event.is_set():
            try:
                user_input = await asyncio.to_thread(
                    console.input, "[bold cyan]You>[/bold cyan] "
                )
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
                    break

                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # Send to brain
                console.print()
                response = await self.brain.process_message(
                    content=user_input,
                    user_id="console",
                    channel_id="console",
                    channel_type="console",
                )
                console.print(f"\n[bold green]ACM>[/bold green] {response}\n")

            except (EOFError, KeyboardInterrupt):
                break
            except Exception as e:
                console.print(f"\n[red]Error: {e}[/red]\n")

        await self._shutdown()

    async def _handle_command(self, command: str):
        """Handle console slash commands."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "/help":
                console.print(Panel(
                    "/model <provider/model>  — Switch LLM model\n"
                    "/models                  — List available models\n"
                    "/clear                   — Clear conversation history\n"
                    "/stats                   — Show usage statistics\n"
                    "/config                  — Show current configuration\n"
                    "/tools                   — List available tools\n"
                    "/quit                    — Exit OpenACM",
                    title="[bold]Commands[/bold]",
                    border_style="blue",
                ))
            case "/model":
                if args:
                    self.llm_router.set_model(args)
                    console.print(f"[green]✓ Model set to: {args}[/green]")
                else:
                    current = self.llm_router.current_model
                    console.print(f"Current model: [cyan]{current}[/cyan]")
            case "/models":
                models = self.llm_router.list_models()
                for provider, model_list in models.items():
                    console.print(f"\n[bold]{provider}[/bold]:")
                    for m in model_list:
                        console.print(f"  • {m}")
            case "/clear":
                await self.memory.clear("console", "console")
                console.print("[green]✓ Conversation cleared[/green]")
            case "/stats":
                stats = await self.database.get_stats()
                console.print(Panel(
                    f"Messages: {stats.get('total_messages', 0)}\n"
                    f"Tokens used: {stats.get('total_tokens', 0)}\n"
                    f"Tool executions: {stats.get('total_tool_calls', 0)}\n"
                    f"Active conversations: {stats.get('active_conversations', 0)}",
                    title="[bold]Usage Stats[/bold]",
                    border_style="cyan",
                ))
            case "/tools":
                for name, tool in self.tool_registry.tools.items():
                    risk = tool.risk_level
                    color = {"low": "green", "medium": "yellow", "high": "red"}.get(risk, "white")
                    console.print(f"  [{color}]●[/{color}] {name} — {tool.description}")
            case "/config":
                console.print(f"Provider: [cyan]{self.config.llm.default_provider}[/cyan]")
                console.print(f"Model: [cyan]{self._get_default_model()}[/cyan]")
                console.print(f"Security: [yellow]{self.config.security.execution_mode}[/yellow]")
                console.print(f"Web: [cyan]http://{self.config.web.host}:{self.config.web.port}[/cyan]")
            case _:
                console.print(f"[red]Unknown command: {cmd}[/red]. Type /help for commands.")

    async def _shutdown(self):
        """Gracefully shutdown all subsystems."""
        console.print("\n[yellow]Shutting down...[/yellow]")
        self._shutdown_event.set()

        # Stop channels
        for channel in self._channels:
            try:
                await channel.stop()
            except Exception:
                pass

        # Stop web server
        if self._web_server:
            try:
                self._web_server.should_exit = True
            except Exception:
                pass

        # Close database
        if self.database:
            await self.database.close()
            
        # Stop browser agent
        try:
            from openacm.tools import browser_agent
            await browser_agent.stop_browser()
        except Exception:
            pass
            
        # Stop Python Kernel
        try:
            from openacm.tools import python_kernel
            await python_kernel.stop_kernel()
        except Exception:
            pass

        console.print("[green]✓ OpenACM stopped. Goodbye! 👋[/green]")

    def _get_default_model(self) -> str:
        """Get the default model name."""
        provider = self.config.llm.default_provider
        providers = self.config.llm.providers
        if provider in providers:
            return providers[provider].get("default_model", "unknown")
        return "unknown"

    def _get_active_channels_str(self) -> str:
        """Get formatted string of active channels."""
        active = []
        if self.config.channels.discord.enabled:
            active.append("[blue]Discord[/blue]")
        if self.config.channels.telegram.enabled:
            active.append("[blue]Telegram[/blue]")
        if self.config.channels.whatsapp.enabled:
            active.append("[green]WhatsApp[/green]")
        active.append("[cyan]Console[/cyan]")
        active.append("[cyan]Web[/cyan]")
        return " · ".join(active)

    def _print_banner(self):
        """Print the startup banner."""
        banner_text = Text(BANNER, style="bold cyan")
        console.print(banner_text)
        console.print("[dim]Multi-channel AI Assistant with System Control[/dim]\n")
