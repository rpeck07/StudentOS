# app.py
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import os
import json
import time
from uuid import uuid4
from datetime import date

ENGINE_OK = True
try:
    from engine import (
        load_assignments,
        rank_assignments_by_danger,
        hours_next_days,
        workload_text_bars,
        gpa_impact_estimates,
    )
except Exception as e:
    ENGINE_OK = False
    ENGINE_IMPORT_ERROR = str(e)

BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, "assignments.json")  # fallback only

app = Flask(__name__)

CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "DELETE", "OPTIONS"],
)

# ----------------------------
# Helpers
# ----------------------------

def _user_file(token: str) -> str:
    """
    FIX #1: Per-user data file so users can't overwrite each other.
    Sanitize the token to make a safe filename.
    """
    safe = token.replace("/", "_").replace("..", "").replace(" ", "_")
    return os.path.join(BASE_DIR, f"data_{safe}.json")


def _read_json_file(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _write_json_file(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _require_token():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.replace("Bearer ", "").strip()
    if not token or token in ("undefined", "null"):
        return None
    return token


# ----------------------------
# Health + home
# ----------------------------

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "engine_ok": ENGINE_OK,
        "data_file_exists": os.path.exists(DATA_FILE),
    }), 200


@app.get("/")
def home():
    today = date.today()

    if not ENGINE_OK:
        return (
            f"<h1>StudentOS is running ✅</h1>"
            f"<p>But engine import failed on server:</p>"
            f"<pre>{ENGINE_IMPORT_ERROR}</pre>"
            f"<p>Go to <code>/health</code> for quick status.</p>",
            200,
        )

    try:
        assignments = load_assignments(DATA_FILE) if os.path.exists(DATA_FILE) else []
    except Exception as e:
        assignments = []
        load_error = str(e)
    else:
        load_error = None

    danger_rows = rank_assignments_by_danger(assignments, today) if assignments else []

    try:
        # FIX #2: correct kwarg name is window_days, not days
        bars = workload_text_bars(assignments, today, window_days=3) if assignments else []

        # FIX #3: hours_next_days returns a LIST of {date, hours} dicts — not a dict with "days" key
        nxt = hours_next_days(assignments, today, window_days=3) if assignments else []
        total_next_3 = round(sum(d["hours"] for d in nxt), 2)

    except Exception:
        bars = []
        total_next_3 = 0

    impacts = []

    return render_template(
        "index.html",
        engine_ok=True,
        load_error=load_error,
        assignments_count=len(assignments),
        danger_rows=danger_rows,
        bars=bars,
        total_next_3=total_next_3,
        impacts=impacts,
    )


# ----------------------------
# Debug
# ----------------------------

@app.post("/debug")
def debug():
    return jsonify({
        "ok": True,
        "headers": dict(request.headers),
        "json": request.get_json(silent=True),
        "raw": request.data.decode("utf-8", errors="ignore"),
    }), 200


# ----------------------------
# Auth
# ----------------------------

@app.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    return jsonify({"access_token": f"demo-{username}"}), 200


@app.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    return jsonify({"access_token": f"demo-{username}"}), 200


# ----------------------------
# Assignments API
# ----------------------------

@app.get("/assignments")
def get_assignments():
    token = _require_token()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    # FIX #1: read from this user's own file
    items = _read_json_file(_user_file(token))
    return jsonify(items), 200


@app.post("/assignments")
def create_assignment():
    token = _require_token()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    body = request.get_json(silent=True) or {}

    name = str(body.get("name", "")).strip()
    weightPercent = body.get("weightPercent")
    dueDate = body.get("dueDate")
    confidence = body.get("confidence")
    estHours = body.get("estHours")

    if not name:
        return jsonify({"error": "name required"}), 400

    item = {
        "id": str(uuid4()),
        "name": name,
        "weightPercent": float(weightPercent or 0),
        "dueDate": str(dueDate or ""),
        "confidence": int(confidence or 3),
        "estHours": float(estHours or 0),
        "createdAt": int(time.time() * 1000),
    }

    # FIX #1: write to this user's own file
    path = _user_file(token)
    items = _read_json_file(path)
    items.append(item)
    _write_json_file(path, items)

    return jsonify(item), 200


@app.delete("/assignments/<id>")
def delete_assignment(id):
    token = _require_token()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    # FIX #1: delete from this user's own file
    path = _user_file(token)
    items = _read_json_file(path)
    new_items = [x for x in items if str(x.get("id")) != str(id)]
    _write_json_file(path, new_items)
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)