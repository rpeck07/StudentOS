# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
)
import bcrypt
import os
import sqlite3
import time
from uuid import uuid4
from datetime import date, timedelta

ENGINE_OK = True
ENGINE_IMPORT_ERROR = ""
try:
    from engine import (
        Assignment,
        parse_date,
        rank_assignments_by_danger,
        hours_next_days,
        workload_text_bars,
        gpa_impact_estimates,
        dashboard_summary,
    )
except Exception as e:
    ENGINE_OK = False
    ENGINE_IMPORT_ERROR = str(e)

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "studentos.db")

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-me")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=30)

jwt = JWTManager(app)

CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "DELETE", "OPTIONS"],
)


# ----------------------------
# DB Setup
# ----------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username   TEXT PRIMARY KEY,
                password   TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id             TEXT PRIMARY KEY,
                username       TEXT NOT NULL,
                name           TEXT NOT NULL,
                weight_percent REAL NOT NULL DEFAULT 0,
                due_date       TEXT NOT NULL DEFAULT '',
                confidence     INTEGER NOT NULL DEFAULT 3,
                est_hours      REAL NOT NULL DEFAULT 0,
                hours_logged   REAL NOT NULL DEFAULT 0,
                created_at     INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                username      TEXT PRIMARY KEY,
                current_grade REAL NOT NULL DEFAULT 85.0
            )
        """)
        # Migration: add hours_logged column if it doesn't exist yet
        try:
            conn.execute("ALTER TABLE assignments ADD COLUMN hours_logged REAL NOT NULL DEFAULT 0")
        except Exception:
            pass  # column already exists
        conn.commit()


init_db()


# ----------------------------
# Helpers
# ----------------------------

def _load_user_assignments(username: str):
    """Load a user's assignments from DB and convert to engine Assignment objects."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE username = ? ORDER BY created_at DESC",
            (username,)
        ).fetchall()

    assignments = []
    for row in rows:
        try:
            # Subtract hours already logged from remaining estimated hours
            remaining = max(0.0, float(row["est_hours"]) - float(row["hours_logged"]))
            assignments.append(Assignment(
                name=str(row["name"]),
                weight_percent=float(row["weight_percent"]),
                due_date=parse_date(str(row["due_date"])),
                confidence=int(row["confidence"]),
                estimated_hours=remaining,
            ))
        except Exception:
            pass
    return assignments


def _get_user_grade(username: str) -> float:
    with get_db() as conn:
        row = conn.execute(
            "SELECT current_grade FROM user_settings WHERE username = ?",
            (username,)
        ).fetchone()
    return float(row["current_grade"]) if row else 85.0


def _set_user_grade(username: str, grade: float):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO user_settings (username, current_grade)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET current_grade = excluded.current_grade
        """, (username, grade))
        conn.commit()


# ----------------------------
# Health
# ----------------------------

@app.get("/health")
def health():
    return jsonify({"ok": True, "engine_ok": ENGINE_OK}), 200


# ----------------------------
# Auth
# ----------------------------

@app.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip().lower()
    password = (body.get("password") or "")

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    if len(username) < 3:
        return jsonify({"error": "username must be at least 3 characters"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT username FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return jsonify({"error": "username already taken"}), 409

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed.decode("utf-8"))
        )
        conn.commit()

    access_token = create_access_token(identity=username)
    return jsonify({"access_token": access_token}), 200


@app.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip().lower()
    password = (body.get("password") or "")

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    with get_db() as conn:
        row = conn.execute(
            "SELECT password FROM users WHERE username = ?", (username,)
        ).fetchone()

    if not row:
        return jsonify({"error": "invalid username or password"}), 401
    if not bcrypt.checkpw(password.encode("utf-8"), row["password"].encode("utf-8")):
        return jsonify({"error": "invalid username or password"}), 401

    access_token = create_access_token(identity=username)
    return jsonify({"access_token": access_token}), 200


# ----------------------------
# Dashboard
# ----------------------------

@app.get("/dashboard")
@jwt_required()
def get_dashboard():
    if not ENGINE_OK:
        return jsonify({"error": "engine not available", "detail": ENGINE_IMPORT_ERROR}), 500

    username = get_jwt_identity()
    today = date.today()
    assignments = _load_user_assignments(username)
    current_grade = _get_user_grade(username)

    if not assignments:
        return jsonify({
            "has_assignments": False,
            "top": [],
            "headlines": [],
            "stress_forecast": {
                "high_risk_count": 0,
                "message": "No assignments yet.",
                "window_days": 5,
                "high_risk_names": []
            },
            "gpa_impacts": [],
            "workload_next_3_days": [],
            "current_grade": current_grade,
        }), 200

    summary = dashboard_summary(assignments, today)
    gpa = gpa_impact_estimates(assignments, current_grade=current_grade)
    workload = hours_next_days(assignments, today, window_days=3)

    return jsonify({
        "has_assignments": True,
        "top": summary["top"],
        "headlines": summary["headlines"],
        "stress_forecast": summary["stress_forecast"],
        "gpa_impacts": gpa,
        "workload_next_3_days": workload,
        "current_grade": current_grade,
    }), 200


# ----------------------------
# Assignments API
# ----------------------------

@app.get("/assignments")
@jwt_required()
def get_assignments():
    username = get_jwt_identity()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE username = ? ORDER BY created_at DESC",
            (username,)
        ).fetchall()

    items = [dict(row) for row in rows]
    # Rename DB columns to camelCase for the frontend
    result = []
    for x in items:
        result.append({
            "id": x["id"],
            "name": x["name"],
            "weightPercent": x["weight_percent"],
            "dueDate": x["due_date"],
            "confidence": x["confidence"],
            "estHours": x["est_hours"],
            "hoursLogged": x["hours_logged"],
            "createdAt": x["created_at"],
        })
    return jsonify(result), 200


@app.post("/assignments")
@jwt_required()
def create_assignment():
    username = get_jwt_identity()
    body = request.get_json(silent=True) or {}

    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    item_id = str(uuid4())
    weight_percent = float(body.get("weightPercent", 0))
    due_date = str(body.get("dueDate", ""))
    confidence = int(body.get("confidence", 3))
    est_hours = float(body.get("estHours", 0))
    created_at = int(time.time() * 1000)

    with get_db() as conn:
        conn.execute("""
            INSERT INTO assignments
                (id, username, name, weight_percent, due_date, confidence, est_hours, hours_logged, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (item_id, username, name, weight_percent, due_date, confidence, est_hours, created_at))
        conn.commit()

    return jsonify({
        "id": item_id,
        "name": name,
        "weightPercent": weight_percent,
        "dueDate": due_date,
        "confidence": confidence,
        "estHours": est_hours,
        "hoursLogged": 0,
        "createdAt": created_at,
    }), 200


@app.delete("/assignments/<id>")
@jwt_required()
def delete_assignment(id):
    username = get_jwt_identity()
    with get_db() as conn:
        conn.execute(
            "DELETE FROM assignments WHERE id = ? AND username = ?",
            (id, username)
        )
        conn.commit()
    return "", 204


@app.post("/assignments/<id>/log-hours")
@jwt_required()
def log_hours(id):
    """Log hours worked on an assignment. Reduces remaining hours in projections."""
    username = get_jwt_identity()
    body = request.get_json(silent=True) or {}
    hours = float(body.get("hours", 0))

    if hours <= 0:
        return jsonify({"error": "hours must be > 0"}), 400

    with get_db() as conn:
        row = conn.execute(
            "SELECT est_hours, hours_logged FROM assignments WHERE id = ? AND username = ?",
            (id, username)
        ).fetchone()

        if not row:
            return jsonify({"error": "assignment not found"}), 404

        new_logged = float(row["hours_logged"]) + hours
        conn.execute(
            "UPDATE assignments SET hours_logged = ? WHERE id = ? AND username = ?",
            (new_logged, id, username)
        )
        conn.commit()

    return jsonify({"hours_logged": new_logged}), 200


# ----------------------------
# Settings (per-user grade)
# ----------------------------

@app.get("/settings")
@jwt_required()
def get_settings():
    username = get_jwt_identity()
    grade = _get_user_grade(username)
    return jsonify({"current_grade": grade}), 200


@app.post("/settings")
@jwt_required()
def update_settings():
    username = get_jwt_identity()
    body = request.get_json(silent=True) or {}

    if "current_grade" in body:
        grade = float(body["current_grade"])
        if not (0 <= grade <= 100):
            return jsonify({"error": "current_grade must be 0–100"}), 400
        _set_user_grade(username, grade)

    return jsonify({"current_grade": _get_user_grade(username)}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)