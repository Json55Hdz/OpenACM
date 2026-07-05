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
