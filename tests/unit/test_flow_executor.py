"""Tests for FlowExecutor's core mechanics: template substitution and the
minimal Start-to-End graph walk. Node-type-specific handlers (HTTP,
Conditional, WooCommerce) are tested in their own dedicated test files."""
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
