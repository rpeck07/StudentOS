# app.py
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import os
import json
import time
from uuid import uuid4
from datetime import date

# If these imports fail on Render for any reason, the app should STILL start.
ENGINE_OK = True
try:
    from engine import (
        load_assignments,
        rank_assignments_by_danger,
        hours_next_days,
        workload_text_bars,
        gpa_impact_estimates,  # optional; if missing, engine_ok will flip false
    )
except Exception as e:
    ENGINE_OK = False
    ENGINE_IMPORT_ERROR = str(e)

BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, "assignments.json")

app = Flask(__name__)
CORS(app)

# ----------------------------
# Helpers (simple JSON storage)
# ----------------------------
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
    return auth.replace("Bearer ", "").strip()

# ----------------------------
# Health + home (web page)
# ----------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "engine_ok": ENGINE_OK,
        "data_file_exists": os.path.exists(DATA_FILE),
    }, 200

@app.get("/")
def home():
    # Always render something, even if engine or data fails.
    today = date.today()

    if not ENGINE_OK:
        return (
            f"<h1>StudentOS is running ✅</h1>"
            f"<p>But engine import failed on server:</p>"
            f"<pre>{ENGINE_IMPORT_ERROR}</pre>"
            f"<p>Go to <code>/health</code> for quick status.</p>",
            200,
        )

    # Load assignments (if missing, treat as empty)
    try:
        assignments = load_assignments(DATA_FILE) if os.path.exists(DATA_FILE) else []
    except Exception as e:
        assignments = []
        load_error = str(e)
    else:
        load_error = None

    danger_rows = rank_assignments_by_danger(assignments, today) if assignments else []

    # Analytics (next 3 days) – keep safe if empty
    try:
        bars = workload_text_bars(assignments, today, window_days=3) if assignments else []
        nxt = hours_next_days(assignments, today, 3) if assignments else {"days": []}
        # nxt is expected to be a dict with "days": [...], where each has {"hours": ...} in your earlier usage
        # but your engine returns {"days": [{"total_hours": ...}, ...]}
        total_next_3 = 0
        if isinstance(nxt, dict) and isinstance(nxt.get("days"), list):
            total_next_3 = round(sum(d.get("total_hours", 0) for d in nxt["days"]), 2)
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
# API (Expo expects these)
# ----------------------------

@app.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    # v1: demo token (no DB yet)
    return jsonify({"access_token": f"demo-{username}"}), 200

@app.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    # v1: demo token (no DB yet)
    return jsonify({"access_token": f"demo-{username}"}), 200

@app.get("/assignments")
def get_assignments():
    token = _require_token()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    items = _read_json_file(DATA_FILE)
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

    items = _read_json_file(DATA_FILE)
    items.append(item)
    _write_json_file(DATA_FILE, items)

    return jsonify(item), 200

@app.delete("/assignments/<id>")
def delete_assignment(id):
    token = _require_token()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    items = _read_json_file(DATA_FILE)
    new_items = [x for x in items if str(x.get("id")) != str(id)]
    _write_json_file(DATA_FILE, new_items)
    return "", 204

if __name__ == "__main__":
    # Local dev only. Render ignores this and uses gunicorn.
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)