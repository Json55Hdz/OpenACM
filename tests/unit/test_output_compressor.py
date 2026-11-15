"""The output compressor decides what the model sees of a tool result. It may shorten output,
but it must never silently lose something the model needs, and when it drops content it says so."""

import json

import pytest

from openacm.core.output_compressor import compress


def _c(text, tool="", **args):
    out, orig, comp = compress(text, tool, args)
    assert orig == len(text) and comp == len(out)
    return out


class TestNeverLosesWhatMatters:
    @pytest.mark.parametrize("tool", ["run_command", "run_python", "read_file", "web_search", "system_info", "other_tool"])
    def test_empty_and_unicode_input_do_not_raise(self, tool):
        assert _c("", tool) == ""
        assert "ñandú" in _c("ñandú ✓ 日本語", tool)

    def test_short_plain_output_survives_unchanged(self):
        assert _c("hello world", "run_command", command="echo hello world") == "hello world"

    def test_errors_in_command_output_are_kept(self):
        noisy = "\n".join(["Collecting requests"] * 5 + ["Traceback (most recent call last):", "ValueError: boom"])
        out = _c(noisy, "run_command", command="pip install x")
        assert "Traceback" in out and "ValueError: boom" in out

    def test_command_output_keeps_first_and_last_lines(self):
        lines = [f"row {i}" for i in range(200)]
        out = _c("\n".join(lines), "run_command", command="python report.py")
        assert "row 0" in out and "row 199" in out


class TestFileReads:
    def test_text_file_without_special_extension_keeps_its_content(self):
        text = "line one\nline two\nline three"
        assert _c(text, "read_file", path="notes.txt") == text

    def test_code_keeps_every_executable_line(self):
        code = "import os\n\n\ndef f(x):\n    return x + 1\n\n\nclass A:\n    pass\n"
        out = _c(code, "read_file", path="a.py")
        for needle in ("import os", "def f(x):", "return x + 1", "class A:"):
            assert needle in out

    def test_a_long_docstring_removed_from_code_is_marked(self):
        doc = '"""\n' + "\n".join(f"detail line {i}" for i in range(10)) + '\n"""'
        code = f"def f():\n    {doc}\n    return 1\n"
        out = _c(code, "read_file", path="a.py")
        assert "detail line 9" not in out
        assert "omitted" in out.lower() or "..." in out

    def test_log_lines_without_a_level_are_not_silently_dropped(self):
        lines = [f"plain line {i}" for i in range(40)]
        out = _c("\n".join(lines), "read_file", path="app.log")
        kept = sum(1 for l in lines if l in out)
        assert kept == 40 or "omitted" in out.lower() or "more" in out.lower()

    def test_log_keeps_all_errors(self):
        lines = [f"INFO ok {i}" for i in range(30)] + ["ERROR database is down"] + [f"INFO ok {i}" for i in range(30)]
        assert "ERROR database is down" in _c("\n".join(lines), "read_file", path="app.log")

    def test_json_with_long_values_is_marked_when_cut(self):
        data = {"items": [{"k": "x" * 500} for _ in range(30)]}
        out = _c(json.dumps(data), "read_file", path="d.json")
        assert len(out) < len(json.dumps(data))
        assert "..." in out or "more" in out.lower()


class TestDirectoryListings:
    def test_recursive_listing_is_summarized_not_dumped(self):
        text = "\n".join(f"./src/pkg{i % 7}/file{i}.py" for i in range(400))
        out = _c(text, "run_command", command="find . -type f")
        assert len(out) < len(text) // 2


class TestExactText:
    """The model must be able to get a file exactly as it is: to edit it, or when it needs all of it."""

    CODE = 'def f():\n    """\n' + "\n".join(f"    detail {i}" for i in range(10)) + '\n    """\n    x  =  1   # aligned\n'

    def test_raw_returns_the_text_untouched(self):
        assert _c(self.CODE, "read_file", path="a.py", raw=True) == self.CODE

    def test_raw_log_keeps_every_line(self):
        log = "\n".join(f"plain line {i}" for i in range(40))
        assert _c(log, "read_file", path="app.log", raw=True) == log

    def test_read_file_range_is_never_condensed(self):
        text = "   12 | x  =  1   # two spaces\n   13 | \n\n\n\n   14 | y\n"
        assert _c(text, "read_file_range") == text

    def test_a_condensed_read_tells_the_model_how_to_get_the_exact_text(self):
        out = _c(self.CODE, "read_file", path="a.py")
        assert "raw=true" in out

    def test_an_unchanged_read_gets_no_note(self):
        assert "raw=true" not in _c("just text", "read_file", path="a.txt")

    def test_read_file_accepts_raw(self):
        import inspect
        from openacm.tools.file_ops import read_file

        assert "raw" in inspect.signature(read_file).parameters
