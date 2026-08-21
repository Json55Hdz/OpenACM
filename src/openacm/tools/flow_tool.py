"""Tool letting an agent create or update one of its own flows by
generating graph_json directly, without the visual editor."""
from __future__ import annotations

import json
import re

from openacm.core.flow_executor import validate_graph
from openacm.tools.base import tool

_CHANNEL_AGENT_RE = re.compile(r"^agent_(\d+)$")

_FLOW_TOOL_DESCRIPTION = """Crea o actualiza un flujo visual de un agente generando su grafo (graph_json) directamente, sin usar el editor visual. Usa esto cuando el usuario te pida construir, armar o modificar un flujo/automatización.

Un flujo es un grafo con dos tipos de conexión: 'flow' (define el orden de ejecución) y 'data' (pasa un valor de la salida de un nodo al campo de otro, sin afectar el orden).

TIPOS DE NODO Y SU CONFIG (campo 'config' de cada nodo):
- start: {"parameters": [{"name": str, "type": "string"|"number"|"boolean", "description": str, "required": bool}]} — el punto de entrada. Sin pin de flujo de entrada. Pin de flujo de salida: "default".
- http: {"url": str, "method": "GET"|"POST"|"PUT"|"DELETE", "headers": dict, "body": str} — llamada HTTP. Pines de flujo: entrada "default", salida "default". Pines de dato de entrada (wire-or-literal): "url", "body". Pin de dato de salida: "response" (JSON parseado o texto crudo).
- conditional: {"field": str, "operator": "contains"|"equals"|"is_empty"|"is_error", "value": str} — evalúa una condición. Pin de flujo de entrada: "default". NO tiene pin de flujo de salida "default" — en su lugar tiene DOS: "true" y "false". Pines de dato de entrada: "field", "value".
- woocommerce: {"connection_id": int, "search_term": str} — busca productos en una tienda WooCommerce conectada. Pines de flujo: entrada "default", salida "default". Pin de dato de entrada: "search_term". Pines de dato de salida: "result" (texto formateado con la lista de productos), "count" (número de productos encontrados).
- set: {"name": str} — guarda un valor en una variable con nombre, referenciable luego como {{name}}. Pines de flujo: entrada "default", salida "default". Pin de dato de entrada (opcional): "value" — si no se conecta, usa la salida del nodo anterior en el flujo.
- get: {"name": str} — nodo puro (SIN pines de flujo, ni entrada ni salida) que expone el valor de una variable ya guardada. Pin de dato de salida: "default".
- end: {"template": str} — termina el flujo y devuelve el resultado de sustituir plantillas en 'template'. Pin de flujo de entrada: "default". Sin salidas.

EDGES: cada edge es {"from": node_id, "to": node_id, "fromHandle": pin_id, "toHandle": pin_id, "kind": "flow"|"data"}. Un edge "flow" define qué nodo se ejecuta después. Un edge "data" conecta la salida nombrada de un nodo directamente al campo de entrada nombrado de otro (alternativa a escribir {{node_id.field}} a mano).

PLANTILLAS: cualquier campo de texto no conectado por un edge "data" puede usar {{nombre}} (variable de un Set, o parámetro de Start) o {{node_id.campo}} (un campo específico de la salida de otro nodo) para insertar valores dinámicamente.

POSICIÓN: el campo "position" de cada nodo es opcional — si lo omites, se calcula automáticamente. No inventes coordenadas de píxeles.

REGLAS: debe haber exactamente un nodo "start" y al menos un nodo "end". Todo id de nodo debe ser único. Todo "from"/"to" de un edge debe apuntar a un id de nodo que exista en el grafo."""

_FLOW_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nombre del flujo."},
        "graph_json": {
            "type": "object",
            "description": 'El grafo del flujo: {"nodes": [...], "edges": [...]}. Ver la descripción de la herramienta para el formato exacto de cada tipo de nodo y edge.',
        },
        "description": {"type": "string", "description": "Descripción opcional del flujo."},
        "flow_id": {"type": "integer", "description": "Si se pasa, actualiza este flujo existente en lugar de crear uno nuevo."},
        "agent_id": {
            "type": "integer",
            "description": "El agente dueño del flujo. Opcional si esta herramienta se llama desde dentro de la ejecución de un agente (se detecta solo); requerido si se llama desde el asistente principal para crear un flujo en otro agente.",
        },
    },
    "required": ["name", "graph_json"],
}


def _resolve_agent_id(agent_id: int | None, channel_id: str | None) -> int | None:
    if agent_id is not None:
        return agent_id
    if channel_id:
        match = _CHANNEL_AGENT_RE.match(channel_id)
        if match:
            return int(match.group(1))
    return None


def _get_db(brain):
    if brain and brain.skill_manager and brain.skill_manager.database:
        return brain.skill_manager.database
    return None


def _auto_layout(nodes: list[dict], edges: list[dict]) -> None:
    """Fills in `position` for any node missing one, via BFS depth over
    flow-kind edges from the start node. Mutates `nodes` in place. Never
    touches a node that already has a position."""
    start_id = next((n["id"] for n in nodes if n.get("type") == "start"), None)

    flow_adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("kind", "flow") == "flow":
            flow_adjacency.setdefault(edge["from"], []).append(edge["to"])

    depth: dict[str, int] = {}
    if start_id is not None:
        depth[start_id] = 0
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for neighbor in flow_adjacency.get(current, []):
                if neighbor not in depth:
                    depth[neighbor] = depth[current] + 1
                    queue.append(neighbor)

    column_counts: dict[int, int] = {}
    for node in nodes:
        if node.get("position"):
            continue
        node_depth = depth.get(node["id"], 0)
        index_in_column = column_counts.get(node_depth, 0)
        column_counts[node_depth] = index_in_column + 1
        node["position"] = {"x": node_depth * 260, "y": index_in_column * 140}


@tool(
    name="create_or_update_agent_flow",
    description=_FLOW_TOOL_DESCRIPTION,
    parameters=_FLOW_TOOL_PARAMETERS,
    category="agents",
)
async def create_or_update_agent_flow(
    name: str,
    graph_json: dict,
    description: str = "",
    flow_id: int | None = None,
    agent_id: int | None = None,
    _brain=None,
    _channel_id: str | None = None,
    **kwargs,
) -> str:
    resolved_agent_id = _resolve_agent_id(agent_id, _channel_id)
    if resolved_agent_id is None:
        return "No se pudo determinar a qué agente pertenece este flujo — pasa agent_id explícitamente."

    db = _get_db(_brain)
    if db is None:
        return "Error: base de datos no disponible."

    nodes = graph_json.get("nodes", [])
    edges = graph_json.get("edges", [])
    _auto_layout(nodes, edges)

    errors = validate_graph(graph_json)
    if errors:
        return "El grafo del flujo tiene errores:\n- " + "\n- ".join(errors)

    graph_str = json.dumps(graph_json)

    if flow_id is not None:
        existing = await db.get_flow(flow_id)
        if not existing or existing["agent_id"] != resolved_agent_id:
            return f"No se encontró el flujo {flow_id} para este agente."
        await db.update_flow(flow_id, agent_id=resolved_agent_id, name=name, description=description, graph_json=graph_str)
        return f"Flujo '{name}' (id {flow_id}) actualizado. Ábrelo en Agentes → Flujos para verlo, o pídeme que lo pruebe."

    new_id = await db.create_flow(agent_id=resolved_agent_id, name=name, description=description, graph_json=graph_str)
    return f"Flujo '{name}' creado (id {new_id}). Ábrelo en Agentes → Flujos para verlo, o pídeme que lo pruebe."
