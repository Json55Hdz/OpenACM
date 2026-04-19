"""
add_resurrection_path.py - Tool to autoconfigure paths for Code Resurrection.
"""

import os
from pathlib import Path
import yaml
import structlog
from openacm.tools.base import tool
from openacm.core.config import _find_project_root

log = structlog.get_logger()

@tool(
    name="add_resurrection_path",
    description=(
        "Agrega una nueva ruta absoluta al sistema de Code Resurrection (Segundo Cerebro de Código). "
        "Usa esto automáticamente si el usuario te proporciona la ruta de sus proyectos viejos por el chat."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta absoluta de la carpeta de proyectos a indexar",
            }
        },
        "required": ["path"],
    },
    risk_level="low",
    needs_sandbox=False,
    category="system",
)
async def add_resurrection_path(path: str, **kwargs) -> str:
    """Add a path to the resurrection_paths config."""
    p = Path(path).resolve()
    if not p.exists() or not p.is_dir():
        return f"Error: La ruta {path} no existe o no es un directorio válido."

    str_path = str(p)
    root = _find_project_root()
    config_file = root / "config" / "default.yaml"
    
    data = {}
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            log.error("Failed to read config", error=str(e))
    
    paths = data.get("resurrection_paths", [])
    if str_path in paths:
        return f"La ruta {str_path} ya estaba configurada para Code Resurrection."
        
    paths.append(str_path)
    data["resurrection_paths"] = paths
    
    config_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        return f"Error al guardar la configuración: {e}"

    # Try to update the active config in memory if running on the same process
    try:
        from openacm.web.server import _state
        if _state.config:
            if str_path not in _state.config.resurrection_paths:
                _state.config.resurrection_paths.append(str_path)
    except Exception:
        pass

    return f"¡Ruta '{str_path}' agregada exitosamente! El Watcher en background comenzará a indexarla (o continuará) durante mi tiempo de inactividad."

__all__ = ["add_resurrection_path"]
