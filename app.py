import os
from datetime import date

from flask import Flask, render_template, request, redirect, url_for, jsonify

from engine import (
    Assignment,
    parse_date,
    calc_risk,
    calc_urgency,
    danger_score,
    rank_assignments_by_danger,
)

# ----------------------------
# APP SETUP
# ----------------------------
app = Flask(__name__)

# Where your data file lives (Render writes to /tmp safely)
DATA_FILE = os.environ.get("STUDENTOS_DATA_FILE", "/tmp/assignments.json")

# ----------------------------
# DATA HELPERS
# ----------------------------
def load_assignments(path: str) -> list[Assignment]:
    """Load Assignment objects from JSON file. If file missing, return empty list."""
    if not os.path.exists(path):
        return []
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        assignments = []
        for item in raw:
            assignments.append(
                Assignment(
                    name=item["name"],
                    weight_percent=float(item["weight_percent"]),
                    due_date=parse_date(item["due_date"]),
                    confidence=int(item["confidence"]),
                    estimated_hours=float(item["estimated_hours"]),
                )
            )
        return assignments
    except Exception:
        # if JSON is corrupted, don't crash the whole site
        return []


def save_assignments(assignments: list[Assignment], path: str) -> None:
    """Save Assignment objects to JSON file."""
    import json
    data = []
    for a in assignments:
        data.append(
            {
                "name": a.name,
                "weight_percent": a.weight_percent,
                "due_date": a.due_date.isoformat(),
                "confidence": a.confidence,
                "estimated_hours": a.estimated_hours,
            }
        )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ----------------------------
# ROUTES (MAKE RENDER REACHABLE)
# ----------------------------
@app.get("/ping")
def ping():
    return {"ok": True, "date": date.today().isoformat()}


@app.get("/")
def index():
    today = date.today()
    assignments = load_assignments(DATA_FILE)

    # Sorted by danger for display
    ranked = rank_assignments_by_danger(assignments, today) if assignments else []

    return render_template(
        "index.html",
        today=today.isoformat(),
        assignments=ranked,
        data_file=DATA_FILE,
    )


@app.post("/add")
def add_assignment():
    assignments = load_assignments(DATA_FILE)

    # Read form fields safely
    name = request.form.get("name", "").strip()
    weight_percent = request.form.get("weight_percent", "").strip()
    due_date_str = request.form.get("due_date", "").strip()
    confidence = request.form.get("confidence", "").strip()
    estimated_hours = request.form.get("estimated_hours", "").strip()

    # Basic validation (don’t crash)
    if not name:
        return redirect(url_for("index"))

    try:
        a = Assignment(
            name=name,
            weight_percent=float(weight_percent),
            due_date=parse_date(due_date_str),
            confidence=int(confidence),
            estimated_hours=float(estimated_hours),
        )
        assignments.append(a)
        save_assignments(assignments, DATA_FILE)
    except Exception:
        # If bad input, just return home (no crash)
        return redirect(url_for("index"))

    return redirect(url_for("index"))


@app.post("/delete")
def delete_assignment():
    assignments = load_assignments(DATA_FILE)
    name = request.form.get("name", "").strip()

    if name:
        assignments = [a for a in assignments if a.name != name]
        save_assignments(assignments, DATA_FILE)

    return redirect(url_for("index"))


# ----------------------------
# LOCAL RUN (Render uses gunicorn)
# ----------------------------
if __name__ == "__main__":
    # Local dev only
    app.run(host="127.0.0.1", port=5000, debug=True)