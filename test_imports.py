"""Quick test to verify all imports work."""

print("Testing imports...")

from openacm.core.config import load_config
from openacm.core.brain import Brain
from openacm.core.llm_router import LLMRouter
from openacm.core.memory import MemoryManager
from openacm.core.events import EventBus
from openacm.tools.registry import ToolRegistry
from openacm.tools.base import get_registered_tools
from openacm.tools import system_cmd, file_ops, system_info, web_search, google_services
from openacm.security.sandbox import Sandbox
from openacm.security.policies import SecurityPolicy
from openacm.channels.discord_channel import DiscordChannel
from openacm.channels.telegram_channel import TelegramChannel
from openacm.web.server import create_app

print("✓ All imports OK")

config = load_config()
print(f"✓ Config loaded: provider={config.llm.default_provider}")

# Check registered tools
tools = get_registered_tools()
print(f"✓ {len(tools)} tools registered:")
for t in tools:
    print(f"  - {t.name} ({t.risk_level})")

print("\n✅ OpenACM is ready to run!")
print(f"   Run with: .venv\\Scripts\\python.exe -m openacm")
