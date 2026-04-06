"""Tools module — system tools the AI can use."""

from openacm.tools import system_cmd, file_ops, system_info, web_search, google_services, blender_tool

try:
    from openacm.tools.iot import iot_tool
except Exception as _iot_err:
    import structlog as _log
    _log.get_logger().warning("IoT tools not loaded", error=str(_iot_err),
                              hint="Run: uv pip install tinytuya aiowebostv python-miio")

try:
    from openacm.tools import remote_tool
except Exception as _remote_err:
    import structlog as _log2
    _log2.get_logger().warning("Remote control tool not loaded", error=str(_remote_err),
                                hint="Run: uv pip install pyautogui pyngrok")

__all__ = ["system_cmd", "file_ops", "system_info", "web_search", "google_services", "blender_tool", "remote_tool"]

