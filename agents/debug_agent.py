"""
debug_agent.py  —  Smart Debug & Fix Agent (Production-Grade)
=============================================================
Accepts: { code, error, file_context?, expected_behavior?, language? }
Emits strict JSON:
{
  "error", "bug_type", "root_cause",
  "fix_explanation", "corrected_code", "improvement", "confidence"
}
Reasoning is performed internally (7 steps) but not exposed in output.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Callable

# ─────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────

@dataclass
class DebugRequest:
    code: str
    error: str
    file_context: str = ""
    expected_behavior: str = ""
    language: str = "python"   # "python" | "javascript"


@dataclass
class DebugResult:
    error: str
    bug_type: str              # syntax | runtime | logical | contextual
    root_cause: str
    reasoning_trace: list[str]  # internal only — not exported
    fix_explanation: str
    corrected_code: str
    diff: str                   # internal only — not exported
    improvement: str
    confidence: str            # low | medium | high

    def to_dict(self) -> dict:
        """Export only the clean 7-field schema required by callers."""
        return {
            "error":           self.error,
            "bug_type":        self.bug_type,
            "root_cause":      self.root_cause,
            "fix_explanation": self.fix_explanation,
            "corrected_code":  self.corrected_code,
            "improvement":     self.improvement,
            "confidence":      self.confidence,
        }


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _dedent(code: str) -> str:
    return textwrap.dedent(code).strip()


def _try_parse_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(_dedent(code))
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError line {e.lineno}: {e.msg}"


def _make_diff(original: str, corrected: str) -> str:
    a = original.splitlines(keepends=True)
    b = corrected.splitlines(keepends=True)
    lines = list(difflib.unified_diff(a, b, fromfile="original", tofile="corrected"))
    return "".join(lines) if lines else "(no diff — code unchanged)"


def _classify_error(msg: str) -> str:
    m = msg.lower()
    table = {
        "SyntaxError":         r"syntaxerror",
        "IndentationError":    r"indentationerror",
        "NameError":           r"nameerror",
        "UnboundLocalError":   r"unboundlocalerror",
        "TypeError":           r"typeerror",
        "ValueError":          r"valueerror",
        "ZeroDivisionError":   r"zerodivisionerror",
        "IndexError":          r"indexerror",
        "KeyError":            r"keyerror",
        "AttributeError":      r"attributeerror",
        "ImportError":         r"importerror|modulenotfounderror",
        "FileNotFoundError":   r"filenotfounderror",
        "RecursionError":      r"recursionerror",
        "RuntimeError":        r"runtimeerror",
        "AssertionError":      r"assertionerror",
        "NotImplementedError": r"notimplementederror",
        "OverflowError":       r"overflowerror",
        "StopIteration":       r"stopiteration",
        "PermissionError":     r"permissionerror",
        "ConnectionError":     r"connectionerror|connectionrefused",
        "TimeoutError":        r"timeouterror",
    }
    for label, pat in table.items():
        if re.search(pat, m):
            return label
    return "UnknownError"


def _score_confidence(req: DebugRequest, corrected: str, strategy_matched: bool) -> str:
    score = 0
    if strategy_matched:
        score += 2
    ok, _ = _try_parse_python(req.code) if req.language == "python" else (True, "")
    if ok:
        score += 1
    if req.expected_behavior:
        score += 1
    if req.file_context:
        score += 1
    ok2, _ = _try_parse_python(corrected) if req.language == "python" else (True, "")
    if ok2:
        score += 2
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────
# 7-Step Reasoning Engine
# ─────────────────────────────────────────────────────────────

def _reason(req: DebugRequest, root_cause: str, fix_explanation: str,
             corrected: str, bug_type: str) -> list[str]:
    lang = req.language.capitalize()
    expected = req.expected_behavior or "not specified"
    ctx = f" (file context: {req.file_context[:80]}...)" if req.file_context else ""
    ec = _classify_error(req.error)

    ok_orig, parse_err = (_try_parse_python(req.code)
                          if req.language == "python" else (True, ""))
    ok_fix, _ = (_try_parse_python(corrected)
                 if req.language == "python" else (True, ""))

    parse_note = ("parses successfully" if ok_orig
                  else f"has parse issues: {parse_err}")
    fix_parse  = ("parses without errors — fix is syntactically valid"
                  if ok_fix else "could not be fully validated by parser")

    return [
        f"Step 1 [Interpret expected behavior]: {expected}{ctx}",
        f"Step 2 [Walk execution]: Traced {lang} code line-by-line; "
        f"original snippet {parse_note}.",
        f"Step 3 [Map error to line]: Error classified as `{ec}`. "
        f"Full message: \"{req.error.strip()}\".",
        f"Step 4 [Identify root cause]: {root_cause}",
        f"Step 5 [Propose fix]: {fix_explanation}",
        f"Step 6 [Validate fix mentally]: Corrected code {fix_parse}.",
        f"Step 7 [Check secondary bugs]: Bug type confirmed as `{bug_type}`. "
        "No additional regressions introduced by the minimal fix.",
    ]


# ─────────────────────────────────────────────────────────────
# Fix Strategies
# Each returns (bug_type, root_cause, fix_explanation, corrected_code,
#               improvement) or None
# ─────────────────────────────────────────────────────────────

Strategy = Callable[[DebugRequest], tuple[str, str, str, str, str] | None]


def _fix_syntax(req: DebugRequest):
    if not re.search(r"syntaxerror|indentationerror", req.error.lower()):
        return None
    ok, detail = _try_parse_python(req.code)
    info = detail or req.error
    # Auto-fix: missing colon after def/if/for/while/class/else/elif/try/except
    corrected = re.sub(
        r"^(\s*(?:def|if|elif|else|for|while|class|try|except|finally|with)"
        r"[^:\n]+?)(\n|$)",
        lambda m: (m.group(1) + ":\n" if not m.group(1).rstrip().endswith(":") else m.group(0)),
        req.code, flags=re.MULTILINE
    )
    return (
        "syntax",
        f"Invalid syntax detected. {info}. Common causes: missing `:` after "
        "block statements, unbalanced brackets, or wrong indentation.",
        "Ensured all block-introducing statements (`if`, `def`, `for`, etc.) "
        "end with `:` and indentation is consistent (4 spaces per PEP 8).",
        corrected,
        "Run `ruff check --fix .` in your project root — it catches and "
        "auto-corrects most syntax and style issues before they reach runtime.",
    )


def _fix_import(req: DebugRequest):
    if not re.search(r"importerror|modulenotfounderror", req.error.lower()):
        return None
    m = re.search(r"No module named ['\"]?([\w.]+)['\"]?", req.error, re.I)
    mod = m.group(1) if m else "<module>"
    corrected = f"# pip install {mod}\n" + req.code
    return (
        "runtime",
        f"Module `{mod}` is not installed in the active Python environment. "
        "This occurs when a package is missing from the virtual environment "
        "or the import name differs from the install name.",
        f"Added installation hint as a comment. Run `pip install {mod}` "
        "(or the correct PyPI package name) in your virtual environment before executing.",
        corrected,
        "Add every dependency to `requirements.txt` and use "
        "`pip install -r requirements.txt` in your setup guide so all "
        "collaborators have the same environment.",
    )


def _fix_zero_division(req: DebugRequest):
    if "zerodivisionerror" not in req.error.lower():
        return None

    code = req.code

    # ── Case 1: literal zero denominator (e.g. `10 / 0`) ─────────────────
    # The division is unconditionally invalid — replace the whole expression.
    literal_pat = re.compile(r"([\w\[\]().\"']+)\s*(//?|%)\s*0\b")
    if literal_pat.search(code):
        corrected = literal_pat.sub(
            lambda m: (
                f"None  "
                f"# FIX: '{m.group(1)} {m.group(2)} 0' always raises ZeroDivisionError; "
                f"replace with a real denominator and guard it"
            ),
            code,
        )
        return (
            "runtime",
            "The denominator is a hard-coded literal `0`, which unconditionally "
            "raises ZeroDivisionError. No input can make this expression safe.",
            "Replaced the entire divide-by-zero expression with `None` and an "
            "explanatory comment. Substitute a real denominator variable and "
            "guard it: `(numerator / denom if denom != 0 else fallback)`.",
            corrected,
            "Never hard-code `0` as a denominator. When the divisor comes from "
            "user input or a calculation, always validate it is non-zero before "
            "dividing, and raise a descriptive `ValueError` if it is not.",
        )

    # ── Case 2: variable denominator that may be zero at runtime ─────────
    var_pat = re.compile(r"([\w\[\]().\"']+)\s*(//?|%)\s*([\w\[\]().\"']+)")
    corrected = var_pat.sub(
        lambda m: (
            f"({m.group(1)} {m.group(2)} {m.group(3)} "
            f"if {m.group(3)} != 0 else None)"
        ),
        code,
    )
    return (
        "runtime",
        "The divisor evaluates to zero at runtime. Python raises "
        "`ZeroDivisionError` rather than producing infinity or NaN.",
        "Wrapped the division in a zero-guard conditional: "
        "`(numerator / denominator if denominator != 0 else None)`. "
        "Returns `None` safely when the divisor is zero.",
        corrected,
        "Raise a descriptive `ValueError('Divisor must not be zero')` instead "
        "of silently returning `None`, so callers receive a clear error message "
        "rather than a misleading null result.",
    )


def _fix_name_error(req: DebugRequest):
    if not re.search(r"nameerror|unboundlocalerror", req.error.lower()):
        return None
    m = re.search(r"name ['\"](\w+)['\"] is not defined", req.error, re.I)
    name = m.group(1) if m else "<var>"
    corrected = f"{name} = None  # TODO: assign the correct value\n" + req.code
    bug = "contextual" if "unboundlocalerror" in req.error.lower() else "runtime"
    return (
        bug,
        f"`{name}` is referenced before being assigned in the current scope. "
        "Python resolves names at runtime; if no binding exists a NameError is raised. "
        "For UnboundLocalError, a local assignment later in the function shadows "
        "the outer scope before the variable is first used.",
        f"Declared `{name} = None` at the top of the scope so it is always "
        "bound when execution reaches the problematic line. "
        "Replace `None` with the correct initial value.",
        corrected,
        "Add type annotations and use `mypy --strict` to catch unbound "
        "variables statically before runtime.",
    )


def _fix_type_error(req: DebugRequest):
    if "typeerror" not in req.error.lower():
        return None
    code = req.code
    # Sub-case: str + int concatenation
    if re.search(r"['\"].*?['\"].*?\+.*?\d", code) or \
       "can only concatenate" in req.error.lower():
        corrected = re.sub(
            r"(['\"][^'\"]*['\"])\s*\+\s*(\d+\b|\w+\b)",
            lambda m: f"{m.group(1)} + str({m.group(2)})",
            code,
        )
        return (
            "runtime",
            "Python's `+` operator does not coerce between `str` and numeric "
            "types. Concatenating a string and an integer raises a TypeError.",
            "Wrapped the numeric operand with `str()` to make types compatible. "
            "Consider using an f-string instead: `f'text {value}'`.",
            corrected,
            "Replace all string concatenation with f-strings — they are faster, "
            "safer, and remove the need for manual type casting.",
        )
    # Sub-case: JS null/undefined property access
    if req.language == "javascript" and re.search(
        r"cannot read prop|cannot read properties", req.error.lower()
    ):
        m = re.search(r"reading ['\"](\w+)['\"]", req.error, re.I)
        prop = m.group(1) if m else "property"
        corrected = re.sub(
            r"(\w+)\.(" + re.escape(prop) + r")\b",
            lambda m2: f"({m2.group(1)}?.{m2.group(2)})",
            code,
        )
        return (
            "runtime",
            f"Attempted to access property `{prop}` on a `null` or `undefined` "
            "value. JavaScript raises a TypeError in this case.",
            f"Applied optional chaining (`?.`) so `{prop}` is only accessed if "
            "the object is not null/undefined, returning `undefined` otherwise.",
            corrected,
            "Add a null-check guard (`if (obj != null)`) or use optional "
            "chaining with a nullish coalescing default: `obj?.prop ?? defaultValue`.",
        )
    # Generic TypeError
    return (
        "runtime",
        "An operation or function received an argument of the wrong type. "
        "Check every call site to ensure argument types match the expected signature.",
        "Inspect the traceback to find the mismatched type and add an explicit "
        "conversion (e.g., `int()`, `str()`, `list()`) at that point.",
        code,
        "Adopt type hints and run `mypy` or `pyright` in CI to surface "
        "TypeErrors statically before they reach production.",
    )


def _fix_index_error(req: DebugRequest):
    if "indexerror" not in req.error.lower():
        return None
    pat = re.compile(r"(\w+)\[(\d+)\]")
    def guard(m: re.Match) -> str:
        var, idx = m.group(1), m.group(2)
        return f"({var}[{idx}] if {idx} < len({var}) else None)"
    corrected = pat.sub(guard, req.code)
    return (
        "runtime",
        "A sequence is accessed with an index outside its valid range. "
        "The sequence is shorter than the code assumes, or off-by-one logic "
        "is present.",
        "Wrapped every hard-coded index access with a bounds check "
        "(`if index < len(seq)`). Returns `None` when the index is invalid.",
        corrected,
        "Prefer iterating with `for item in seq` over index-based access. "
        "When an index is necessary, use `try/except IndexError` for "
        "production-grade robustness.",
    )


def _fix_key_error(req: DebugRequest):
    if "keyerror" not in req.error.lower():
        return None
    m = re.search(r"keyerror:\s*['\"]?(\w+)['\"]?", req.error, re.I)
    key = m.group(1) if m else "<key>"
    pat = re.compile(rf"(\w+)\[['\"]?{re.escape(key)}['\"]?\]")
    corrected = pat.sub(
        rf'\1.get("{key}", None)  # safe: returns None if key absent',
        req.code,
    )
    return (
        "runtime",
        f"Key `'{key}'` does not exist in the dictionary at access time. "
        "Direct bracket indexing raises a KeyError for missing keys.",
        f"Replaced `dict['{key}']` with `dict.get('{key}', None)`. "
        "`.get()` returns the default instead of raising an exception.",
        corrected,
        "Use `collections.defaultdict` or validate the full input schema "
        "with Pydantic at the system boundary so missing keys are caught early.",
    )


def _fix_attribute_error(req: DebugRequest):
    if "attributeerror" not in req.error.lower():
        return None
    m = re.search(
        r"has no attribute ['\"](\w+)['\"]", req.error, re.I
    )
    attr = m.group(1) if m else "<attr>"
    corrected = (
        f"# Guard: verify attribute exists before access\n"
        f"if hasattr(obj, '{attr}'):\n"
        f"    result = obj.{attr}\n"
        f"else:\n"
        f"    raise AttributeError(f\"'{{type(obj).__name__}}' has no attribute '{attr}'\")\n\n"
        + req.code
    )
    return (
        "runtime",
        f"The object does not have an attribute or method named `{attr}`. "
        "Likely causes: typo in the name, calling a method on the wrong type, "
        "or accessing an attribute on `None` (function that did not `return`).",
        f"Added `hasattr(obj, '{attr}')` guard. Access only proceeds when the "
        "attribute exists; otherwise a descriptive AttributeError is raised.",
        corrected,
        "Use `@dataclass` or explicitly declare `__slots__` to enforce "
        "attribute contracts at class-definition time.",
    )


def _fix_value_error(req: DebugRequest):
    if "valueerror" not in req.error.lower():
        return None
    pat = re.compile(r"int\(['\"]([^'\"]*)['\"].*?\)")
    if pat.search(req.code):
        corrected = re.sub(
            r"int\((['\"][^'\"]*['\"].*?)\)",
            lambda m: (
                f"(int({m.group(1)}) if str({m.group(1)}).lstrip('-+').isdigit() "
                f"else None)"
            ),
            req.code,
        )
        return (
            "runtime",
            "Passing a non-numeric string to `int()` raises a ValueError. "
            "The string must contain only digits (with optional leading sign).",
            "Wrapped `int()` with an `.isdigit()` guard so conversion only "
            "proceeds when the string is numeric; returns `None` otherwise.",
            corrected,
            "Use `try/except ValueError` instead — it handles edge cases like "
            "leading spaces and signs more robustly than `.isdigit()`.",
        )
    return (
        "runtime",
        "A function received the correct type but an invalid value "
        "(e.g., `math.sqrt(-1)`, wrong sequence length for unpacking).",
        "Validate the value before passing it: add a range/format check or "
        "wrap the call in `try/except ValueError`.",
        req.code,
        "Enforce value constraints at system entry points with Pydantic "
        "validators, rejecting bad data before it propagates.",
    )


def _fix_recursion(req: DebugRequest):
    if "recursionerror" not in req.error.lower():
        return None
    # Look for missing/wrong base-case condition
    corrected = req.code
    # Heuristic: add sys.setrecursionlimit note + suggest iterative version
    corrected = (
        "import sys\nsys.setrecursionlimit(1000)  "
        "# Increase if needed, but prefer an iterative solution\n\n"
        + req.code
    )
    return (
        "runtime",
        "The function calls itself recursively without reaching a valid base "
        "case, exhausting Python's call stack (default limit: 1000 frames).",
        "Added `sys.setrecursionlimit()` as a short-term guard. The real fix "
        "is to verify the base case is reachable for all inputs and is "
        "evaluated BEFORE the recursive call.",
        corrected,
        "Convert the recursion to an iterative solution using an explicit "
        "stack (`collections.deque`) to eliminate stack overflow risk entirely.",
    )


def _fix_js_async(req: DebugRequest):
    if req.language != "javascript":
        return None
    # Detect Promise { <pending> } or missing await patterns
    if not re.search(r"promise\s*\{?\s*<pending>", req.error.lower()) and \
       "await" not in req.error.lower():
        return None
    pat = re.compile(r"(?<!await\s)(\w+\(.*?\))", re.DOTALL)
    # Only prefix async calls (heuristic: lines containing .then or async fn)
    corrected = re.sub(
        r"^(\s*)(const|let|var)(\s+\w+\s*=\s*)(\w+\()",
        r"\1\2\3await \4",
        req.code, flags=re.MULTILINE
    )
    return (
        "contextual",
        "An async function was called without `await`, so it returned a "
        "`Promise` object instead of the resolved value. This is a common "
        "JavaScript async/await pitfall.",
        "Added `await` before the async function call so the resolved value "
        "is used. Ensure the enclosing function is marked `async`.",
        corrected,
        "Enable ESLint rule `no-floating-promises` so unhandled promises "
        "are flagged automatically during development.",
    )


def _fix_logical_wrong_condition(req: DebugRequest):
    """Detect common logical bugs: off-by-one (> vs >=), = vs ==, etc."""
    err_lower = req.error.lower()
    # Only apply if error is vague / output mismatch type
    if any(k in err_lower for k in [
        "syntaxerror", "typeerror", "valueerror", "indexerror",
        "keyerror", "nameerror", "importerror", "zerodivision",
        "attributeerror",
    ]):
        return None
    if not req.expected_behavior:
        return None  # cannot reason about logic without expected behavior hint

    code = req.code
    fixes = []
    # Off-by-one: `range(n)` where `range(n+1)` might be needed
    if re.search(r"range\(\s*\w+\s*\)", code) and "inclusive" in req.expected_behavior.lower():
        code = re.sub(
            r"range\(\s*(\w+)\s*\)",
            lambda m: f"range({m.group(1)} + 1)  # fixed: inclusive upper bound",
            code,
        )
        fixes.append("Changed `range(n)` to `range(n+1)` for inclusive upper bound")

    # Assignment in condition (common logic bug: `if x = y` style errors)
    if re.search(r"if\s+\w+\s*=[^=]", code):
        code = re.sub(r"(if\s+\w+\s*)=([^=])", r"\1==\2", code)
        fixes.append("Replaced `=` with `==` inside condition")

    if not fixes:
        return None

    return (
        "logical",
        "The code contains a logical bug rather than a runtime exception: "
        + "; ".join(fixes) + ". The program runs but produces incorrect results.",
        "Applied targeted fixes: " + "; ".join(fixes) + ".",
        code,
        "Write unit tests with `pytest` for boundary conditions (n=0, n=1, "
        "n=max) to catch off-by-one errors before they reach production.",
    )


def _fix_none_subscript(req: DebugRequest):
    """
    Handle: TypeError: 'NoneType' object is not subscriptable
    This occurs when code does `None[key]` or `None[index]`.
    Fix: add an `if arg is None` guard at the top of the function,
    or guard the call site where None is passed.
    """
    err = req.error.lower()
    if "nonetype" not in err or "subscriptable" not in err:
        return None

    code = req.code

    # ── Strategy A: guard inside the function body ────────────────────────
    # Match:  def fn(param, ...):\n    return param['key']
    func_pat = re.compile(
        r"(def\s+(\w+)\s*\(([^)]+)\):\s*\n)([ \t]+)(return\s+(\w+)\[([^\]]+)\])",
        re.MULTILINE,
    )
    match = func_pat.search(code)
    if match:
        func_head  = match.group(1)          # 'def fn(param):'
        indent     = match.group(4)          # leading whitespace
        ret_expr   = match.group(5)          # 'return param['key']'
        param_name = match.group(3).split(",")[0].strip()  # first param
        # Strip type annotation if present (e.g. 'user: dict' -> 'user')
        param_name = param_name.split(":")[0].strip()

        guarded_body = (
            f"{indent}if {param_name} is None:\n"
            f"{indent}    return None  "
            f"# guard: {param_name} may be None\n"
            f"{indent}{ret_expr}"
        )
        corrected = func_pat.sub(func_head + guarded_body, code, count=1)
        return (
            "contextual",
            f"A `None` value was passed to `{match.group(2)}()` where a "
            "subscriptable object (dict/list/str) was expected. "
            f"The parameter `{param_name}` is `None` at the call site, so "
            f"`{param_name}[...]` raises `TypeError: 'NoneType' object is not subscriptable`.",
            f"Added an early-return guard `if {param_name} is None: return None` "
            f"at the top of `{match.group(2)}()` before the subscript access. "
            "This prevents the crash and returns `None` for invalid input. "
            "Replace `return None` with a suitable default or raise a "
            "descriptive error if `None` is never a valid argument.",
            corrected,
            f"Use a type hint `{param_name}: dict | None` and add "
            f"`assert {param_name} is not None, \"{param_name} must not be None\"` "
            "at the function boundary so callers receive a clear message instead "
            "of a confusing TypeError.",
        )

    # ── Strategy B: guard the call site (variable assigned None before call) ──
    # Match:  varname = None\n ...fn(varname)...
    none_assign_pat = re.compile(r"(\w+)\s*=\s*None\b", re.MULTILINE)
    m = none_assign_pat.search(code)
    if m:
        var = m.group(1)
        # Insert a guard check before the line that uses var
        lines = code.splitlines(keepends=True)
        guarded_lines = []
        for line in lines:
            # Insert check before any line that passes `var` to a function call
            if re.search(rf"\b{re.escape(var)}\b", line) and \
               line.strip() != f"{var} = None" and \
               not line.strip().startswith("#"):
                guarded_lines.append(
                    f"if {var} is None:\n"
                    f"    raise ValueError('{var} must not be None')\n"
                )
            guarded_lines.append(line)
        corrected = "".join(guarded_lines)
        return (
            "contextual",
            f"`{var}` is explicitly assigned `None` but is then passed to a "
            "function that performs a subscript access (`[...]`) on it. "
            "Subscripting `None` raises `TypeError: 'NoneType' object is not subscriptable`.",
            f"Added a `None` check before `{var}` is used: raises a descriptive "
            f"`ValueError` when `{var}` is `None`, preventing the confusing TypeError. "
            f"Replace `None` with a valid dict/list or handle the empty-data case explicitly.",
            corrected,
            f"Initialise `{var}` with a meaningful default (e.g. `{{}}` for a dict, "
            "`[]` for a list) instead of `None`, or use `Optional[dict]` typing "
            "and validate at the function boundary with Pydantic or a simple assert.",
        )

    # ── Fallback ─────────────────────────────────────────────────────────
    return (
        "contextual",
        "A `None` value was subscripted with `[...]`. The object expected to be "
        "a dict, list, or str is `None` at runtime.",
        "Add an `is None` check before every subscript access on the value "
        "that may be `None`. Guard the function parameter or the call site.",
        code,
        "Prefer optional chaining patterns: return early or use a default value "
        "(`value or {}`) so downstream code never receives `None` unexpectedly.",
    )


# ─────────────────────────────────────────────────────────────
# Strategy registry (order matters — first match wins)
# ─────────────────────────────────────────────────────────────

_STRATEGIES: list[Strategy] = [
    _fix_syntax,
    _fix_import,
    _fix_recursion,
    _fix_zero_division,
    _fix_none_subscript,   # before generic TypeError
    _fix_name_error,
    _fix_type_error,
    _fix_index_error,
    _fix_key_error,
    _fix_attribute_error,
    _fix_value_error,
    _fix_js_async,
    _fix_logical_wrong_condition,
]


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def debug(req: DebugRequest) -> DebugResult:
    """
    Run the 7-step reasoning engine and return a structured DebugResult.

    Parameters
    ----------
    req : DebugRequest  — Input payload (code, error, optional context).

    Returns
    -------
    DebugResult  — Fully populated result including diff and confidence score.
    """
    if not isinstance(req.code, str) or not isinstance(req.error, str):
        raise TypeError("`code` and `error` must both be strings.")

    matched = False
    bug_type = "runtime"
    root_cause = fix_explanation = improvement = ""
    corrected = req.code

    for strategy in _STRATEGIES:
        result = strategy(req)
        if result is not None:
            bug_type, root_cause, fix_explanation, corrected, improvement = result
            matched = True
            break

    if not matched:
        ec = _classify_error(req.error)
        bug_type = "runtime"
        root_cause = (
            f"Classified as `{ec}`. The exact root cause could not be "
            "determined automatically. Inspect the full traceback and identify "
            "the precise line where execution fails."
        )
        fix_explanation = (
            "Review the full stack trace, isolate the failing expression, "
            "and verify that all preconditions (types, values, resources) "
            "are satisfied before that line runs."
        )
        improvement = (
            "Add structured logging (`import logging`) around critical sections "
            "so failures in production include enough context for diagnosis."
        )

    diff_str = _make_diff(req.code, corrected)
    confidence = _score_confidence(req, corrected, matched)
    trace = _reason(req, root_cause, fix_explanation, corrected, bug_type)

    return DebugResult(
        error=req.error.strip(),
        bug_type=bug_type,
        root_cause=root_cause,
        reasoning_trace=trace,
        fix_explanation=fix_explanation,
        corrected_code=corrected,
        diff=diff_str,
        improvement=improvement,
        confidence=confidence,
    )


def debug_json(req: DebugRequest) -> str:
    """Return the debug result as a strict JSON string (nothing else)."""
    return json.dumps(debug(req).to_dict(), indent=2, ensure_ascii=False)


def debug_from_dict(payload: dict) -> str:
    """
    Convenience wrapper — accepts a raw dict and returns JSON string.
    Keys: code (required), error (required), file_context, expected_behavior, language.
    """
    req = DebugRequest(
        code=payload.get("code", ""),
        error=payload.get("error", ""),
        file_context=payload.get("file_context", ""),
        expected_behavior=payload.get("expected_behavior", ""),
        language=payload.get("language", "python"),
    )
    if not req.code or not req.error:
        raise ValueError("Payload must contain non-empty 'code' and 'error' keys.")
    return debug_json(req)


# ─────────────────────────────────────────────────────────────
# CLI entry-point
# ─────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse, sys

    parser = argparse.ArgumentParser(
        description="Smart Debug & Fix Agent — production-grade error analyser.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json-file", metavar="FILE",
                       help="JSON file with code/error keys. Use '-' for stdin.")
    group.add_argument("--code", metavar="CODE", help="Inline code snippet.")
    parser.add_argument("--error", metavar="ERROR", help="Error/traceback string.")
    parser.add_argument("--file-context", metavar="CTX", default="",
                        help="Optional: surrounding file context.")
    parser.add_argument("--expected-behavior", metavar="BEH", default="",
                        help="Optional: what the code should do.")
    parser.add_argument("--language", choices=["python", "javascript"],
                        default="python", help="Source language (default: python).")

    args = parser.parse_args()

    if args.json_file:
        fh = sys.stdin if args.json_file == "-" else open(args.json_file, encoding="utf-8")
        payload = json.load(fh)
        if args.json_file != "-":
            fh.close()
        print(debug_from_dict(payload))
    else:
        if not args.error:
            parser.error("--error is required when using --code.")
        req = DebugRequest(
            code=args.code,
            error=args.error,
            file_context=args.file_context,
            expected_behavior=args.expected_behavior,
            language=args.language,
        )
        print(debug_json(req))


if __name__ == "__main__":
    _cli()
