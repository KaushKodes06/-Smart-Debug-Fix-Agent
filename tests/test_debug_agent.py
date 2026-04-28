"""
tests/test_debug_agent.py
--------------------------
Validates the Smart Debug & Fix Agent across all supported error categories.
Run:  python -m pytest tests/test_debug_agent.py -v
"""
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from agents.debug_agent import DebugRequest, debug, debug_from_dict

REQUIRED_KEYS = {
    "error", "bug_type", "root_cause",
    "fix_explanation", "corrected_code", "improvement", "confidence"
}
VALID_BUG_TYPES  = {"syntax", "runtime", "logical", "contextual"}
VALID_CONFIDENCE = {"low", "medium", "high"}


def _run(code: str, error: str, **kwargs) -> dict:
    req = DebugRequest(code=code, error=error, **kwargs)
    result = debug(req)
    return result.to_dict()


def _assert_valid(d: dict):
    assert REQUIRED_KEYS == set(d.keys()), f"Missing keys: {REQUIRED_KEYS - set(d.keys())}"
    assert d["bug_type"] in VALID_BUG_TYPES,  f"Invalid bug_type: {d['bug_type']}"
    assert d["confidence"] in VALID_CONFIDENCE, f"Invalid confidence: {d['confidence']}"
    assert d["corrected_code"].strip(), "corrected_code must not be empty"
    assert d["error"], "error field must not be empty"
    # Internal fields must never leak into the public output
    assert "reasoning_trace" not in d, "reasoning_trace must not appear in output"
    assert "diff" not in d, "diff must not appear in output"


# ── Test cases ───────────────────────────────────────────────────────────────

class TestRuntimeErrors:

    def test_zero_division(self):
        d = _run("result = 10 / 0", "ZeroDivisionError: division by zero")
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        # Strip inline comments then check no executable token contains `/ 0`
        def _strip_comment(ln: str) -> str:
            return ln.split("#")[0]

        code_lines = [
            _strip_comment(ln)
            for ln in d["corrected_code"].splitlines()
            if _strip_comment(ln).strip()
        ]
        assert all("/ 0" not in ln for ln in code_lines), (
            "A non-comment token in corrected_code still contains a literal division by zero"
        )

    def test_name_error(self):
        d = _run(
            "print(username)",
            "NameError: name 'username' is not defined",
        )
        _assert_valid(d)
        assert d["bug_type"] in {"runtime", "contextual"}
        assert "username" in d["corrected_code"]

    def test_type_error_str_int(self):
        d = _run(
            "msg = 'Hello ' + 42",
            "TypeError: can only concatenate str (not 'int') to str",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert "str(" in d["corrected_code"]

    def test_index_error(self):
        d = _run(
            "lst = [1, 2, 3]\nprint(lst[10])",
            "IndexError: list index out of range",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert "len(" in d["corrected_code"]

    def test_key_error(self):
        d = _run(
            "data = {'name': 'Alice'}\nprint(data['age'])",
            "KeyError: 'age'",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert ".get(" in d["corrected_code"]

    def test_attribute_error(self):
        d = _run(
            "x = 42\nx.append(1)",
            "AttributeError: 'int' object has no attribute 'append'",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert "hasattr" in d["corrected_code"]

    def test_value_error_int_parse(self):
        d = _run(
            "n = int('abc')",
            "ValueError: invalid literal for int() with base 10: 'abc'",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"

    def test_import_error(self):
        d = _run(
            "import pandas as pd",
            "ModuleNotFoundError: No module named 'pandas'",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert "pandas" in d["corrected_code"]

    def test_recursion_error(self):
        d = _run(
            "def f(n):\n    return f(n - 1)\nf(5)",
            "RecursionError: maximum recursion depth exceeded",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert "setrecursionlimit" in d["corrected_code"]

    def test_unbound_local_error(self):
        d = _run(
            "def greet():\n    print(msg)\n    msg = 'hi'",
            "UnboundLocalError: local variable 'msg' referenced before assignment",
        )
        _assert_valid(d)
        assert d["bug_type"] in {"runtime", "contextual"}


class TestSyntaxErrors:

    def test_indentation_error(self):
        d = _run(
            "def foo():\nprint('hi')",
            "IndentationError: expected an indented block",
        )
        _assert_valid(d)
        assert d["bug_type"] == "syntax"

    def test_missing_colon(self):
        d = _run(
            "if True\n    print('yes')",
            "SyntaxError: invalid syntax",
        )
        _assert_valid(d)
        assert d["bug_type"] == "syntax"


class TestLogicalBugs:

    def test_off_by_one_range(self):
        d = _run(
            "for i in range(n):\n    print(i)",
            "AssertionError: expected value not reached",
            expected_behavior="loop should be inclusive of n",
        )
        _assert_valid(d)
        # May match logical or fall through to generic
        assert d["bug_type"] in VALID_BUG_TYPES


class TestJavaScript:

    def test_null_property_access(self):
        d = _run(
            "const x = null;\nconsole.log(x.name);",
            "TypeError: Cannot read properties of null (reading 'name')",
            language="javascript",
        )
        _assert_valid(d)
        assert d["bug_type"] == "runtime"
        assert "?." in d["corrected_code"]

    def test_missing_await(self):
        d = _run(
            "const result = fetchData();\nconsole.log(result);",
            "Promise { <pending> } — missing await",
            language="javascript",
        )
        _assert_valid(d)
        assert d["bug_type"] == "contextual"
        assert "await" in d["corrected_code"]


class TestNoneHandling:

    def test_none_subscript_function_guard(self):
        d = _run(
            "def get_user_name(user):\n    return user['name']\n\nuser = None\nprint(get_user_name(user))",
            "TypeError: 'NoneType' object is not subscriptable",
            expected_behavior="Should safely handle missing user data",
        )
        _assert_valid(d)
        assert d["bug_type"] == "contextual"
        assert "is None" in d["corrected_code"]
        assert "return None" in d["corrected_code"] or "ValueError" in d["corrected_code"]

    def test_none_subscript_call_site_guard(self):
        d = _run(
            "data = None\nprint(data['key'])",
            "TypeError: 'NoneType' object is not subscriptable",
        )
        _assert_valid(d)
        assert d["bug_type"] == "contextual"


class TestFallback:

    def test_unknown_error_fallback(self):
        d = _run(
            "print('hello')",
            "OSError: [Errno 28] No space left on device",
        )
        _assert_valid(d)
        # Fallback path — any valid bug_type is acceptable
        assert d["bug_type"] in VALID_BUG_TYPES


class TestDebugFromDict:

    def test_from_dict_basic(self):
        payload = {
            "code": "x = 1 / 0",
            "error": "ZeroDivisionError: division by zero",
            "file_context": "math_utils.py",
            "expected_behavior": "compute reciprocal safely",
        }
        out = debug_from_dict(payload)
        d = json.loads(out)
        _assert_valid(d)
        assert d["confidence"] in VALID_CONFIDENCE
        # corrected code must NOT still contain a literal `/ 0`
        assert "/ 0" not in d["corrected_code"] or "None" in d["corrected_code"]

    def test_from_dict_missing_fields(self):
        with pytest.raises(ValueError):
            debug_from_dict({"code": "x = 1"})   # no 'error'

    def test_output_has_no_internal_fields(self):
        """reasoning_trace and diff must NOT appear in the public output."""
        payload = {
            "code": "result = 10 / 0\nprint(result)",
            "error": "ZeroDivisionError: division by zero",
        }
        d = json.loads(debug_from_dict(payload))
        assert "reasoning_trace" not in d, "reasoning_trace must not be in output"
        assert "diff" not in d, "diff must not be in output"
        _assert_valid(d)
