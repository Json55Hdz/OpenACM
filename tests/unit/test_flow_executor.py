"""Tests for FlowExecutor's core mechanics: template substitution and the
minimal Start-to-End graph walk. Node-type-specific handlers (HTTP,
Conditional, WooCommerce) are tested in their own dedicated test files."""
from unittest.mock import AsyncMock, MagicMock, patch

from openacm.core.flow_executor import FlowExecutor, substitute_templates


class TestSubstituteTemplates:
    def test_bare_param_name_substitutes_whole_value(self):
        result = substitute_templates("Hello {{name}}", params={"name": "Ana"}, outputs={})
        assert result == "Hello Ana"

    def test_bare_node_id_substitutes_whole_output(self):
        result = substitute_templates("Result: {{http1}}", params={}, outputs={"http1": "some text"})
        assert result == "Result: some text"

    def test_node_id_dot_field_looks_up_json_key(self):
        result = substitute_templates(
            "Price: {{http1.price}}", params={}, outputs={"http1": {"price": "19.99", "name": "Widget"}}
        )
        assert result == "Price: 19.99"

    def test_dot_field_on_non_dict_output_is_missing_marker(self):
        result = substitute_templates(
            "{{woo1.price}}", params={}, outputs={"woo1": "Search results for 'x':\n- Product: Widget"}
        )
        assert result == "[missing: woo1.price]"

    def test_dot_field_not_a_key_in_dict_is_missing_marker(self):
        result = substitute_templates(
            "{{http1.nonexistent}}", params={}, outputs={"http1": {"price": "19.99"}}
        )
        assert result == "[missing: http1.nonexistent]"

    def test_unknown_bare_name_is_missing_marker(self):
        result = substitute_templates("{{unknown}}", params={}, outputs={})
        assert result == "[missing: unknown]"

    def test_param_takes_priority_over_a_same_named_node_output(self):
        # params and outputs are separate namespaces for bare (no-dot) lookups;
        # params checked first per the spec's documented precedence.
        result = substitute_templates("{{x}}", params={"x": "from-param"}, outputs={"x": "from-node"})
        assert result == "from-param"

    def test_multiple_substitutions_in_one_template(self):
        result = substitute_templates(
            "{{name}} bought {{http1.item}}", params={"name": "Ana"}, outputs={"http1": {"item": "Widget"}}
        )
        assert result == "Ana bought Widget"


class TestFlowExecutorStartToEnd:
    async def test_minimal_start_to_end_flow_returns_end_template(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "required": True}]}},
                {"id": "end", "type": "end", "config": {"template": "You asked about {{producto}}"}},
            ],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
        }
        executor = FlowExecutor()

        result = await executor.run(graph, params={"producto": "zapatos"})

        assert result == "You asked about zapatos"

    async def test_missing_required_param_returns_error_without_running(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "required": True}]}},
                {"id": "end", "type": "end", "config": {"template": "{{producto}}"}},
            ],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
        }
        executor = FlowExecutor()

        result = await executor.run(graph, params={})

        assert "producto" in result
        assert result.startswith("Error")

    async def test_flow_with_no_start_node_returns_error(self):
        graph = {"nodes": [{"id": "end", "type": "end", "config": {"template": "x"}}], "edges": []}
        executor = FlowExecutor()

        result = await executor.run(graph, params={})

        assert result.startswith("Error")


def _http_graph(url="https://example.com/api", method="GET", headers=None, body=None):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            {"id": "http1", "type": "http", "config": {"url": url, "method": method, "headers": headers or {}, "body": body}},
            {"id": "end", "type": "end", "config": {"template": "{{http1.status}}"}},
        ],
        "edges": [
            {"from": "start", "to": "http1", "fromHandle": "default"},
            {"from": "http1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestHttpNode:
    async def test_json_response_is_parsed_and_fields_are_addressable(self):
        graph = _http_graph()
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "ok"

    async def test_non_json_response_is_raw_text_and_has_no_dot_fields(self):
        graph = _http_graph()
        graph["nodes"][2]["config"]["template"] = "{{http1}}"
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "plain body"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "plain body"

    async def test_http_error_stops_the_flow_and_returns_an_error_string(self):
        graph = _http_graph()
        mock_client = AsyncMock()
        mock_client.request.side_effect = Exception("connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result.startswith("Error in node 'http1'")
        assert "connection refused" in result

    async def test_url_and_body_support_template_substitution(self):
        graph = _http_graph(url="https://example.com/{{producto}}", body='{"q": "{{producto}}"}')
        graph["nodes"][0]["config"]["parameters"] = [{"name": "producto", "type": "string", "required": True}]
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            executor = FlowExecutor()
            await executor.run(graph, params={"producto": "zapatos"})

        call_kwargs = mock_client.request.call_args
        assert "zapatos" in call_kwargs.args[1] or "zapatos" in str(call_kwargs)


def _conditional_graph(operator, value, field="{{start_value}}"):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "start_value", "type": "string", "required": True}]}},
            {"id": "cond1", "type": "conditional", "config": {"field": field, "operator": operator, "value": value}},
            {"id": "end_true", "type": "end", "config": {"template": "YES: {{cond1}}"}},
            {"id": "end_false", "type": "end", "config": {"template": "NO: {{cond1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "cond1", "fromHandle": "default"},
            {"from": "cond1", "to": "end_true", "fromHandle": "true"},
            {"from": "cond1", "to": "end_false", "fromHandle": "false"},
        ],
    }


class TestConditionalNode:
    async def test_contains_operator_true_branch(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("contains", "zap"), params={"start_value": "zapatos"})
        assert result == "YES: zapatos"

    async def test_contains_operator_false_branch(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("contains", "camisa"), params={"start_value": "zapatos"})
        assert result == "NO: zapatos"

    async def test_equals_operator(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("equals", "zapatos"), params={"start_value": "zapatos"})
        assert result == "YES: zapatos"

    async def test_is_empty_operator_true(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("is_empty", ""), params={"start_value": ""})
        assert result == "YES: "

    async def test_is_empty_operator_false(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("is_empty", ""), params={"start_value": "zapatos"})
        assert result == "NO: zapatos"

    async def test_is_error_operator(self):
        graph = _conditional_graph("is_error", "", field="{{prev}}")
        graph["nodes"][0]["config"]["parameters"] = []
        graph["nodes"][1]["config"]["field"] = "{{missing_node}}"
        executor = FlowExecutor()
        result = await executor.run(graph, params={})
        # "{{missing_node}}" resolves to "[missing: missing_node]" which starts with neither
        # "error" — this exercises is_error's false path using the missing-marker text itself.
        assert result == "NO: [missing: missing_node]"

    async def test_unknown_operator_is_an_error(self):
        graph = _conditional_graph("bogus_operator", "x")
        executor = FlowExecutor()
        result = await executor.run(graph, params={"start_value": "zapatos"})
        assert result.startswith("Error in node 'cond1'")

    async def test_passthrough_output_is_the_evaluated_value_not_the_boolean(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("contains", "zap"), params={"start_value": "zapatos"})
        # end_true's template is "YES: {{cond1}}" — if the stored output were the
        # boolean True/False instead of the passthrough string, this would read "YES: True".
        assert result == "YES: zapatos"


import json as _json


def _woo_graph(connection_id=1, search_term="{{producto}}"):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "required": True}]}},
            {"id": "woo1", "type": "woocommerce", "config": {"connection_id": connection_id, "search_term": search_term}},
            {"id": "end", "type": "end", "config": {"template": "{{woo1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "woo1", "fromHandle": "default"},
            {"from": "woo1", "to": "end", "fromHandle": "default"},
        ],
    }


def _connection_row(url="https://tienda.example.com", ck="ck_123", cs="cs_456"):
    return {"id": 1, "config": _json.dumps({"url": url, "consumer_key": ck, "consumer_secret": cs})}


class TestWooCommerceNode:
    async def test_formats_top_5_products(self):
        products = [
            {"name": "Zapatos rojos", "price": "49.99", "stock_quantity": 3, "manage_stock": True,
             "short_description": "<p>Comodos y <b>bonitos</b></p>", "permalink": "https://tienda.example.com/zapatos-rojos"},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = products
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert "Zapatos rojos" in result
        assert "$49.99" in result
        assert "Comodos y bonitos" in result  # HTML stripped
        assert "https://tienda.example.com/zapatos-rojos" in result

    async def test_no_products_found_message(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result = await executor.run(_woo_graph(), params={"producto": "inexistente"})

        assert "No products found" in result

    async def test_missing_connection_is_an_error(self):
        async def get_connection(conn_id):
            return None

        executor = FlowExecutor(get_connection=get_connection)
        result = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert result.startswith("Error in node 'woo1'")

    async def test_no_get_connection_configured_is_an_error(self):
        executor = FlowExecutor()  # get_connection defaults to None
        result = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert result.startswith("Error in node 'woo1'")

    async def test_search_uses_basic_auth_with_connection_credentials(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row(ck="my_key", cs="my_secret")

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            await executor.run(_woo_graph(), params={"producto": "x"})

        _, call_kwargs = mock_client.get.call_args
        assert call_kwargs["auth"] == ("my_key", "my_secret")


def _set_graph(source_type="http", var_name="mi_variable"):
    """Start -> source_node -> Set(name=var_name) -> End(template referencing the set)."""
    source_node = {"id": "src1", "type": source_type, "config": {}}
    if source_type == "http":
        source_node["config"] = {"url": "https://example.com", "method": "GET"}
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            source_node,
            {"id": "var1", "type": "set", "config": {"name": var_name}},
            {"id": "end", "type": "end", "config": {"template": "Valor: {{" + var_name + "}}"}},
        ],
        "edges": [
            {"from": "start", "to": "src1", "fromHandle": "default"},
            {"from": "src1", "to": "var1", "fromHandle": "default"},
            {"from": "var1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestSetNode:
    async def test_aliases_the_incoming_nodes_output_under_the_declared_name(self):
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola mundo"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(_set_graph(), params={})

        assert result == "Valor: hola mundo"

    async def test_variable_output_is_also_addressable_by_its_own_node_id(self):
        """{{var1}} (the node's own id) must still work too — the set
        node is stored under both keys, not just the friendly name."""
        graph = _set_graph()
        graph["nodes"][3]["config"]["template"] = "Por id: {{var1}}"
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola mundo"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "Por id: hola mundo"

    async def test_variable_with_no_incoming_edge_aliases_none(self):
        """A Set node placed directly after Start (or otherwise with no
        real predecessor output to alias) resolves to the missing-marker,
        not a crash — substitute_templates already handles a None/missing
        outputs value via its existing missing-marker logic once the key
        is simply absent, so the set handler stores nothing for a
        node with no incoming edge."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "var1", "type": "set", "config": {"name": "huerfana"}},
                {"id": "end", "type": "end", "config": {"template": "{{huerfana}}"}},
            ],
            "edges": [
                {"from": "start", "to": "var1", "fromHandle": "default"},
                {"from": "var1", "to": "end", "fromHandle": "default"},
            ],
        }
        executor = FlowExecutor()
        result = await executor.run(graph, params={})
        assert result == "[missing: huerfana]"

    async def test_two_variables_with_the_same_name_last_one_wins(self):
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "segundo valor"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "var1", "type": "set", "config": {"name": "dup"}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
                {"id": "var2", "type": "set", "config": {"name": "dup"}},
                {"id": "end", "type": "end", "config": {"template": "{{dup}}"}},
            ],
            "edges": [
                {"from": "start", "to": "var1", "fromHandle": "default"},
                {"from": "var1", "to": "http1", "fromHandle": "default"},
                {"from": "http1", "to": "var2", "fromHandle": "default"},
                {"from": "var2", "to": "end", "fromHandle": "default"},
            ],
        }

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "segundo valor"


def _get_graph(get_name="mi_variable"):
    """Start -> HTTP -> Set(name=get_name) -> Get(name=get_name) -> End(references the Get node's own id)."""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            {"id": "src1", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
            {"id": "set1", "type": "set", "config": {"name": get_name}},
            {"id": "get1", "type": "get", "config": {"name": get_name}},
            {"id": "end", "type": "end", "config": {"template": "Por id del Get: {{get1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "src1", "fromHandle": "default"},
            {"from": "src1", "to": "set1", "fromHandle": "default"},
            {"from": "set1", "to": "get1", "fromHandle": "default"},
            {"from": "get1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestGetNode:
    async def test_get_reads_a_previously_set_value_via_its_own_node_id(self):
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola desde get"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(_get_graph(), params={})

        assert result == "Por id del Get: hola desde get"

    async def test_get_by_friendly_name_directly_also_works(self):
        graph = _get_graph()
        graph["nodes"][4]["config"]["template"] = "Por nombre: {{mi_variable}}"
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola desde get"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "Por nombre: hola desde get"

    async def test_get_before_any_set_with_that_name_resolves_to_missing_marker(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "get1", "type": "get", "config": {"name": "nunca_seteada"}},
                {"id": "end", "type": "end", "config": {"template": "{{get1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "get1", "fromHandle": "default"},
                {"from": "get1", "to": "end", "fromHandle": "default"},
            ],
        }
        executor = FlowExecutor()
        result = await executor.run(graph, params={})
        assert result == "[missing: get1]"
