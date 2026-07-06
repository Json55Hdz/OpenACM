"""
FlowExecutor — interprets a node-graph flow (built visually by the user)
and runs it as a tool call for an Agent.

A flow is a linear chain of nodes with exactly one possible branch point
(a Conditional node, which has two outgoing edges: "true" and "false").
There are no loops, no multi-input nodes, and no rejoined branches — see
docs/superpowers/specs/2026-07-05-agent-node-flows-design.md for the full
design rationale.
"""
import json as _json
import re
from typing import Any, Callable, Coroutine

import httpx

_TEMPLATE_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}")


def substitute_templates(template: str, params: dict[str, Any], outputs: dict[str, Any]) -> str:
    """Replace {{name}} / {{node_id.field}} references in template.

    {{name}} (no dot): checks params first, then node outputs, for an exact
    key match — substitutes the whole value (stringified) if found in
    either, else the literal marker "[missing: name]".

    {{node_id.field}} (with a dot): only looks in node outputs. If that
    node's output is a dict and field is one of its keys, substitutes that
    key's value (stringified); in every other case (unknown node_id,
    non-dict output, or field not a key), substitutes
    "[missing: node_id.field]" — never a silent empty string.
    """
    def _replace(match: re.Match) -> str:
        name, field = match.group(1), match.group(2)
        if field is None:
            if name in params:
                return str(params[name])
            if name in outputs:
                return str(outputs[name])
            return f"[missing: {name}]"
        value = outputs.get(name)
        if isinstance(value, dict) and field in value:
            return str(value[field])
        return f"[missing: {name}.{field}]"

    return _TEMPLATE_RE.sub(_replace, template)


class FlowExecutor:
    """Interprets and runs one flow's graph_json against a set of params."""

    _CONDITIONAL_OPERATORS = {"contains", "equals", "is_empty", "is_error"}

    def __init__(self, get_connection: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None):
        self.get_connection = get_connection
        self._HANDLERS: dict[str, Callable] = {
            "http": FlowExecutor._run_http_node,
            "conditional": FlowExecutor._run_conditional_node,
            "woocommerce": FlowExecutor._run_woocommerce_node,
        }

    async def _run_http_node(self, node: dict, params: dict, outputs: dict) -> Any:
        cfg = node["config"]
        url = substitute_templates(cfg["url"], params, outputs)
        method = cfg.get("method", "GET").upper()
        headers = {k: substitute_templates(v, params, outputs) for k, v in (cfg.get("headers") or {}).items()}
        body = cfg.get("body")
        if body:
            body = substitute_templates(body, params, outputs)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, headers=headers, content=body)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return response.text

    async def _run_conditional_node(self, node: dict, params: dict, outputs: dict) -> dict:
        cfg = node["config"]
        operator = cfg["operator"]
        if operator not in self._CONDITIONAL_OPERATORS:
            raise ValueError(f"Unknown conditional operator: {operator}")

        resolved = substitute_templates(cfg["field"], params, outputs)
        compare_value = cfg.get("value", "")

        if operator == "contains":
            branch = compare_value in resolved
        elif operator == "equals":
            branch = resolved == compare_value
        elif operator == "is_empty":
            branch = resolved == ""
        else:  # is_error
            branch = resolved.lower().startswith("error")

        return {"branch": branch, "passthrough": resolved}

    async def _run_woocommerce_node(self, node: dict, params: dict, outputs: dict) -> str:
        cfg = node["config"]
        search_term = substitute_templates(cfg["search_term"], params, outputs)

        if not self.get_connection:
            raise RuntimeError("No connection lookup configured for this flow executor")

        connection = await self.get_connection(cfg["connection_id"])
        if not connection:
            raise RuntimeError(f"Connection {cfg['connection_id']} not found")

        conn_config = _json.loads(connection["config"])
        woo_url = conn_config["url"].rstrip("/")
        if not woo_url.endswith("/wp-json/wc/v3/products"):
            woo_url += "/wp-json/wc/v3/products"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                woo_url,
                params={"search": search_term},
                auth=(conn_config["consumer_key"], conn_config["consumer_secret"]),
            )
            response.raise_for_status()
            products = response.json()

        if not products:
            return f"No products found for query: '{search_term}'."

        output = [f"Search results for '{search_term}':"]
        for p in products[:5]:
            stock = p.get("stock_quantity")
            stock_text = str(stock) if stock is not None else ("In stock" if p.get("manage_stock") is False else "Out of stock")

            raw_desc = p.get("short_description") or p.get("description", "")
            clean_desc = re.sub(r"<[^>]+>", " ", raw_desc).strip()
            clean_desc = re.sub(r"\s+", " ", clean_desc)

            output.append(f"- Product: {p.get('name')}")
            output.append(f"  Price: ${p.get('price')}")
            output.append(f"  Stock: {stock_text}")
            if clean_desc:
                shortened = clean_desc[:300] + "..." if len(clean_desc) > 300 else clean_desc
                output.append(f"  Description: {shortened}")
            output.append(f"  Link: {p.get('permalink')}")

        return "\n".join(output)

    async def run(self, graph: dict, params: dict) -> str:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        edges_by_target: dict[str, str] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]
            edges_by_target[edge["to"]] = edge["from"]

        start_node = next((n for n in nodes.values() if n["type"] == "start"), None)
        if not start_node:
            return "Error: flow has no Start node"

        for param_def in start_node["config"].get("parameters", []):
            if param_def.get("required") and param_def["name"] not in params:
                return f"Error: missing required parameter '{param_def['name']}'"

        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")

        while current_id:
            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'"

            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs)

            if node["type"] == "set":
                source_id = edges_by_target.get(node["id"])
                if source_id and source_id in outputs:
                    value = outputs[source_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            if node["type"] == "get":
                name = node["config"]["name"]
                if name in outputs:
                    outputs[node["id"]] = outputs[name]
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'"

            try:
                result = await handler(self, node, params, outputs)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}"

            if node["type"] == "conditional":
                outputs[node["id"]] = result["passthrough"]
                current_id = edges_by_source.get(node["id"], {}).get("true" if result["branch"] else "false")
            else:
                outputs[node["id"]] = result
                current_id = edges_by_source.get(node["id"], {}).get("default")

        return "Error: flow ended without reaching an End node"
