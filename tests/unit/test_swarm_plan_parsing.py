"""The swarm planner asks an LLM for a JSON plan and the reply is often fenced, wrapped in prose,
has trailing commas or is cut off. These paths decide whether a swarm starts with its whole plan."""

import json

import pytest

from openacm.core.swarm_manager import SwarmManager

PLAN = {"name": "demo", "tasks": [{"title": "A", "depends_on": []}, {"title": "B", "depends_on": ["A"]}]}


@pytest.fixture
def parse():
    return SwarmManager.__new__(SwarmManager)._parse_plan  # parsing needs no running manager


class TestParsePlan:
    def test_raw_json(self, parse):
        assert parse(json.dumps(PLAN)) == PLAN

    def test_fenced_json_with_language_tag(self, parse):
        assert parse("```json\n" + json.dumps(PLAN) + "\n```") == PLAN

    def test_fence_without_language_tag_and_trailing_newlines(self, parse):
        assert parse("```\n" + json.dumps(PLAN) + "\n```\n\n") == PLAN

    def test_json_wrapped_in_prose(self, parse):
        assert parse("Here is the plan:\n" + json.dumps(PLAN) + "\nHope it helps!") == PLAN

    def test_trailing_commas_are_repaired(self, parse):
        text = '{"name": "demo", "tasks": [{"title": "A",}, {"title": "B",},],}'
        assert [t["title"] for t in parse(text)["tasks"]] == ["A", "B"]

    def test_cut_off_after_a_complete_task_keeps_the_complete_tasks(self, parse):
        text = '{"name": "demo", "tasks": [{"title": "A"}, {"title": "B"}'
        assert [t["title"] for t in parse(text)["tasks"]] == ["A", "B"]

    def test_unclosed_fence_is_still_parsed(self, parse):
        text = '```json\n{"name": "demo", "tasks": [{"title": "A"}'
        assert parse(text)["tasks"][0]["title"] == "A"

    def test_cut_off_inside_a_string_is_an_error_not_a_guess(self, parse):
        with pytest.raises(ValueError):
            parse('{"name": "demo", "tasks": [{"title": "A unfinished tit')

    @pytest.mark.parametrize("text", ["", "no json here", "{not json at all"])
    def test_garbage_raises_value_error(self, parse, text):
        with pytest.raises(ValueError):
            parse(text)


class TestRepairJson:
    def test_balanced_json_is_untouched(self):
        assert SwarmManager._repair_json('{"a": [1, 2]}') == '{"a": [1, 2]}'

    def test_closes_brackets_in_the_right_amount(self):
        assert json.loads(SwarmManager._repair_json('{"a": [1, 2')) == {"a": [1, 2]}

    def test_trailing_comma_before_close_is_removed(self):
        assert json.loads(SwarmManager._repair_json('{"a": [1, 2,],}')) == {"a": [1, 2]}


class TestCutOffPlans:
    """A plan cut off in the middle of a task must not silently lose that task."""

    def test_cut_inside_a_task_keeps_every_task(self, parse):
        text = '{"tasks": [{"title": "A"}, {"title": "B", "depends_on": ["A"]'
        assert [t["title"] for t in parse(text)["tasks"]] == ["A", "B"]

    def test_cut_inside_a_nested_object_closes_in_the_right_order(self, parse):
        plan = parse('{"tasks": [{"title": "A", "x": {"y": 1')
        assert plan["tasks"][0]["x"] == {"y": 1}

    def test_braces_inside_strings_are_not_counted(self, parse):
        text = '{"tasks": [{"title": "uses a } brace"}, {"title": "has { open"}'
        assert [t["title"] for t in parse(text)["tasks"]] == ["uses a } brace", "has { open"]

    def test_escaped_quotes_do_not_end_a_string(self, parse):
        text = '{"tasks": [{"title": "say \\"hi}\\""}'
        assert parse(text)["tasks"][0]["title"] == 'say "hi}"'

    def test_repair_cannot_guess_the_end_of_an_unfinished_string(self):
        text = '{"a": "unfinished'
        assert SwarmManager._repair_json(text) == text
