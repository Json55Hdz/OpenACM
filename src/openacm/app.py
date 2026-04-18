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
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from openacm.core.config import load_config, AppConfig
from openacm.core.commands import CommandProcessor
from openacm.core.events import EventBus
from openacm.core.llm_router import LLMRouter
from openacm.core.brain import Brain
from openacm.core.local_router import LocalRouter
from openacm.core.memory import MemoryManager
from openacm.core.skill_manager import SkillManager
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
        self.skill_manager: SkillManager | None = None
        self.sandbox: Sandbox | None = None
        self.security_policy: SecurityPolicy | None = None
        self.command_processor: CommandProcessor | None = None
        self._channels: list = []
        self._agent_bot_manager = None
        self._mcp_manager = None
        self._web_server = None
        self._activity_watcher = None
        self._cron_scheduler = None
        self._resurrection_watcher = None
        self._swarm_manager = None
        self._content_watcher = None  # kept for server.py compat; plugins manage their own
        self._plugin_manager = None
        self._shutdown_event = asyncio.Event()

    async def run(self):
        """Start OpenACM."""
        self._print_banner()

        steps = [
            "Loading configuration",
            "Initializing database",
            "Loading AI & memory",
            "Registering tools",
            "Starting channels",
            "Starting web dashboard",
        ]
        total = len(steps)

        with Progress(
            SpinnerColumn(),
            BarColumn(bar_width=28),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TextColumn("[bold cyan]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(steps[0], total=total)

            # Phase 1: Load config
            progress.update(task, description=steps[0])
            self.config = load_config()
            progress.advance(task)

            # Phase 2-3: Initialize core systems
            progress.update(task, description=steps[1])
            await self._init_core(progress, task, steps)

            # Phase 4: Register tools
            progress.update(task, description=steps[3])
            await self._init_tools()
            progress.advance(task)

            # Phase 5: Start channels
            progress.update(task, description=steps[4])
            await self._init_channels()
            await self._init_agent_bots()
            progress.advance(task)

            # Generate dashboard token
            from openacm.security.crypto import get_or_create_dashboard_token
            dashboard_token = get_or_create_dashboard_token()

            # Phase 6: Start web dashboard
            progress.update(task, description=steps[5])
            await self._init_watchers()
            await self._init_web()
            progress.advance(task)

        console.print(
            Panel(
                f"[green bold]✅ OpenACM is running![/green bold]\n\n"
                f"  🧠 LLM: [cyan]{self.config.llm.default_provider}[/cyan] "
                f"([cyan]{self._get_default_model()}[/cyan])\n"
                f"  🖥️  Web: [cyan]http://{self.config.web.host}:{self.config.web.port}[/cyan]\n"
                f"  🔒 Security: [yellow]{self.config.security.execution_mode}[/yellow] mode\n"
                f"  📱 Channels: {self._get_active_channels_str()}\n\n"
                f"  🔑 Dashboard Token:\n"
                f"  [bold yellow]{dashboard_token}[/bold yellow]\n"
                f"  [dim](Copy this token the first time you open the dashboard)[/dim]",
                title="[bold white]OpenACM v0.1.0[/bold white]",
                border_style="green",
            )
        )

        # Start LocalRouter warm-up AFTER the panel so its log appears below it.
        # Once the model is loaded, also precompute tool embeddings for semantic selection.
        async def _warmup_and_embed():
            await self.brain.local_router.warm_up()
            model = LocalRouter._model
            if model is not None and self.tool_registry is not None:
                try:
                    self.tool_registry.precompute_tool_embeddings(model)
                except Exception as e:
                    log.warning("Failed to precompute tool embeddings", error=str(e))

        asyncio.create_task(_warmup_and_embed())

        # Phase 6: Interactive console loop
        await self._console_loop()

    async def _init_core(self, progress=None, task=None, steps=None):
        """Initialize core subsystems."""
        import os
        from pathlib import Path

        def _step(desc):
            if progress and task is not None:
                progress.update(task, description=desc)

        workspace = Path(self.config.storage.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
        os.environ["OPENACM_WORKSPACE"] = str(workspace)
        os.environ["OPENACM_PROJECT_ROOT"] = str(workspace.parent)

        # Event bus
        self.event_bus = EventBus()

        # Activity encryptor (local key, never transmitted)
        _enc = None
        try:
            from openacm.watchers.encryption import ActivityEncryptor
            _enc = ActivityEncryptor()
            console.print(f"  [green]✓[/green] Activity data encrypted (key: [dim]{_enc.key_path}[/dim])")
        except Exception as _enc_err:
            console.print(f"  [yellow]~[/yellow] Activity encryption skipped: {_enc_err}")

        # Database
        _step("Initializing database")
        self.database = Database(self.config.storage.database_path, encryptor=_enc)
        await self.database.initialize()
        if progress and task is not None:
            progress.advance(task)

        # Security + LLM Router + Memory
        _step("Loading AI & memory")
        self.security_policy = SecurityPolicy(self.config.security)
        self.sandbox = Sandbox(self.security_policy, self.event_bus)
        self.llm_router = LLMRouter(self.config.llm, self.event_bus)
        self.memory = MemoryManager(self.database, self.config.assistant)

        # RAG Engine
        try:
            import chromadb
            from openacm.core import rag
            rag._rag_engine = rag.RAGEngine()
            await rag._rag_engine.initialize()
        except ImportError:
            pass  # chromadb optional
        except Exception as e:
            log.warning("RAG engine initialization failed", error=str(e))

        # Skill Manager
        self.skill_manager = SkillManager(self.database)
        await self.skill_manager.initialize()
        if progress and task is not None:
            progress.advance(task)

        # LLM Router — restore persisted model preference
        await self.llm_router.load_persisted_model(self.database)

        # Restore persisted security settings
        saved_mode = await self.database.get_setting("security.execution_mode")
        if saved_mode and saved_mode in ("yolo", "confirmation", "auto"):
            self.config.security.execution_mode = saved_mode

        # Brain
        self.brain = Brain(
            config=self.config.assistant,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=None,  # set after tools init
            skill_manager=self.skill_manager,
        )

        # Workflow Tracker — detects repeated tool patterns and suggests automation
        try:
            from openacm.core.workflow_tracker import WorkflowTracker
            from openacm.core import rag as _rag_module
            _rag_engine = getattr(_rag_module, '_rag_engine', None)
        except Exception:
            _rag_engine = None
        try:
            from openacm.core.workflow_tracker import WorkflowTracker
            self.brain.workflow_tracker = WorkflowTracker(
                self.database, _rag_engine, self.brain.llm_router
            )
        except Exception as _wf_err:
            log.warning("WorkflowTracker init failed", error=str(_wf_err))

        # Central command processor
        self.command_processor = CommandProcessor(self.brain, self.database)

    async def _init_tools(self):
        """Register all tools."""
        self.tool_registry = ToolRegistry(self.sandbox, self.event_bus, self.database)

        # Import and register all built-in tools
        from openacm.tools import (
            system_cmd,
            file_ops,
            system_info,
            web_search,
            google_services,
            screenshot,
            rag_tools,
            browser_agent,
            python_kernel,
            skill_creator,
            blender_tool,
            add_resurrection_path,
            onboarding_tools,
        )

        self.tool_registry.register_module(system_cmd)
        self.tool_registry.register_module(file_ops)
        self.tool_registry.register_module(system_info)
        self.tool_registry.register_module(web_search)
        self.tool_registry.register_module(google_services)
        self.tool_registry.register_module(screenshot)
        self.tool_registry.register_module(rag_tools)
        self.tool_registry.register_module(browser_agent)
        self.tool_registry.register_module(python_kernel)
        self.tool_registry.register_module(skill_creator)
        self.tool_registry.register_module(blender_tool)
        self.tool_registry.register_module(add_resurrection_path)
        self.tool_registry.register_module(onboarding_tools)

        from openacm.tools import agent_tool
        self.tool_registry.register_module(agent_tool)

        from openacm.tools import cron_tool
        self.tool_registry.register_module(cron_tool)

        from openacm.tools import swarm_tool
        self.tool_registry.register_module(swarm_tool)

        from openacm.tools import code_editor
        self.tool_registry.register_module(code_editor)

        # Content tools are now registered by the ContentAutomationPlugin via plugin_manager
        # (see _init_plugins). Keep nothing here for content.

        # Stitch tool (optional — requiere STITCH_API_KEY en config/.env)
        try:
            from openacm.tools import stitch_tool
            self.tool_registry.register_module(stitch_tool)
        except Exception as _stitch_err:
            console.print(f"  [yellow]~[/yellow] Stitch tool skipped: {_stitch_err}")

        # IoT tools (optional — skipped gracefully if dependencies missing)
        try:
            from openacm.tools.iot import iot_tool
            self.tool_registry.register_module(iot_tool)
        except Exception as _iot_err:
            console.print(f"  [yellow]~[/yellow] IoT tools skipped: {_iot_err}")

        # Give brain access to tools
        self.brain.tool_registry = self.tool_registry

        # MCP servers (optional — skipped gracefully if mcp not installed)
        try:
            from openacm.tools.mcp_client import MCPManager
            from openacm.core.config import _find_project_root

            mcp_config_path = _find_project_root() / "config" / "mcp_servers.json"
            self._mcp_manager = MCPManager(mcp_config_path, self.tool_registry)
            await self._mcp_manager.auto_connect_all()
            server_count = len(self._mcp_manager.servers)
            if server_count:
                console.print(f"  [green]✓[/green] MCP: {server_count} server(s) configured")
            else:
                console.print("  [dim]MCP: no servers configured (add them in the dashboard)[/dim]")
        except Exception as _mcp_err:
            console.print(f"  [yellow]~[/yellow] MCP skipped: {_mcp_err}")

        tool_count = len(self.tool_registry.tools)
        console.print(f"  [green]✓[/green] {tool_count} tools registered")

    async def _init_channels(self):
        """Initialize messaging channels and wait until each one connects (or fails)."""
        channel_tasks = []

        if self.config.channels.discord.enabled:
            try:
                from openacm.channels.discord_channel import DiscordChannel

                channel = DiscordChannel(self.config.channels.discord, self.brain, self.event_bus)
                self._channels.append(channel)
                channel_tasks.append(asyncio.create_task(channel.start()))
            except Exception as e:
                console.print(f"  [red]✗[/red] Discord failed: {e}")

        if self.config.channels.telegram.enabled:
            try:
                from openacm.channels.telegram_channel import TelegramChannel

                channel = TelegramChannel(
                    self.config.channels.telegram, self.brain, self.event_bus, self.database
                )
                self._channels.append(channel)
                channel_tasks.append(asyncio.create_task(channel.start()))
            except Exception as e:
                console.print(f"  [red]✗[/red] Telegram failed: {e}")

        if self.config.channels.whatsapp.enabled:
            try:
                from openacm.channels.whatsapp_channel import WhatsAppChannel

                channel = WhatsAppChannel(self.config.channels.whatsapp, self.brain, self.event_bus)
                self._channels.append(channel)
                channel_tasks.append(asyncio.create_task(channel.start()))
            except Exception as e:
                console.print(f"  [red]✗[/red] WhatsApp failed: {e}")

        if not self._channels:
            console.print("  [dim]No external channels enabled (edit config/default.yaml)[/dim]")
            return

        # Wait for every channel to signal readiness (connected OR failed), max 15 s per channel.
        await asyncio.gather(
            *[
                asyncio.wait_for(ch.ready_event.wait(), timeout=15)
                for ch in self._channels
            ],
            return_exceptions=True,
        )

        for ch in self._channels:
            status = "[green]✓[/green]" if ch.is_connected else "[yellow]~[/yellow]"
            console.print(f"  {status} {ch.name.capitalize()} channel ready")

    async def _init_agent_bots(self):
        """Start individual Telegram bots for agents that have a telegram_token."""
        try:
            from openacm.core.agent_runner import AgentRunner
            from openacm.channels.agent_telegram_bot import AgentBotManager

            agent_runner = AgentRunner(
                llm_router=self.llm_router,
                tool_registry=self.tool_registry,
                memory=self.memory,
                event_bus=self.event_bus,
            )
            self._agent_bot_manager = AgentBotManager(
                agent_runner=agent_runner,
                event_bus=self.event_bus,
                database=self.database,
            )
            await self._agent_bot_manager.start_all()

            active = [b for b in self._agent_bot_manager.get_status() if b["connected"]]
            if active:
                console.print(f"  [green]✓[/green] {len(active)} agent Telegram bot(s) running")
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Agent bots skipped: {e}")

    async def _init_watchers(self):
        """Start OS activity watcher and cron scheduler."""
        try:
            from openacm.watchers.activity_watcher import ActivityWatcher
            self._activity_watcher = ActivityWatcher(self.database)
            await self._activity_watcher.start()
            console.print("  [green]✓[/green] Activity watcher running")
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Activity watcher skipped: {e}")

        try:
            from openacm.watchers.resurrection_watcher import ResurrectionWatcher
            from openacm.core import rag
            self._resurrection_watcher = ResurrectionWatcher(
                self.config, self.event_bus, rag._rag_engine, self.database
            )
            await self._resurrection_watcher.start()
            console.print("  [green]✓[/green] Resurrection watcher running")
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Resurrection watcher skipped: {e}")

        try:
            from openacm.watchers.cron_scheduler import CronScheduler
            self._cron_scheduler = CronScheduler(
                database=self.database,
                brain=self.brain,
            )
            await self._cron_scheduler.start()
            job_count = len(self._cron_scheduler._jobs)
            console.print(
                f"  [green]✓[/green] Cron scheduler running ([dim]{job_count} job(s)[/dim])"
            )
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Cron scheduler skipped: {e}")

        try:
            from openacm.core.swarm_manager import SwarmManager
            self._swarm_manager = SwarmManager(
                database=self.database,
                llm_router=self.llm_router,
                tool_registry=self.tool_registry,
                memory=self.memory,
                event_bus=self.event_bus,
            )
            console.print("  [green]✓[/green] Swarm manager ready")
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Swarm manager skipped: {e}")

        # Pass swarm_manager to cron scheduler so run_swarm_template works
        if self._cron_scheduler and self._swarm_manager:
            self._cron_scheduler._swarm_manager = self._swarm_manager

        # Start all registered plugins (they manage their own watchers/tools/keywords)
        await self._start_plugins()

    async def _init_web(self):
        """Start the web dashboard."""
        try:
            from openacm.web.server import create_web_server

            import os as _os
            _os.environ["OPENACM_PORT"] = str(self.config.web.port)
            # Give cron tools access to the scheduler for trigger_now
            if self._cron_scheduler:
                try:
                    from openacm.tools import cron_tool as _ct
                    _ct._cron_scheduler = self._cron_scheduler
                except Exception:
                    pass

            # Give swarm tool access to the swarm manager
            if self._swarm_manager:
                try:
                    from openacm.tools import swarm_tool as _st
                    _st._swarm_manager = self._swarm_manager
                except Exception:
                    pass

            self._web_server = await create_web_server(
                config=self.config,
                brain=self.brain,
                database=self.database,
                event_bus=self.event_bus,
                tool_registry=self.tool_registry,
                channels=self._channels,
                agent_bot_manager=self._agent_bot_manager,
                mcp_manager=self._mcp_manager,
                activity_watcher=self._activity_watcher,
                cron_scheduler=self._cron_scheduler,
                swarm_manager=self._swarm_manager,
                content_watcher=self._content_watcher,
            )
            console.print(
                f"  [green]✓[/green] Web dashboard at "
                f"[link=http://{self.config.web.host}:{self.config.web.port}]"
                f"http://{self.config.web.host}:{self.config.web.port}[/link]"
            )
        except Exception as e:
            console.print(f"  [red]✗[/red] Web dashboard failed: {e}")

    async def _start_plugins(self) -> None:
        """Load builtin plugins and start them all."""
        from openacm.plugins import plugin_manager
        from pathlib import Path as _Path

        self._plugin_manager = plugin_manager

        # Auto-discover plugins in openacm.plugins.*
        plugin_manager.load_builtin_plugins()

        # Start each plugin with the full app context
        await plugin_manager.start_all(
            config=self.config,
            database=self.database,
            event_bus=self.event_bus,
            llm_router=self.llm_router,
            brain=self.brain,
            tool_registry=self.tool_registry,
            skill_manager=self.skill_manager,
            activity_watcher=self._activity_watcher,
            cron_scheduler=self._cron_scheduler,
            swarm_manager=self._swarm_manager,
            workspace_root=_Path(self.config.storage.workspace_path),
        )

        loaded = [p.name for p in plugin_manager.plugins]
        if loaded:
            console.print(f"  [green]✓[/green] Plugins: {', '.join(loaded)}")

    async def _console_loop(self):
        """Interactive console for direct chatting."""
        console.print(
            "\n[dim]Type your message below (or 'quit' to exit, '/help' for commands):[/dim]\n"
        )

        while not self._shutdown_event.is_set():
            try:
                user_input = await asyncio.to_thread(console.input, "[bold cyan]You>[/bold cyan] ")
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

        # Console-only commands handled locally
        match cmd:
            case "/models":
                models = self.llm_router.list_models()
                for provider, model_list in models.items():
                    console.print(f"\n[bold]{provider}[/bold]:")
                    for m in model_list:
                        console.print(f"  • {m}")
                return
            case "/tools":
                for name, tool in self.tool_registry.tools.items():
                    risk = tool.risk_level
                    color = {"low": "green", "medium": "yellow", "high": "red"}.get(risk, "white")
                    console.print(f"  [{color}]●[/{color}] {name} — {tool.description}")
                return
            case "/config":
                console.print(f"Provider: [cyan]{self.config.llm.default_provider}[/cyan]")
                console.print(f"Model: [cyan]{self._get_default_model()}[/cyan]")
                console.print(f"Security: [yellow]{self.config.security.execution_mode}[/yellow]")
                console.print(
                    f"Web: [cyan]http://{self.config.web.host}:{self.config.web.port}[/cyan]"
                )
                return

        # Delegate shared commands to the central CommandProcessor
        result = await self.command_processor.handle(cmd, args, "console", "console")
        if result.handled:
            console.print(result.text)
        else:
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

        # Stop agent Telegram bots
        if self._agent_bot_manager:
            try:
                await self._agent_bot_manager.stop_all()
            except Exception:
                pass

        # Stop cron scheduler
        if self._cron_scheduler:
            try:
                await self._cron_scheduler.stop()
            except Exception:
                pass

        # Stop activity watcher
        if self._activity_watcher:
            try:
                await self._activity_watcher.stop()
            except Exception:
                pass

        if getattr(self, "_resurrection_watcher", None):
            try:
                await self._resurrection_watcher.stop()
            except Exception:
                pass

        # Stop all plugins (they manage their own watchers/connections)
        if self._plugin_manager:
            try:
                await self._plugin_manager.stop_all()
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

        # Disconnect MCP servers
        if self._mcp_manager:
            try:
                await self._mcp_manager.disconnect_all()
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
        console.print("[dim]Open Automated Computer Manager - Tier-1 Autonomous Agent[/dim]\n")
