"""Tools module — system tools the AI can use."""

from openacm.tools import system_cmd, file_ops, system_info, web_search, google_services, set_workspace, list_tools

try:
    from openacm.tools.iot import iot_tool
except Exception as _iot_err:
    import structlog as _log
    _log.get_logger().warning("IoT tools not loaded", error=str(_iot_err),
                              hint="Run: uv pip install tinytuya aiowebostv python-miio")

__all__ = ["system_cmd", "file_ops", "system_info", "web_search", "google_services", "set_workspace", "list_tools"]
