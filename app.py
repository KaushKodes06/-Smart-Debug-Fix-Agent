"""
app.py — Smart Debug & Fix Agent  |  Web UI Server
===================================================
Lightweight Flask server that wraps the existing debug_agent.
Run:  python app.py
Then open: http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify
from agents.debug_agent import debug_from_dict

app = Flask(__name__)


@app.after_request
def no_cache(response):
    """Prevent browser from caching any response so JS changes are always picked up."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/debug", methods=["POST"])
def api_debug():
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON payload"}), 400

    code  = (payload.get("code")  or "").strip()
    error = (payload.get("error") or "").strip()

    if not code or not error:
        return jsonify({"error": "'code' and 'error' are required fields"}), 422

    try:
        result_json = debug_from_dict({
            "code":               code,
            "error":              error,
            "expected_behavior":  (payload.get("expected_behavior") or "").strip(),
            "language":           payload.get("language", "python"),
        })
        import json
        return jsonify(json.loads(result_json))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
