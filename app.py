from flask import Flask, render_template
import os
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

DATA_FILE = os.path.join(os.path.dirname(__file__), "assignments.json")

app = Flask(__name__)


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine_ok": ENGINE_OK,
        "data_file_exists": os.path.exists(DATA_FILE),
    }, 200


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

    # Analytics (next 3 days)
    try:
        bars = workload_text_bars(assignments, today, window_days=3) if assignments else []
        next3 = hours_next_days(assignments, today, 3) if assignments else []
        total_next_3 = round(sum(x.get("hours", 0) for x in next3), 2)
    except Exception:
        bars = []
        total_next_3 = 0

    # GPA impact (optional)
    impacts = []
    # If you want to use it later:
    # impacts = gpa_impact_estimates(assignments, current_grade=90.0)

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)