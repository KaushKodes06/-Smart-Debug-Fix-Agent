"""
main.py  —  Smart Debug & Fix Agent entry-point
Usage:
    python main.py                                          # uses test_input.json
    python main.py --code "..." --error "..."
    python main.py --json-file path/to/input.json
    python main.py --language javascript --code "..." --error "..."
"""
import json, sys, argparse
from pathlib import Path
from agents.debug_agent import DebugRequest, debug_json, debug_from_dict

DEFAULT_INPUT = Path(__file__).parent / "test_input.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Smart Debug & Fix Agent — production-grade error analyser.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--json-file", metavar="FILE", default=str(DEFAULT_INPUT),
                   help="JSON file with code/error (use '-' for stdin). Default: test_input.json")
    g.add_argument("--code", metavar="CODE", help="Inline code snippet.")
    p.add_argument("--error",    metavar="ERROR", help="Error/traceback string.")
    p.add_argument("--file-context",      metavar="CTX",  default="",
                   help="Optional surrounding file context.")
    p.add_argument("--expected-behavior", metavar="BEH",  default="",
                   help="Optional description of what the code should do.")
    p.add_argument("--language", choices=["python", "javascript"], default="python",
                   help="Source language (default: python).")
    return p


def main() -> None:
    args = build_parser().parse_args()

    if args.code:
        if not args.error:
            print("Error: --error is required with --code.", file=sys.stderr)
            sys.exit(1)
        req = DebugRequest(
            code=args.code,
            error=args.error,
            file_context=args.file_context or "",
            expected_behavior=args.expected_behavior or "",
            language=args.language,
        )
        print(debug_json(req))
    else:
        src = args.json_file
        if src == "-":
            payload = json.load(sys.stdin)
        else:
            with open(src, encoding="utf-8") as fh:
                payload = json.load(fh)
        # Allow CLI flags to override JSON fields
        if args.file_context:
            payload["file_context"] = args.file_context
        if args.expected_behavior:
            payload["expected_behavior"] = args.expected_behavior
        if args.language != "python":
            payload["language"] = args.language
        print(debug_from_dict(payload))


if __name__ == "__main__":
    main()
