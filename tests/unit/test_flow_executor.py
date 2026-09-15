"""Tests for FlowExecutor's core mechanics: template substitution and the
minimal Start-to-End graph walk. Node-type-specific handlers (HTTP,
Conditional, WooCommerce) are tested in their own dedicated test files."""
from unittest.mock import AsyncMock, MagicMock, patch

from openacm.core.flow_executor import FlowExecutor, is_error_result, substitute_templates


class TestDetectCycle:
    def test_linear_flow_has_no_cycle(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "http1"}, {"id": "end"}],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default"},
                {"from": "http1", "to": "end", "fromHandle": "default"},
            ],
        }
        assert detect_cycle(graph) is None

    def test_a_valid_merge_is_not_a_cycle(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "cond1"}, {"id": "merge1"}, {"id": "end"}],
            "edges": [
                {"from": "start", "to": "cond1", "fromHandle": "default"},
                {"from": "cond1", "to": "merge1", "fromHandle": "true"},
                {"from": "cond1", "to": "merge1", "fromHandle": "false"},
                {"from": "merge1", "to": "end", "fromHandle": "default"},
            ],
        }
        assert detect_cycle(graph) is None

    def test_a_real_cycle_is_detected_and_names_its_nodes(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"from": "start", "to": "a", "fromHandle": "default"},
                {"from": "a", "to": "b", "fromHandle": "default"},
                {"from": "b", "to": "c", "fromHandle": "default"},
                {"from": "c", "to": "a", "fromHandle": "default"},
            ],
        }
        cycle = detect_cycle(graph)
        assert cycle is not None
        assert set(cycle) == {"a", "b", "c"}

    def test_a_self_loop_is_detected(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "a"}],
            "edges": [{"from": "a", "to": "a", "fromHandle": "default"}],
        }
        assert detect_cycle(graph) == ["a"]

    def test_a_cycle_in_a_disconnected_component_is_detected(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "end"}, {"id": "x"}, {"id": "y"}],
            "edges": [
                {"from": "start", "to": "end", "fromHandle": "default"},
                {"from": "x", "to": "y", "fromHandle": "default"},
                {"from": "y", "to": "x", "fromHandle": "default"},
            ],
        }
        cycle = detect_cycle(graph)
        assert cycle is not None
        assert set(cycle) == {"x", "y"}

    def test_a_backward_data_edge_is_never_flagged_as_a_cycle(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "a"}, {"id": "b"}],
            "edges": [
                {"from": "start", "to": "a", "fromHandle": "default", "kind": "flow"},
                {"from": "a", "to": "b", "fromHandle": "default", "kind": "flow"},
                # A data edge pointing "backward" from b to a is allowed —
                # data edges carry no execution order and must never be
                # mistaken for a real cycle.
                {"from": "b", "to": "a", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        assert detect_cycle(graph) is None


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

    def test_bare_reference_to_a_dict_with_a_result_key_resolves_to_that_key(self):
        result = substitute_templates(
            "{{woo1}}", params={}, outputs={"woo1": {"result": "formatted text", "count": 3}}
        )
        assert result == "formatted text"

    def test_bare_reference_to_a_dict_without_a_result_key_stringifies_the_whole_dict_unchanged(self):
        # Proves the special case is narrow: a dict-shaped output with no
        # "result" key still stringifies exactly as it always has.
        result = substitute_templates(
            "{{http1}}", params={}, outputs={"http1": {"status": "ok"}}
        )
        assert result == "{'status': 'ok'}"

    def test_array_index_into_a_list_output(self):
        result = substitute_templates(
            "{{http1.items[0]}}", params={}, outputs={"http1": {"items": ["first", "second"]}}
        )
        assert result == "first"

    def test_nested_array_index_then_field(self):
        result = substitute_templates(
            "Temp: {{weather.current_condition[0].temp_C}}",
            params={}, outputs={"weather": {"current_condition": [{"temp_C": "18"}]}},
        )
        assert result == "Temp: 18"

    def test_multiple_array_indices_and_fields_chained(self):
        result = substitute_templates(
            "{{weather.nearest_area[0].areaName[0].value}}",
            params={},
            outputs={"weather": {"nearest_area": [{"areaName": [{"value": "Bogota"}]}]}},
        )
        assert result == "Bogota"

    def test_out_of_range_array_index_is_missing_marker(self):
        result = substitute_templates(
            "{{http1.items[5]}}", params={}, outputs={"http1": {"items": ["only-one"]}}
        )
        assert result == "[missing: http1.items[5]]"

    def test_array_index_into_a_non_list_is_missing_marker(self):
        result = substitute_templates(
            "{{http1.items[0]}}", params={}, outputs={"http1": {"items": "not-a-list"}}
        )
        assert result == "[missing: http1.items[0]]"

    def test_field_access_into_a_non_dict_element_is_missing_marker(self):
        result = substitute_templates(
            "{{http1.items[0].name}}", params={}, outputs={"http1": {"items": ["just-a-string"]}}
        )
        assert result == "[missing: http1.items[0].name]"


class TestResolveField:
    def test_no_data_edge_falls_back_to_literal_and_template(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"url": "https://example.com/{{producto}}"}
        result = resolve_field(
            "url", "http1", cfg, data_edges_by_target={}, nodes={},
            params={"producto": "zapatos"}, outputs={},
        )
        assert result == "https://example.com/zapatos"

    def test_data_edge_from_default_handle_resolves_whole_value(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"url": "https://ignored.example.com"}
        data_edges_by_target = {("http2", "url"): ("http1", "default")}
        nodes = {"http1": {"id": "http1", "type": "http", "config": {}}}
        result = resolve_field(
            "url", "http2", cfg, data_edges_by_target, nodes,
            params={}, outputs={"http1": "https://real-source.example.com"},
        )
        assert result == "https://real-source.example.com"

    def test_data_edge_with_named_handle_narrows_into_a_dict_value(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"search_term": "ignored"}
        data_edges_by_target = {("woo1", "search_term"): ("http1", "count")}
        nodes = {"http1": {"id": "http1", "type": "http", "config": {}}}
        result = resolve_field(
            "search_term", "woo1", cfg, data_edges_by_target, nodes,
            params={}, outputs={"http1": {"count": 7, "result": "..."}},
        )
        assert result == "7"

    def test_data_edge_from_a_get_source_resolves_via_the_variable_name_not_the_node_id(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"value": "ignored"}
        data_edges_by_target = {("cond1", "value"): ("get1", "default")}
        nodes = {"get1": {"id": "get1", "type": "get", "config": {"name": "mi_variable"}}}
        result = resolve_field(
            "value", "cond1", cfg, data_edges_by_target, nodes,
            params={}, outputs={"mi_variable": "hola"},  # get1's own id is NOT a key in outputs
        )
        assert result == "hola"

    def test_data_edge_from_a_source_that_has_not_executed_yet_is_a_missing_marker(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"url": "ignored"}
        data_edges_by_target = {("http2", "url"): ("http1", "default")}
        nodes = {"http1": {"id": "http1", "type": "http", "config": {}}}
        result = resolve_field(
            "url", "http2", cfg, data_edges_by_target, nodes,
            params={}, outputs={},  # http1 never ran (e.g. it's on the untaken branch)
        )
        assert result == "[missing: http1]"


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

        result, _ = await executor.run(graph, params={"producto": "zapatos"})

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

        result, _ = await executor.run(graph, params={})

        assert "producto" in result
        assert result.startswith("Error")

    async def test_flow_with_no_start_node_returns_error(self):
        graph = {"nodes": [{"id": "end", "type": "end", "config": {"template": "x"}}], "edges": []}
        executor = FlowExecutor()

        result, _ = await executor.run(graph, params={})

        assert result.startswith("Error")

    async def test_a_cycle_that_reaches_run_directly_is_capped_not_infinite(self):
        """detect_cycle() (Task 2) guards the API layer, but run() itself
        must not hang if a cyclic graph reaches it some other way (e.g. a
        row edited directly in the database, bypassing the API)."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "a", "type": "conditional", "config": {"field": "x", "operator": "equals", "value": "x"}},
                {"id": "b", "type": "conditional", "config": {"field": "x", "operator": "equals", "value": "x"}},
            ],
            "edges": [
                {"from": "start", "to": "a", "fromHandle": "default"},
                {"from": "a", "to": "b", "fromHandle": "true"},
                {"from": "b", "to": "a", "fromHandle": "true"},
            ],
        }
        executor = FlowExecutor()

        result, _ = await executor.run(graph, params={})

        assert result == "Error: flow exceeded maximum node visits (possible cycle)"

    async def test_run_returns_outputs_dict_alongside_the_result_string(self):
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
            result, outputs = await executor.run(graph, params={})

        assert result == "ok"
        assert outputs["http1"] == {"status": "ok"}


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
            result, _ = await executor.run(graph, params={})

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
            result, _ = await executor.run(graph, params={})

        assert result == "plain body"

    async def test_http_error_stops_the_flow_and_returns_an_error_string(self):
        graph = _http_graph()
        mock_client = AsyncMock()
        mock_client.request.side_effect = Exception("connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result.startswith("Error in node 'http1'")
        assert "connection refused" in result

    async def test_exception_with_empty_str_falls_back_to_type_name(self):
        graph = _http_graph()
        mock_client = AsyncMock()
        mock_client.request.side_effect = TimeoutError()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "Error in node 'http1' (http): TimeoutError"

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


class TestHttpNodeDataEdges:
    async def test_url_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "http1", "type": "http", "config": {"url": "https://ignored-literal.example.com", "method": "GET"}},
                {"id": "end", "type": "end", "config": {"template": "{{http1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "http1", "fromHandle": "default", "toHandle": "url", "kind": "data"},
            ],
        }
        source_response = MagicMock()
        source_response.headers = {"content-type": "text/plain"}
        source_response.text = "https://real-target.example.com"
        source_response.json.side_effect = ValueError("not json")
        source_response.raise_for_status = MagicMock()

        target_response = MagicMock()
        target_response.headers = {"content-type": "text/plain"}
        target_response.text = "ok"
        target_response.json.side_effect = ValueError("not json")
        target_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request.side_effect = [source_response, target_response]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            await executor.run(graph, params={})

        second_call_args = mock_client.request.call_args_list[1]
        assert second_call_args.args[1] == "https://real-target.example.com"


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
        result, _ = await executor.run(_conditional_graph("contains", "zap"), params={"start_value": "zapatos"})
        assert result == "YES: zapatos"

    async def test_contains_operator_false_branch(self):
        executor = FlowExecutor()
        result, _ = await executor.run(_conditional_graph("contains", "camisa"), params={"start_value": "zapatos"})
        assert result == "NO: zapatos"

    async def test_equals_operator(self):
        executor = FlowExecutor()
        result, _ = await executor.run(_conditional_graph("equals", "zapatos"), params={"start_value": "zapatos"})
        assert result == "YES: zapatos"

    async def test_is_empty_operator_true(self):
        executor = FlowExecutor()
        result, _ = await executor.run(_conditional_graph("is_empty", ""), params={"start_value": ""})
        assert result == "YES: "

    async def test_is_empty_operator_false(self):
        executor = FlowExecutor()
        result, _ = await executor.run(_conditional_graph("is_empty", ""), params={"start_value": "zapatos"})
        assert result == "NO: zapatos"

    async def test_is_error_operator(self):
        graph = _conditional_graph("is_error", "", field="{{prev}}")
        graph["nodes"][0]["config"]["parameters"] = []
        graph["nodes"][1]["config"]["field"] = "{{missing_node}}"
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        # "{{missing_node}}" resolves to "[missing: missing_node]" which starts with neither
        # "error" — this exercises is_error's false path using the missing-marker text itself.
        assert result == "NO: [missing: missing_node]"

    async def test_unknown_operator_is_an_error(self):
        graph = _conditional_graph("bogus_operator", "x")
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={"start_value": "zapatos"})
        assert result.startswith("Error in node 'cond1'")

    async def test_passthrough_output_is_the_evaluated_value_not_the_boolean(self):
        executor = FlowExecutor()
        result, _ = await executor.run(_conditional_graph("contains", "zap"), params={"start_value": "zapatos"})
        # end_true's template is "YES: {{cond1}}" — if the stored output were the
        # boolean True/False instead of the passthrough string, this would read "YES: True".
        assert result == "YES: zapatos"


class TestConditionalNodeDataEdges:
    async def test_field_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{ignored}}", "operator": "equals", "value": "zapatos"}},
                {"id": "end_true", "type": "end", "config": {"template": "YES"}},
                {"id": "end_false", "type": "end", "config": {"template": "NO"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "kind": "flow"},
                {"from": "cond1", "to": "end_true", "fromHandle": "true", "kind": "flow"},
                {"from": "cond1", "to": "end_false", "fromHandle": "false", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "toHandle": "field", "kind": "data"},
            ],
        }
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "zapatos"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        # field's literal is "{{ignored}}" (resolves to "[missing: ignored]")
        # — if the data edge weren't winning, equals would evaluate False.
        assert result == "YES"

    async def test_value_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "start_value", "type": "string", "required": True}]}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{start_value}}", "operator": "equals", "value": "wrong-literal"}},
                {"id": "end_true", "type": "end", "config": {"template": "YES"}},
                {"id": "end_false", "type": "end", "config": {"template": "NO"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "kind": "flow"},
                {"from": "cond1", "to": "end_true", "fromHandle": "true", "kind": "flow"},
                {"from": "cond1", "to": "end_false", "fromHandle": "false", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "zapatos"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={"start_value": "zapatos"})

        assert result == "YES"


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
            result, _ = await executor.run(_woo_graph(), params={"producto": "zapatos"})

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
            result, _ = await executor.run(_woo_graph(), params={"producto": "inexistente"})

        assert "No products found" in result

    async def test_missing_connection_is_an_error(self):
        async def get_connection(conn_id):
            return None

        executor = FlowExecutor(get_connection=get_connection)
        result, _ = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert result.startswith("Error in node 'woo1'")

    async def test_no_get_connection_configured_is_an_error(self):
        executor = FlowExecutor()  # get_connection defaults to None
        result, _ = await executor.run(_woo_graph(), params={"producto": "zapatos"})

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

    async def test_search_only_requests_published_products(self):
        """A private/draft product isn't meant to be customer-facing yet —
        don't let it leak into search results the bot recites to a customer."""
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
            await executor.run(_woo_graph(), params={"producto": "x"})

        _, call_kwargs = mock_client.get.call_args
        assert call_kwargs["params"]["status"] == "publish"

    async def test_stock_without_price_reported_as_out_of_stock(self):
        """WordPress/WooCommerce sometimes reports stock_quantity for a product
        that has no price set — that's not real availability, treat it as
        out of stock regardless of what stock_quantity says."""
        products = [
            {"name": "Fantasma", "price": "", "stock_quantity": 5, "manage_stock": True,
             "permalink": "https://tienda.example.com/fantasma"},
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
            result, _ = await executor.run(_woo_graph(), params={"producto": "fantasma"})

        assert "Stock: Out of stock" in result
        assert "Stock: 5" not in result

    async def test_stock_with_price_reports_actual_quantity(self):
        products = [
            {"name": "Real", "price": "10.00", "stock_quantity": 5, "manage_stock": True,
             "permalink": "https://tienda.example.com/real"},
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
            result, _ = await executor.run(_woo_graph(), params={"producto": "real"})

        assert "Stock: 5" in result


class TestWooCommerceStructuredOutput:
    async def test_returns_a_dict_with_result_and_count(self):
        products = [
            {"name": "A", "price": "1", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"},
            {"name": "B", "price": "2", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"},
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

        graph = _woo_graph()
        graph["nodes"][2]["config"]["template"] = "{{woo1.count}}"

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result, outputs = await executor.run(graph, params={"producto": "zapatos"})

        assert result == "2"
        assert outputs["woo1"]["count"] == 2
        assert isinstance(outputs["woo1"]["result"], str)

    async def test_count_reflects_the_top_10_slice_not_the_full_result_set(self):
        # The node fetches per_page=10 candidates and hands ALL of them to
        # the agent (no 5-item shortlisting on our side) — the agent, which
        # already knows what the user actually asked for, is what narrows
        # this down when it replies. If WooCommerce ever ignores per_page
        # and returns more anyway, the node still caps defensively at 10.
        products = [
            {"name": f"P{i}", "price": "1", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"}
            for i in range(15)
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

        graph = _woo_graph()
        graph["nodes"][2]["config"]["template"] = "{{woo1.count}}"

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result, _ = await executor.run(graph, params={"producto": "zapatos"})

        assert result == "10"

    async def test_requests_ten_candidates_per_page(self):
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
            await executor.run(_woo_graph(), params={"producto": "zapatos"})

        _, call_kwargs = mock_client.get.call_args
        assert call_kwargs["params"]["per_page"] == 10

    async def test_result_text_tells_the_agent_to_select_relevant_ones(self):
        products = [
            {"name": f"P{i}", "price": "1", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"}
            for i in range(3)
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
            result, _ = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert "select and mention only the ones" in result

    async def test_bare_reference_still_resolves_to_the_formatted_result_text(self):
        """{{woo1}} (no dot) must keep behaving exactly as it did before
        this task — the human-formatted listing — even though
        outputs['woo1'] is now a dict, via the new whole-value
        dict-with-result-key special case in substitute_templates."""
        products = [
            {"name": "Zapatos rojos", "price": "49.99", "stock_quantity": 3, "manage_stock": True,
             "short_description": "Comodos", "permalink": "https://tienda.example.com/zapatos-rojos"},
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
            result, _ = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert "Zapatos rojos" in result
        assert "$49.99" in result

    async def test_no_products_found_is_also_a_result_count_dict(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        graph = _woo_graph()
        graph["nodes"][2]["config"]["template"] = "{{woo1.count}}"

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result, outputs = await executor.run(graph, params={"producto": "inexistente"})

        assert result == "0"
        assert "No products found" in outputs["woo1"]["result"]

    async def test_search_term_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "woo1", "type": "woocommerce", "config": {"connection_id": 1, "search_term": "ignored-literal"}},
                {"id": "end", "type": "end", "config": {"template": "{{woo1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "woo1", "fromHandle": "default", "kind": "flow"},
                {"from": "woo1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "woo1", "fromHandle": "default", "toHandle": "search_term", "kind": "data"},
            ],
        }
        source_response = MagicMock()
        source_response.headers = {"content-type": "text/plain"}
        source_response.text = "zapatos"
        source_response.json.side_effect = ValueError("not json")
        source_response.raise_for_status = MagicMock()
        mock_http_client = AsyncMock()
        mock_http_client.request.return_value = source_response
        mock_http_client.__aenter__.return_value = mock_http_client
        mock_http_client.__aexit__.return_value = False

        products_response = MagicMock()
        products_response.json.return_value = []
        products_response.raise_for_status = MagicMock()
        mock_woo_client = AsyncMock()
        mock_woo_client.get.return_value = products_response
        mock_woo_client.__aenter__.return_value = mock_woo_client
        mock_woo_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        with patch("openacm.core.flow_executor.httpx.AsyncClient") as mock_cls:
            mock_cls.side_effect = [mock_http_client, mock_woo_client]
            executor = FlowExecutor(get_connection=get_connection)
            result, _ = await executor.run(graph, params={})

        assert "zapatos" in result


def _set_graph(source_type="http", var_name="mi_variable"):
    """Start -> source_node -> End(template referencing the Set). Set has
    no flow position (it's a pure node) — its "value" pin is wired
    directly from source_node's default output and computed on demand
    the moment {{var_name}} is first referenced."""
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
            {"from": "start", "to": "src1", "fromHandle": "default", "kind": "flow"},
            {"from": "src1", "to": "end", "fromHandle": "default", "kind": "flow"},
            {"from": "src1", "to": "var1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
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
            result, _ = await executor.run(_set_graph(), params={})

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
            result, _ = await executor.run(graph, params={})

        assert result == "Por id: hola mundo"

    async def test_variable_with_nothing_wired_to_its_value_pin_resolves_to_missing(self):
        """A pure Set node has no flow position and no previous-node
        fallback anymore — if nothing is wired into its "value" input,
        referencing its name finds nothing to compute, not a stale or
        borrowed value."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "var1", "type": "set", "config": {"name": "huerfana"}},
                {"id": "end", "type": "end", "config": {"template": "{{huerfana}}"}},
            ],
            "edges": [
                {"from": "start", "to": "end", "fromHandle": "default", "kind": "flow"},
            ],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        assert result == "[missing: huerfana]"

    async def test_two_variables_with_the_same_name_first_match_in_node_order_wins(self):
        """Pure Set nodes have no execution order, so "two Sets sharing a
        name" no longer has a "last one to run" — resolution just takes
        the first matching Set node in the graph's node list. Not a shape
        a real flow should build deliberately; documented here so the
        behavior is at least deterministic instead of silently
        arbitrary."""
        response_a = MagicMock()
        response_a.headers = {"content-type": "text/plain"}
        response_a.text = "primer valor"
        response_a.json.side_effect = ValueError("not json")
        response_a.raise_for_status = MagicMock()
        response_b = MagicMock()
        response_b.headers = {"content-type": "text/plain"}
        response_b.text = "segundo valor"
        response_b.json.side_effect = ValueError("not json")
        response_b.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.side_effect = [response_a, response_b]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://a.example.com", "method": "GET"}},
                {"id": "http2", "type": "http", "config": {"url": "https://b.example.com", "method": "GET"}},
                {"id": "var1", "type": "set", "config": {"name": "dup"}},
                {"id": "var2", "type": "set", "config": {"name": "dup"}},
                {"id": "end", "type": "end", "config": {"template": "{{dup}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "http2", "fromHandle": "default", "kind": "flow"},
                {"from": "http2", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "var1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
                {"from": "http2", "to": "var2", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "primer valor"

    async def test_set_wired_from_a_conditionals_result_pin_works_under_either_branch(self):
        """Old previous_id-based "downstream of a merge" semantics no
        longer apply — a pure Set just wires its "value" pin directly to
        Conditional's "result" pin (the evaluated field value, the same
        regardless of which branch fired), which doesn't care about flow
        position at all."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "x", "type": "string", "required": True}]}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{x}}", "operator": "equals", "value": "yes"}},
                {"id": "picked", "type": "set", "config": {"name": "picked"}},
                {"id": "end", "type": "end", "config": {"template": "{{picked}}"}},
            ],
            "edges": [
                {"from": "start", "to": "cond1", "fromHandle": "default", "kind": "flow"},
                {"from": "cond1", "to": "end", "fromHandle": "true", "kind": "flow"},
                {"from": "cond1", "to": "end", "fromHandle": "false", "kind": "flow"},
                {"from": "cond1", "to": "picked", "fromHandle": "result", "toHandle": "value", "kind": "data"},
            ],
        }
        executor = FlowExecutor()

        result_true, _ = await executor.run(graph, params={"x": "yes"})
        result_false, _ = await executor.run(graph, params={"x": "no"})

        assert result_true == "yes"
        assert result_false == "no"


class TestSetNodeDataEdge:
    async def test_set_value_handle_wired_to_a_far_back_node_aliases_it_correctly(self):
        """A pure Set's "value" pin can wire from ANY node's output, not
        just an adjacent one in the flow — set1 has no flow position at
        all; it just pulls http_a's output the moment {{picked}} is
        referenced, ignoring http_b entirely."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http_a", "type": "http", "config": {"url": "https://a.example.com", "method": "GET"}},
                {"id": "http_b", "type": "http", "config": {"url": "https://b.example.com", "method": "GET"}},
                {"id": "set1", "type": "set", "config": {"name": "picked"}},
                {"id": "end", "type": "end", "config": {"template": "{{picked}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http_a", "fromHandle": "default", "kind": "flow"},
                {"from": "http_a", "to": "http_b", "fromHandle": "default", "kind": "flow"},
                {"from": "http_b", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http_a", "to": "set1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        response_a = MagicMock()
        response_a.headers = {"content-type": "text/plain"}
        response_a.text = "from A"
        response_a.json.side_effect = ValueError("not json")
        response_a.raise_for_status = MagicMock()
        response_b = MagicMock()
        response_b.headers = {"content-type": "text/plain"}
        response_b.text = "from B"
        response_b.json.side_effect = ValueError("not json")
        response_b.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request.side_effect = [response_a, response_b]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "from A"

    async def test_set_value_handle_sourced_from_a_get_node_resolves_via_variable_name(self):
        """A Get node has no flow handles (it's a "pure" node — see
        _resolve_pin_value's docstring), and now neither does Set. When a
        Set node's "value" data edge is sourced from a Get node,
        resolution must go through the Get's configured variable name
        instead of the Get node's own id — and that name lookup must
        itself trigger a THIRD Set node's (set_a's) on-demand computation,
        since nothing walked it into outputs proactively either."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http_a", "type": "http", "config": {"url": "https://a.example.com", "method": "GET"}},
                {"id": "set_a", "type": "set", "config": {"name": "some_var"}},
                {"id": "get1", "type": "get", "config": {"name": "some_var"}},
                {"id": "set2", "type": "set", "config": {"name": "final"}},
                {"id": "end", "type": "end", "config": {"template": "Final: {{final}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http_a", "fromHandle": "default", "kind": "flow"},
                {"from": "http_a", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http_a", "to": "set_a", "fromHandle": "default", "toHandle": "value", "kind": "data"},
                {"from": "get1", "to": "set2", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "from A"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, outputs = await executor.run(graph, params={})

        assert result == "Final: from A"
        assert outputs["final"] == outputs["some_var"]
        assert "get1" not in outputs

    async def test_two_sets_wired_into_each_other_does_not_infinite_loop(self):
        """Data edges are exempt from the save-time cycle check (a Set
        aliasing an earlier node's output is allowed to point "backward")
        — two Set nodes wired into each other's "value" pin is the one
        shape that check can't catch. The _resolving guard makes
        resolution fail closed (a missing marker) instead of recursing
        forever."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "set_a", "type": "set", "config": {"name": "a"}},
                {"id": "set_b", "type": "set", "config": {"name": "b"}},
                {"id": "end", "type": "end", "config": {"template": "{{a}}"}},
            ],
            "edges": [
                {"from": "start", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "set_b", "to": "set_a", "fromHandle": "value", "toHandle": "value", "kind": "data"},
                {"from": "set_a", "to": "set_b", "fromHandle": "value", "toHandle": "value", "kind": "data"},
            ],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        assert result == "[missing: a]"


def _get_graph(get_name="mi_variable"):
    """Start -> HTTP -> Get(name=get_name) -> End(references the Get
    node's own id). Set(name=get_name) has no flow position — it's wired
    from HTTP's default output and computed on demand the moment Get (or
    anything else) first references get_name."""
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
            {"from": "src1", "to": "get1", "fromHandle": "default"},
            {"from": "src1", "to": "set1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
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
            result, _ = await executor.run(_get_graph(), params={})

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
            result, _ = await executor.run(graph, params={})

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
        result, _ = await executor.run(graph, params={})
        assert result == "[missing: get1]"


class TestIsErrorResult:
    def test_end_node_output_is_not_an_error(self):
        assert is_error_result("done") is False
        assert is_error_result("🌤️ Clima en Madrid: 18°C") is False

    def test_missing_start_node_is_an_error(self):
        assert is_error_result("Error: flow has no Start node") is True

    def test_missing_required_param_is_an_error(self):
        assert is_error_result("Error: missing required parameter 'url'") is True

    def test_node_handler_exception_is_an_error(self):
        assert is_error_result("Error in node 'weather' (http): 403 Forbidden") is True

    def test_unknown_node_type_is_an_error(self):
        assert is_error_result("Error: unknown node type 'bogus'") is True


class TestLoopNode:
    async def test_loop_runs_body_once_per_item_then_reaches_done(self):
        # No body node — with Set no longer flow-connectable, "loop1"'s
        # own outputs (item/index) already carry the state of the last
        # iteration, so the End template reads that directly instead of
        # relaying it through a per-iteration Set node.
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "Last seen: {{loop1.item}}, final index: {{loop1.index}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, outputs = await executor.run(graph, params={})

        assert result == "Last seen: c, final index: 2"
        assert outputs["loop1"] == {"item": "c", "index": 2}

    async def test_empty_items_list_skips_straight_to_done(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "{{loop1.item}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = []
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        # An empty-items loop never writes outputs["loop1"] at all (only
        # the non-empty branch does) — proof the body was never entered.
        assert result == "[missing: loop1.item]"

    async def test_max_iterations_cap_trips_with_items_remaining(self):
        # The max_iterations check fires on every dead end regardless of
        # what (if anything) is wired into the loop's "loop" pin — no body
        # node is needed to exercise it.
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {"max_iterations": 2}},
                {"id": "end", "type": "end", "config": {"template": "unreachable"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c", "d", "e"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "Error in node 'loop1' (loop): reached max_iterations (2) with more items remaining"

    async def test_items_pin_not_wired_returns_error(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "done"}},
            ],
            "edges": [
                {"from": "start", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        assert result == "Error in node 'loop1' (loop): 'items' pin is not wired to a list"

    async def test_end_node_inside_loop_body_terminates_the_whole_flow_immediately(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "Stopped at {{loop1.item}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "loop", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "Stopped at a"

    async def test_nested_loops_both_trackers_resolve_independently(self):
        """Outer loop (2 items) wraps an inner loop (3 items). The inner
        loop's own "loop" AND "done" pins are BOTH deliberately left
        UNWIRED (Set can no longer sit in a loop body to give "loop" a
        target) — when the inner loop exhausts, it dead-ends immediately,
        which must cascade to advancing the OUTER frame (not error out),
        proving the stack (not a single value) is what tracks "which loop
        am I in"."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http_outer", "type": "http", "config": {"url": "https://example.com/outer", "method": "GET"}},
                {"id": "http_inner", "type": "http", "config": {"url": "https://example.com/inner", "method": "GET"}},
                {"id": "loop_outer", "type": "loop", "config": {}},
                {"id": "loop_inner", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {
                    "template": "outer={{loop_outer.item}}:{{loop_outer.index}} inner={{loop_inner.item}}:{{loop_inner.index}}"
                }},
            ],
            "edges": [
                {"from": "start", "to": "http_outer", "fromHandle": "default", "kind": "flow"},
                {"from": "http_outer", "to": "http_inner", "fromHandle": "default", "kind": "flow"},
                {"from": "http_inner", "to": "loop_outer", "fromHandle": "default", "kind": "flow"},
                {"from": "http_outer", "to": "loop_outer", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop_outer", "to": "loop_inner", "fromHandle": "loop", "kind": "flow"},
                {"from": "http_inner", "to": "loop_inner", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop_outer", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response_outer = MagicMock()
        response_outer.json.return_value = ["x", "y"]
        response_outer.raise_for_status = MagicMock()
        response_inner = MagicMock()
        response_inner.json.return_value = [1, 2, 3]
        response_inner.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.side_effect = [response_outer, response_inner]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "outer=y:1 inner=3:2"

    async def test_non_numeric_max_iterations_falls_back_to_default_instead_of_raising(self):
        """A config value that isn't a clean int (a string from a JSON
        import, or an explicit null) must not raise a TypeError out of
        run() — it should fall back to the 200 default and complete the
        flow normally."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {"max_iterations": "not-a-number"}},
                {"id": "end", "type": "end", "config": {"template": "Last seen: {{loop1.item}}, final index: {{loop1.index}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, outputs = await executor.run(graph, params={})

        assert result == "Last seen: c, final index: 2"
        assert outputs["loop1"] == {"item": "c", "index": 2}

    async def test_null_max_iterations_falls_back_to_default_instead_of_raising(self):
        """.get(key, 200) does NOT protect against an explicit null — the
        key IS present, so the default is never used and None flows
        through. Confirm the coercion catches this case too."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {"max_iterations": None}},
                {"id": "end", "type": "end", "config": {"template": "Last seen: {{loop1.item}}, final index: {{loop1.index}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, outputs = await executor.run(graph, params={})

        assert result == "Last seen: c, final index: 2"
        assert outputs["loop1"] == {"item": "c", "index": 2}

    async def test_global_visit_cap_tripped_inside_loop_names_the_loop_not_a_cycle(self):
        """A legitimate loop with a large max_iterations and a multi-visit
        body can trip the global _MAX_NODE_VISITS backstop with zero
        actual cycles. The error must name the loop, not claim
        "possible cycle". The body needs an actual flow-connectable node
        to rack up visits (a dead-end pass doesn't increment `visits` at
        all) — Set can no longer fill that role, so a synchronous
        Conditional (its "false" output left unwired) stands in instead."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {"max_iterations": 5000}},
                {"id": "noop", "type": "conditional", "config": {"field": "x", "operator": "equals", "value": "y"}},
                {"id": "end", "type": "end", "config": {"template": "unreachable"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "noop", "fromHandle": "loop", "kind": "flow"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = list(range(3000))
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert "possible cycle" not in result
        assert "loop1" in result
        assert result.startswith("Error: flow exceeded maximum node visits")


class TestWholeValueSourcePinAliases:
    """http's "response", conditional's "result", and set's "value" source
    pins all alias the node's WHOLE stored output — unlike WooCommerce's
    "result"/"count" or Loop's "item"/"index", where outputs[node_id] is
    itself a dict keyed by the handle name, these three store the raw
    value directly. A JSON-object response is the case that would break
    without the alias carve-out: wiring "response" would otherwise try to
    find a literal "response" KEY inside the response body itself."""

    async def test_http_response_pin_yields_the_whole_json_object_not_a_key_lookup(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/data", "method": "GET"}},
                {"id": "set1", "type": "set", "config": {"name": "captured"}},
                {"id": "end", "type": "end", "config": {"template": "{{captured.city}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "set1", "fromHandle": "response", "toHandle": "value", "kind": "data"},
            ],
        }
        response = MagicMock()
        response.json.return_value = {"city": "Bogota", "response": "not-this-key"}
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "Bogota"

    async def test_conditional_result_pin_yields_the_evaluated_field_value(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "start_value", "type": "string", "required": True}]}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{start_value}}", "operator": "contains", "value": "zap"}},
                {"id": "set1", "type": "set", "config": {"name": "captured"}},
                {"id": "end", "type": "end", "config": {"template": "{{captured}}"}},
            ],
            "edges": [
                {"from": "start", "to": "cond1", "fromHandle": "default", "kind": "flow"},
                {"from": "cond1", "to": "end", "fromHandle": "true", "kind": "flow"},
                {"from": "cond1", "to": "set1", "fromHandle": "result", "toHandle": "value", "kind": "data"},
            ],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={"start_value": "zapatos"})
        assert result == "zapatos"

    async def test_set_value_pin_yields_the_aliased_value_to_a_downstream_node(self):
        """set2 reads set1's captured value via set1's "value" SOURCE pin,
        rather than via set1's {{captured}} template name — proving a data
        edge wired directly to a Set node's own output resolves it on
        demand too, not just a bare-name template reference."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/greeting", "method": "GET"}},
                {"id": "set1", "type": "set", "config": {"name": "captured"}},
                {"id": "set2", "type": "set", "config": {"name": "relayed"}},
                {"id": "end", "type": "end", "config": {"template": "{{relayed}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "set1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
                {"from": "set1", "to": "set2", "fromHandle": "value", "toHandle": "value", "kind": "data"},
            ],
        }
        response = MagicMock()
        response.headers = {"content-type": "text/plain"}
        response.text = "hola"
        response.json.side_effect = ValueError("not json")
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "hola"


class TestValidateGraph:
    def _valid_graph(self):
        return {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://x", "method": "GET"}},
                {"id": "end", "type": "end", "config": {"template": "{{http1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
            ],
        }

    def test_valid_graph_has_no_errors(self):
        from openacm.core.flow_executor import validate_graph
        assert validate_graph(self._valid_graph()) == []

    def test_unknown_node_type_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"][1]["type"] = "not_a_real_type"
        errors = validate_graph(graph)
        assert any("not_a_real_type" in e for e in errors)

    def test_zero_start_nodes_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "start"]
        graph["edges"] = []
        errors = validate_graph(graph)
        assert any("start" in e.lower() for e in errors)

    def test_two_start_nodes_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"].append({"id": "start2", "type": "start", "config": {"parameters": []}})
        errors = validate_graph(graph)
        assert any("start" in e.lower() for e in errors)

    def test_zero_end_nodes_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "end"]
        graph["edges"] = [e for e in graph["edges"] if e["to"] != "end"]
        errors = validate_graph(graph)
        assert any("end" in e.lower() for e in errors)

    def test_duplicate_node_ids_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"][1]["id"] = "start"
        errors = validate_graph(graph)
        assert any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)

    def test_edge_to_missing_node_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["edges"].append({"from": "http1", "to": "nonexistent", "fromHandle": "default", "toHandle": "default", "kind": "flow"})
        errors = validate_graph(graph)
        assert any("nonexistent" in e for e in errors)

    def test_invalid_handle_for_node_type_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        # "count" is a valid SOURCE handle on woocommerce, not on http.
        graph["edges"][1]["fromHandle"] = "count"
        errors = validate_graph(graph)
        assert any("count" in e for e in errors)

    def test_cycle_is_still_reported(self):
        from openacm.core.flow_executor import validate_graph
        # A minimal cyclic graph: conditional's "false" branch loops back to
        # itself instead of reaching an exit — a real cycle, unrelated to
        # any other validation rule.
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "cond", "type": "conditional", "config": {"field": "x", "operator": "equals", "value": "y"}},
                {"id": "end", "type": "end", "config": {"template": "done"}},
            ],
            "edges": [
                {"from": "start", "to": "cond", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "cond", "to": "end", "fromHandle": "true", "toHandle": "default", "kind": "flow"},
                {"from": "cond", "to": "cond", "fromHandle": "false", "toHandle": "default", "kind": "flow"},
            ],
        }
        errors = validate_graph(graph)
        assert any("cycle" in e.lower() for e in errors)

    def test_multiple_problems_are_all_reported_together(self):
        from openacm.core.flow_executor import validate_graph
        graph = {"nodes": [{"id": "a", "type": "bogus", "config": {}}], "edges": []}
        errors = validate_graph(graph)
        assert len(errors) >= 2  # unknown type AND missing start AND missing end

    def test_loop_node_with_valid_handles_has_no_errors(self):
        from openacm.core.flow_executor import validate_graph
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://x", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "{{loop1.item}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "toHandle": "default", "kind": "flow"},
            ],
        }
        assert validate_graph(graph) == []


class TestConfiglessNodeDoesNotCrash:
    """The spec's global constraint: a node with no "config" key is treated
    as config: {}. validate_graph correctly accepts such a node, so run()
    must honor the same default rather than raising a raw KeyError — which,
    for a flow exposed as an agent tool, bricks the owning agent's chat."""

    async def test_start_node_with_no_config_key_runs_without_crashing(self):
        graph = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end", "config": {"template": "done"}}],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"}],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        assert result == "done"

    async def test_end_node_with_no_config_key_runs_without_crashing(self):
        graph = {
            "nodes": [{"id": "start", "type": "start", "config": {"parameters": []}}, {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"}],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        assert result == ""  # missing config -> {} -> template defaults to ""
