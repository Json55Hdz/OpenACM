"""
Tests for openacm.constants

Verifies that every exported constant:
  - exists and is importable
  - has the correct Python type
  - is within a sane range (no typos like 120_000 instead of 12_000)
"""

import openacm.constants as C


class TestNetworkDefaults:
    def test_web_host_is_loopback(self):
        assert C.DEFAULT_WEB_HOST == "127.0.0.1"

    def test_web_port_is_int_in_range(self):
        assert isinstance(C.DEFAULT_WEB_PORT, int)
        assert 1024 < C.DEFAULT_WEB_PORT < 65535

    def test_ollama_url_is_http(self):
        assert C.DEFAULT_OLLAMA_BASE_URL.startswith("http://")
        assert "11434" in C.DEFAULT_OLLAMA_BASE_URL

    def test_whatsapp_bridge_url_is_http(self):
        assert C.DEFAULT_WHATSAPP_BRIDGE_URL.startswith("http://")

    def test_blender_bridge_port_is_int(self):
        assert isinstance(C.DEFAULT_BLENDER_BRIDGE_PORT, int)
        assert 1024 < C.DEFAULT_BLENDER_BRIDGE_PORT < 65535


class TestTruncationLimits:
    """All truncation values must be positive ints within sensible bounds."""

    TRUNCATION_CONSTANTS = [
        "TRUNCATE_PDF_CHARS",
        "TRUNCATE_FILE_CONTEXT_CHARS",
        "TRUNCATE_BROWSER_PAGE_CHARS",
        "TRUNCATE_BROWSER_HTML_CHARS",
        "TRUNCATE_TOOL_RESULT_CHARS",
        "TRUNCATE_SWARM_TASK_OUTPUT_CHARS",
        "TRUNCATE_CRON_OUTPUT_CHARS",
        "TRUNCATE_LLM_ERROR_CHARS",
        "TRUNCATE_DB_OUTPUT_CHARS",
        "TRUNCATE_DB_ERROR_CHARS",
        "TRUNCATE_ONBOARDING_BEHAVIORS_CHARS",
        "TRUNCATE_STITCH_PREVIEW_CHARS",
        "TRUNCATE_RAG_CONTEXT_CHARS",
    ]

    def test_all_truncation_constants_exist(self):
        for name in self.TRUNCATION_CONSTANTS:
            assert hasattr(C, name), f"Missing constant: {name}"

    def test_all_truncation_constants_are_positive_ints(self):
        for name in self.TRUNCATION_CONSTANTS:
            val = getattr(C, name)
            assert isinstance(val, int), f"{name} should be int, got {type(val)}"
            assert val > 0, f"{name} should be > 0, got {val}"

    def test_truncation_limits_are_sane(self):
        # Nothing should be more than 1 MB of chars (would be absurd)
        for name in self.TRUNCATION_CONSTANTS:
            val = getattr(C, name)
            assert val <= 1_000_000, f"{name} = {val} seems too large"

    def test_pdf_larger_than_html(self):
        assert C.TRUNCATE_PDF_CHARS >= C.TRUNCATE_BROWSER_HTML_CHARS

    def test_db_error_smaller_than_db_output(self):
        assert C.TRUNCATE_DB_ERROR_CHARS <= C.TRUNCATE_DB_OUTPUT_CHARS


class TestSwarmConstants:
    def test_max_parallel_workers_is_positive(self):
        assert isinstance(C.SWARM_MAX_PARALLEL_WORKERS, int)
        assert C.SWARM_MAX_PARALLEL_WORKERS >= 1

    def test_max_task_retries_is_non_negative(self):
        assert isinstance(C.SWARM_MAX_TASK_RETRIES, int)
        assert C.SWARM_MAX_TASK_RETRIES >= 0

    def test_max_bug_fix_cycles_is_positive(self):
        assert isinstance(C.SWARM_MAX_BUG_FIX_CYCLES, int)
        assert C.SWARM_MAX_BUG_FIX_CYCLES >= 1


class TestRoutingThresholds:
    def test_confidence_threshold_is_float_in_0_1(self):
        assert isinstance(C.LOCAL_ROUTER_CONFIDENCE_THRESHOLD, float)
        assert 0.0 < C.LOCAL_ROUTER_CONFIDENCE_THRESHOLD < 1.0

    def test_semantic_tool_threshold_is_float_in_0_1(self):
        assert isinstance(C.SEMANTIC_TOOL_THRESHOLD, float)
        assert 0.0 < C.SEMANTIC_TOOL_THRESHOLD < 1.0
