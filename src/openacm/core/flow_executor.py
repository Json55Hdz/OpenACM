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

# Group 1: the base name (a param or an output/node id). Group 2: the rest
# of the path, verbatim (e.g. ".current_condition[0].temp_C") — walked one
# segment at a time by _walk_template_path, not captured segment-by-segment
# here, since a path can mix an arbitrary number of ".field" and "[N]" hops.
_TEMPLATE_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)((?:\.[a-zA-Z0-9_]+|\[\d+\])*)\}\}")
_TEMPLATE_PATH_SEGMENT_RE = re.compile(r"\.([a-zA-Z0-9_]+)|\[(\d+)\]")

# Every early-return string inside FlowExecutor.run() that signals failure
# (missing Start node, missing param, cycle guard, unknown node/type, a node
# handler's exception) starts with one of these two prefixes. Centralized
# here so callers (the /test endpoint) can tell a real failure apart from a
# successful End-node result without re-deriving or drifting from the exact
# strings run() produces.
_ERROR_PREFIXES = ("Error: ", "Error in node ")


def is_error_result(result: str) -> bool:
    """True if `result` is one of run()'s error-path strings rather than an
    End node's actual template output. (An End template that itself starts
    with one of these prefixes would be misclassified — an accepted, narrow
    edge case, not worth widening run()'s return contract to avoid.)"""
    return result.startswith(_ERROR_PREFIXES)


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


# Mirrors classifyPin() in frontend/components/flow-editor/node-types.tsx —
# keep both in sync when either changes. Target = a node's flow-in/data-in
# handle ids; source = its flow-out/data-out handle ids.
KNOWN_NODE_TYPES = {"start", "http", "conditional", "woocommerce", "set", "get", "end"}

NODE_TARGET_HANDLES: dict[str, set[str]] = {
    "start": set(),
    "http": {"default", "url", "body"},
    "conditional": {"default", "field", "value"},
    "woocommerce": {"default", "search_term"},
    "set": {"default", "value"},
    "get": set(),
    "end": {"default"},
}

NODE_SOURCE_HANDLES: dict[str, set[str]] = {
    "start": {"default"},
    "http": {"default"},
    "conditional": {"true", "false"},
    "woocommerce": {"default", "result", "count"},
    "set": {"default"},
    "get": {"default"},
    "end": set(),
}


def validate_graph(graph: dict) -> list[str]:
    """Structural validation of a flow's graph_json, beyond just "is this
    valid JSON" and "does it have a cycle" (detect_cycle, above). Collects
    every problem found rather than stopping at the first, so an AI (or a
    human) fixing a bad graph sees everything wrong in one round-trip.
    Returns an empty list when the graph is valid.
    """
    errors: list[str] = []
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if not isinstance(nodes, list):
        return ["graph_json.nodes must be a list"]
    if not isinstance(edges, list):
        return ["graph_json.edges must be a list"]

    node_ids_seen: set[str] = set()
    node_types: dict[str, str] = {}
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            errors.append("A node is missing its 'id'")
            continue
        if node_id in node_ids_seen:
            errors.append(f"Duplicate node id: '{node_id}' — node ids must be unique")
        node_ids_seen.add(node_id)

        node_type = node.get("type")
        if node_type not in KNOWN_NODE_TYPES:
            errors.append(f"Node '{node_id}' has unknown type '{node_type}' — must be one of {sorted(KNOWN_NODE_TYPES)}")
        else:
            node_types[node_id] = node_type

    start_count = sum(1 for n in nodes if n.get("type") == "start")
    if start_count != 1:
        errors.append(f"A flow must have exactly one 'start' node (found {start_count})")

    end_count = sum(1 for n in nodes if n.get("type") == "end")
    if end_count == 0:
        errors.append("A flow must have at least one 'end' node")

    for edge in edges:
        from_id, to_id = edge.get("from"), edge.get("to")
        from_ok = from_id in node_types
        to_ok = to_id in node_types
        if not from_ok:
            errors.append(f"Edge references unknown source node '{from_id}'")
        if not to_ok:
            errors.append(f"Edge references unknown target node '{to_id}'")
        if not (from_ok and to_ok):
            continue  # handle-id checks below would just cascade confusingly

        from_handle = edge.get("fromHandle", "default")
        if from_handle not in NODE_SOURCE_HANDLES.get(node_types[from_id], set()):
            errors.append(f"'{from_handle}' is not a valid output pin on node '{from_id}' (type '{node_types[from_id]}')")

        to_handle = edge.get("toHandle", "default")
        if to_handle not in NODE_TARGET_HANDLES.get(node_types[to_id], set()):
            errors.append(f"'{to_handle}' is not a valid input pin on node '{to_id}' (type '{node_types[to_id]}')")

    cycle = detect_cycle(graph)
    if cycle:
        errors.append(f"Flow has a cycle: {' -> '.join(cycle)}")

    return errors


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


def _walk_template_path(value: Any, path: str) -> tuple[bool, Any]:
    """Walks a dotted/bracketed path (e.g. ".current_condition[0].temp_C")
    into `value`, one segment at a time. A ".field" segment must land on a
    dict with that key; a "[N]" segment must land on a list with that
    index. Returns (False, None) the instant any segment can't be
    resolved — never a partial result."""
    for field, index in _TEMPLATE_PATH_SEGMENT_RE.findall(path):
        if field:
            if not (isinstance(value, dict) and field in value):
                return False, None
            value = value[field]
        else:
            idx = int(index)
            if not (isinstance(value, list) and 0 <= idx < len(value)):
                return False, None
            value = value[idx]
    return True, value


def substitute_templates(template: str, params: dict[str, Any], outputs: dict[str, Any]) -> str:
    """Replace {{name}} / {{node_id.field}} / {{node_id.field[0].sub}}
    references in template.

    {{name}} (no path): checks params first, then node outputs, for an
    exact key match — substitutes the whole value (stringified) if found
    in either, else the literal marker "[missing: name]".

    {{node_id<path>}} (with a dotted/bracketed path): only looks in node
    outputs, walking each ".field" as a dict-key lookup and each "[N]" as a
    list-index lookup (see _walk_template_path). If any segment along the
    path can't be resolved (unknown node_id, wrong container type, missing
    key, out-of-range index), substitutes "[missing: node_id<path>]" —
    never a silent empty string or partial value.
    """
    def _replace(match: re.Match) -> str:
        name, path = match.group(1), match.group(2)
        if not path:
            if name in params:
                return str(params[name])
            if name in outputs:
                return _stringify_whole_value(outputs[name])
            return f"[missing: {name}]"
        if name not in outputs:
            return f"[missing: {name}{path}]"
        found, value = _walk_template_path(outputs[name], path)
        if not found:
            return f"[missing: {name}{path}]"
        return str(value)

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
        # Normalize once, here: the spec's global constraint says a node with
        # no "config" key is treated as config: {} (and validate_graph
        # deliberately does not reject one). Every downstream handler and
        # lookup reads its node out of THIS dict, so defaulting it at this
        # single point is what actually honors that constraint — otherwise a
        # config-less node raises a raw KeyError mid-run, which for an agent
        # flow tool surfaces as a broken chat rather than a flow error.
        nodes = {n["id"]: {**n, "config": n.get("config", {})} for n in graph.get("nodes", [])}
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
