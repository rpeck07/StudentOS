from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
import os
from typing import List, Dict, Any

from flask import Flask, render_template, request, redirect, url_for

from config import Config
from engine import (
    Assignment,
    parse_date,
    calc_risk,
    calc_urgency,
    danger_score,
)

# ----------------------------
# APP SETUP
# ----------------------------

app = Flask(__name__)
app.config.from_object(Config)

# Local JSON storage (fine for v1 / portfolio; not for multi-user production)
DATA_FILE = "assignments.json"


# ----------------------------
# STORAGE HELPERS
# ----------------------------

def load_assignments(path: str = DATA_FILE) -> List[Assignment]:
    """
    Loads assignments from a JSON file into Assignment objects.
    Returns an empty list if the file doesn't exist yet.
    """
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    assignments: List[Assignment] = []
    for item in raw:
        assignments.append(
            Assignment(
                name=item["name"],
                weight_percent=float(item["weight_percent"]),
                due_date=parse_date(item["due_date"]),  # stored as "YYYY-MM-DD"
                confidence=int(item["confidence"]),
                estimated_hours=float(item["estimated_hours"]),
            )
        )
    return assignments


def save_assignments(assignments: List[Assignment], path: str = DATA_FILE) -> None:
    """
    Saves Assignment objects to JSON.
    Note: dates must be converted back to strings.
    """
    payload = []
    for a in assignments:
        d = asdict(a)
        d["due_date"] = a.due_date.isoformat()
        payload.append(d)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ----------------------------
# VIEW HELPERS (UI DATA)
# ----------------------------

def emoji_for_item(risk_label: str, zone: str) -> str:
    """
    Pick a 'vibe' emoji based on risk + urgency zone.
    """
    if zone == "Panic Zone":
        return "🚨 🔥"
    if zone == "Crunch Zone":
        return "🚧 ⏳"
    if risk_label == "High":
        return "⚠️"
    if zone == "Safe":
        return "🌿"
    return "🚶‍♂️"


def build_dashboard(assignments: List[Assignment], today: date) -> Dict[str, Any]:
    """
    Converts raw assignments into computed rows the template can display.
    """
    rows = []

    for a in assignments:
        r = calc_risk(a, today)
        u = calc_urgency(a, today, start_delay_days=0)

        row = {
            "name": a.name,
            "weight_percent": a.weight_percent,
            "due_date": a.due_date.isoformat(),
            "days_left": r["days_left"],
            "confidence": a.confidence,
            "estimated_hours": a.estimated_hours,

            "risk_score": r["risk_score"],
            "risk_label": r["risk_label"],

            "hours_per_day": u["hours_per_day"],
            "zone": u["zone"],

            "danger_score": danger_score(a, today),
        }

        row["emoji"] = emoji_for_item(row["risk_label"], row["zone"])
        rows.append(row)

    # Sort by danger_score (highest first)
    rows.sort(key=lambda x: x["danger_score"], reverse=True)

    # Dashboard headline
    if not rows:
        headline = "No assignments yet. Add one above."
    else:
        high_count = sum(1 for x in rows if x["risk_label"] == "High")
        headline = f"Today’s snapshot: {len(rows)} assignments tracked • {high_count} high-risk"

    return {
        "headline": headline,
        "rows": rows,
    }


# ----------------------------
# ROUTES
# ----------------------------

@app.get("/")
def index():
    today = date.today()
    assignments = load_assignments()
    dashboard = build_dashboard(assignments, today)

    # Helpful explanations for the form fields (template will show them)
    help_text = {
        "name": "Short title (ex: 'Calc Midterm', 'Bio Lab').",
        "weight": "How much this is worth in your final grade (0–100). Example: 20 means 20%.",
        "due": "Due date in YYYY-MM-DD (or pick from the date picker).",
        "confidence": "How confident you feel (1–5). 1 = not confident, 5 = very confident.",
        "hours": "How many total hours you think you’ll need. Example: essay = 6, exam study = 4.",
    }

    return render_template(
        "index.html",
        today=today.isoformat(),
        dashboard=dashboard,
        help_text=help_text,
    )


@app.post("/add")
def add_assignment():
    """
    Adds an assignment from the form on the homepage.
    """
    assignments = load_assignments()

    name = request.form.get("name", "").strip()
    weight_str = request.form.get("weight_percent", "0").strip()
    due_str = request.form.get("due_date", "").strip()
    conf_str = request.form.get("confidence", "3").strip()
    hours_str = request.form.get("estimated_hours", "1").strip()

    # Basic validation (keep it simple for v1)
    if not name or not due_str:
        return redirect(url_for("index"))

    try:
        weight = float(weight_str)
        conf = int(conf_str)
        hours = float(hours_str)
        due = parse_date(due_str)
    except ValueError:
        return redirect(url_for("index"))

    # Clamp ranges so the app never breaks
    weight = max(0.0, min(100.0, weight))
    conf = max(1, min(5, conf))
    hours = max(0.25, hours)

    assignments.append(
        Assignment(
            name=name,
            weight_percent=weight,
            due_date=due,
            confidence=conf,
            estimated_hours=hours,
        )
    )

    save_assignments(assignments)
    return redirect(url_for("index"))


@app.post("/delete")
def delete_assignment():
    """
    Deletes an assignment by name (simple v1 approach).
    Later: use unique IDs.
    """
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("index"))

    assignments = load_assignments()
    assignments = [a for a in assignments if a.name != name]
    save_assignments(assignments)
    return redirect(url_for("index"))


# ----------------------------
# RUN LOCAL
# ----------------------------

if __name__ == "__main__":
    # Debug mode is local-only. Render will run gunicorn instead.
    app.run(debug=True)