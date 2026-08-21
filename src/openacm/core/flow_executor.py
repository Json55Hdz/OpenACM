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


def detect_cycle(graph: dict) -> list[str] | None:
    """DFS cycle detection over the flow's directed edges (ignoring
    fromHandle — both a Conditional's true and false edges are just
    directed edges for this purpose). Returns the node ids forming a
    cycle if one exists, else None.

    A merge (two edges into the same target) is NOT a cycle: the first
    path to reach a node finishes exploring it (turns it BLACK) before a
    second path can reach it, so the second arrival sees BLACK, not GRAY,
    and is correctly not treated as a cycle.
    """
    adjacency: dict[str, list[str]] = {}
    for edge in graph.get("edges", []):
        # Data edges carry no execution-order meaning and can legitimately
        # point "backward" relative to flow order (e.g. Set aliasing an
        # earlier node's output) — only flow edges can ever form a real
        # execution cycle.
        if edge.get("kind", "flow") != "flow":
            continue
        adjacency.setdefault(edge["from"], []).append(edge["to"])

    node_ids = [n["id"] for n in graph.get("nodes", [])]
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node_id: WHITE for node_id in node_ids}
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        color[node_id] = GRAY
        stack.append(node_id)
        for neighbor in adjacency.get(node_id, []):
            neighbor_color = color.get(neighbor, WHITE)
            if neighbor_color == GRAY:
                cycle_start = stack.index(neighbor)
                return stack[cycle_start:]
            if neighbor_color == WHITE:
                found = visit(neighbor)
                if found:
                    return found
        stack.pop()
        color[node_id] = BLACK
        return None

    for node_id in node_ids:
        if color[node_id] == WHITE:
            found = visit(node_id)
            if found:
                return found
    return None


def _stringify_whole_value(value: Any) -> str:
    """Stringify a whole (non-narrowed) value for template/text substitution.

    A dict-shaped value that exposes a "result" key (today, only
    WooCommerce's structured output) stringifies to that key's value
    specifically — this keeps every {{woo1}} reference, and every data
    edge wired from WooCommerce's flow-out/default pin, reading as the
    human-formatted listing instead of the dict's Python repr (e.g.
    "{'result': '...', 'count': 2}"). This is a narrow, explicit special
    case, not a general change to whole-value stringification for every
    dict-shaped value.

    Shared by substitute_templates()'s bare {{name}} branch and
    resolve_field()'s data-edge whole-value fallback so a {{woo1}}
    template reference and a data edge wired from the same node's default
    pin agree on the same resolved text — see the FINAL whole-branch
    review finding this fixes: resolve_field() used to call str(value)
    directly here, diverging from substitute_templates.
    """
    if isinstance(value, dict) and "result" in value:
        return str(value["result"])
    return str(value)


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
                return _stringify_whole_value(outputs[name])
            return f"[missing: {name}]"
        value = outputs.get(name)
        if isinstance(value, dict) and field in value:
            return str(value[field])
        return f"[missing: {name}.{field}]"

    return _TEMPLATE_RE.sub(_replace, template)


def _resolve_pin_value(
    source_id: str, source_handle: str, nodes: dict[str, dict], outputs: dict[str, Any],
) -> tuple[bool, Any]:
    """Resolve a data edge's source pin to its RAW value (not stringified).
    Returns (True, value) if the source has produced a value, else
    (False, None). Shared by resolve_field() (which stringifies the result
    for template/text fields) and the `set`-node branch in run() (which
    needs the actual typed value — e.g. a WooCommerce result dict — not a
    stringified one), so the Get-node special case below lives in exactly
    one place.

    Get nodes have no flow handles (see the spec's "pure node" section) so
    run()'s flow-walk never visits one and outputs[get_node_id] is never
    populated the normal way. Evaluate the Get's own name-lookup on demand
    instead of expecting it to already be in outputs.
    """
    source_node = nodes.get(source_id)
    if source_node is not None and source_node["type"] == "get":
        name = source_node["config"]["name"]
        if name not in outputs:
            return False, None
        return True, outputs[name]

    if source_id not in outputs:
        return False, None
    value = outputs[source_id]
    if source_handle != "default" and isinstance(value, dict):
        if source_handle not in value:
            return False, None
        return True, value[source_handle]
    return True, value


def resolve_field(
    field_name: str,
    node_id: str,
    cfg: dict,
    data_edges_by_target: dict[tuple[str, str], tuple[str, str]],
    nodes: dict[str, dict],
    params: dict,
    outputs: dict,
) -> str:
    """Resolve one node config field's value, preferring a wired data edge
    over the field's literal value — the "wire wins" rule this spec
    introduces. Falls back to substitute_templates(cfg[field_name], ...)
    exactly as before when no data edge targets this field, so every flow
    saved before this shipped resolves this field identically to before.
    """
    edge_source = data_edges_by_target.get((node_id, field_name))
    if edge_source is None:
        return substitute_templates(cfg[field_name], params, outputs)

    source_id, source_handle = edge_source
    found, value = _resolve_pin_value(source_id, source_handle, nodes, outputs)
    if not found:
        marker = source_id if source_handle == "default" else f"{source_id}.{source_handle}"
        return f"[missing: {marker}]"
    return _stringify_whole_value(value)


class FlowExecutor:
    """Interprets and runs one flow's graph_json against a set of params."""

    _CONDITIONAL_OPERATORS = {"contains", "equals", "is_empty", "is_error"}
    _MAX_NODE_VISITS = 50

    def __init__(self, get_connection: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None):
        self.get_connection = get_connection
        self._HANDLERS: dict[str, Callable] = {
            "http": FlowExecutor._run_http_node,
            "conditional": FlowExecutor._run_conditional_node,
            "woocommerce": FlowExecutor._run_woocommerce_node,
        }

    async def _run_http_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> Any:
        cfg = node["config"]
        url = resolve_field("url", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        method = cfg.get("method", "GET").upper()
        headers = {k: substitute_templates(v, params, outputs) for k, v in (cfg.get("headers") or {}).items()}
        # body is optional (defaults to None, not ""); only route it through
        # resolve_field when there's a literal to template-substitute OR a
        # data edge targets it — otherwise leave it exactly None, matching
        # the pre-existing behavior byte-for-byte for a flow saved before
        # this task shipped.
        if cfg.get("body") or (node["id"], "body") in data_edges_by_target:
            body = resolve_field("body", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        else:
            body = cfg.get("body")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, headers=headers, content=body)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return response.text

    async def _run_conditional_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> dict:
        cfg = node["config"]
        operator = cfg["operator"]
        if operator not in self._CONDITIONAL_OPERATORS:
            raise ValueError(f"Unknown conditional operator: {operator}")

        resolved = resolve_field("field", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        # value has no history of template substitution (it's a raw
        # comparison literal) — only route it through resolve_field when a
        # data edge actually targets it, so a flow saved before this task
        # shipped keeps its literal "value" exactly as-is, never templated.
        if (node["id"], "value") in data_edges_by_target:
            compare_value = resolve_field("value", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        else:
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

    async def _run_woocommerce_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> dict:
        cfg = node["config"]
        search_term = resolve_field("search_term", node["id"], cfg, data_edges_by_target, nodes, params, outputs)

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
            return {"result": f"No products found for query: '{search_term}'.", "count": 0}

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

        return {"result": "\n".join(output), "count": len(products[:5])}

    async def run(self, graph: dict, params: dict) -> tuple[str, dict[str, Any]]:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        # Keyed by (target_node_id, field_name) -> (source_node_id,
        # source_handle) — built only from data edges, consulted by
        # resolve_field() and the set-node branch below. A data edge never
        # goes into edges_by_source: the flow-walk must never follow one.
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]] = {}
        for edge in graph.get("edges", []):
            if edge.get("kind", "flow") == "data":
                data_edges_by_target[(edge["to"], edge.get("toHandle", "value"))] = (
                    edge["from"], edge.get("fromHandle", "default")
                )
            else:
                edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]

        start_node = next((n for n in nodes.values() if n["type"] == "start"), None)
        if not start_node:
            return "Error: flow has no Start node", {}

        for param_def in start_node["config"].get("parameters", []):
            if param_def.get("required") and param_def["name"] not in params:
                return f"Error: missing required parameter '{param_def['name']}'", {}

        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")
        previous_id: str | None = None
        visits = 0

        while current_id:
            visits += 1
            if visits > self._MAX_NODE_VISITS:
                return "Error: flow exceeded maximum node visits (possible cycle)", outputs

            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'", outputs

            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs), outputs

            if node["type"] == "set":
                # A data edge targeting Set's "value" handle wins if one
                # exists — it can alias ANY earlier node's output, not just
                # the immediate flow-predecessor. If none exists (every Set
                # node saved before this task shipped), fall back to the
                # old previous_id behavior exactly as it worked before:
                # previous_id is the node actually visited just before this
                # one IN THIS RUN — correct even when this node has multiple
                # incoming edges in the graph (a merge point after a
                # Conditional's two branches), since only one of those
                # edges is ever the real predecessor on any given run.
                value_edge = data_edges_by_target.get((node["id"], "value"))
                if value_edge is not None:
                    source_id, source_handle = value_edge
                    found, value = _resolve_pin_value(source_id, source_handle, nodes, outputs)
                    if found:
                        outputs[node["id"]] = value
                        outputs[node["config"]["name"]] = value
                elif previous_id and previous_id in outputs:
                    value = outputs[previous_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            if node["type"] == "get":
                name = node["config"]["name"]
                if name in outputs:
                    outputs[node["id"]] = outputs[name]
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'", outputs

            try:
                result = await handler(self, node, params, outputs, data_edges_by_target, nodes)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}", outputs

            if node["type"] == "conditional":
                outputs[node["id"]] = result["passthrough"]
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("true" if result["branch"] else "false")
            else:
                outputs[node["id"]] = result
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")

        return "Error: flow ended without reaching an End node", outputs
