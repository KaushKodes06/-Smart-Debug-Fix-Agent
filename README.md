# 🔍 Smart Debug & Fix Agent

**An agentic AI system that diagnoses code errors, traces root causes, and generates verified fixes — structured, reliable, and production-ready.**

---

## What It Does

Smart Debug & Fix Agent functions as an autonomous debugging engineer. Given a code snippet and an error message, it follows a **7-step internal reasoning chain** to produce a precise, structured repair report — not just an error label.

The agent thinks before it fixes:

1. Interprets expected behavior
2. Traces code execution logically
3. Maps the error to specific lines
4. Identifies the true root cause (not just the symptom)
5. Proposes a minimal, correct fix
6. Validates the fix mentally (simulated execution)
7. Checks for secondary regressions

Output is **strict JSON** — no prose, no noise, always machine-readable.

---

## Key Features

- **Agentic reasoning** — structured multi-step analysis, not keyword matching
- **Bug classification** — `syntax | runtime | logical | contextual`
- **Verified fixes** — corrected code is validated before output (no fixes that still crash)
- **Confidence scoring** — `high / medium / low` based on error clarity and context richness
- **Multi-language** — Python and JavaScript
- **Rich context support** — accepts `file_context` and `expected_behavior` for deeper analysis
- **Interactive Web UI** — dark-themed split-panel interface with syntax highlighting
- **CLI & API** — usable as a command-line tool or imported as a Python module
- **21-test suite** — full coverage across all error categories

---

## Tech Stack

| Layer | Technology |
|---|---|
| Core Agent | Python 3.10+, stdlib only (`ast`, `re`, `difflib`, `json`, `dataclasses`) |
| Web Server | Flask 3.x |
| UI | Vanilla HTML5 / CSS3 / JavaScript |
| Syntax Highlighting | highlight.js 11.9 |
| Testing | pytest 7.4+ |

> **Zero runtime dependencies** for the core agent. Flask is only required for the web UI.

---

## Project Structure

```
project/
├── agents/debug_agent.py       # Reasoning engine — pure Python stdlib
├── templates/index.html        # Web UI — single-page, no framework
├── tests/test_debug_agent.py   # 21-case pytest suite
├── app.py                      # Flask server
├── main.py                     # CLI entry point
└── test_input.json             # Sample input
```

---

## Setup

**Requirements:** Python 3.10+

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Run the web UI
python app.py
# → Open http://127.0.0.1:5000

# Or use the CLI
python main.py --code "result = 10 / 0" --error "ZeroDivisionError: division by zero"

# Run tests
python -m pytest tests/test_debug_agent.py -v
```

---

## Usage

### Input format

```json
{
  "code": "def get_user_name(user):\n    return user['name']\n\nuser = None\nprint(get_user_name(user))",
  "error": "TypeError: 'NoneType' object is not subscriptable",
  "expected_behavior": "Should safely handle missing user data",
  "language": "python"
}
```

### Structured output

```json
{
  "error":           "TypeError: 'NoneType' object is not subscriptable",
  "bug_type":        "contextual",
  "root_cause":      "A `None` value was passed to `get_user_name()` where a subscriptable object was expected. `user[...]` raises TypeError because `user` is `None` at the call site.",
  "fix_explanation": "Added `if user is None: return None` before the subscript access. The crash is prevented and the function degrades gracefully for invalid input.",
  "corrected_code":  "def get_user_name(user):\n    if user is None:\n        return None  # guard: user may be None\n    return user['name']\n\nuser = None\nprint(get_user_name(user))",
  "improvement":     "Type-annotate the parameter as `user: dict | None` and use `assert user is not None` at the boundary so callers see a clear message rather than a confusing TypeError.",
  "confidence":      "high"
}
```

### Output schema

| Field | Values | Purpose |
|---|---|---|
| `error` | string | Original error message |
| `bug_type` | `syntax` `runtime` `logical` `contextual` | Root category |
| `root_cause` | string | Why the bug occurred |
| `fix_explanation` | string | What the fix does and why it works |
| `corrected_code` | string | Executable, validated corrected code |
| `improvement` | string | One actionable quality suggestion |
| `confidence` | `high` `medium` `low` | Agent's confidence in the fix |

---

## Supported Error Types

Python: `ZeroDivisionError`, `NameError`, `UnboundLocalError`, `TypeError`, `IndexError`, `KeyError`, `AttributeError`, `ValueError`, `SyntaxError`, `IndentationError`, `ImportError`, `RecursionError`, logical bugs (off-by-one, wrong operators)

JavaScript: `TypeError` (null/undefined access), missing `await` on async calls

---

## Programmatic Usage

```python
from agents.debug_agent import DebugRequest, debug, debug_from_dict

# Via request object
result = debug(DebugRequest(
    code="lst = [1, 2]; print(lst[9])",
    error="IndexError: list index out of range",
    expected_behavior="Print element safely",
))
print(result.bug_type)       # "runtime"
print(result.confidence)     # "high"
print(result.corrected_code) # bounds-guarded version

# Or from a dict / parsed JSON payload
output_json = debug_from_dict({"code": "...", "error": "..."})
```

---

## Real-World Applicability

- **CI/CD integration** — pipe compiler/runtime errors into the agent to get structured fix suggestions automatically
- **IDE plugins** — embed the agent as a code action to surface fixes inline
- **Code review tooling** — attach debug reports to PRs for failing test errors
- **Developer onboarding** — helps junior developers understand *why* errors occur, not just what to change
- **LLM pipelines** — use the structured JSON output as grounded context for larger language model workflows
