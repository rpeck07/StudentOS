"""
Academic Decision Engine (Python Core)

This file contains ONLY the “brain” of the app.
It does math + logic. No menus, no UI, no printing inside the core functions.

Later:
• A CLI, website, or iOS app will CALL these functions
• That way, the logic can be reused anywhere
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional
import json


# ----------------------------
# DATA MODELS
# ----------------------------

@dataclass
class Assignment:
    name: str
    weight_percent: float      # 0–100
    due_date: date             # python date object
    confidence: int            # 1–5
    estimated_hours: float     # 0+


@dataclass
class DailyLog:
    sleep_hours: float
    class_hours: float
    study_hours: float
    workout_minutes: float
    social_hours: float
    stress_level: Optional[int] = None


# ----------------------------
# HELPERS
# ----------------------------

def parse_date(iso_yyyy_mm_dd: str) -> date:
    return datetime.strptime(iso_yyyy_mm_dd, "%Y-%m-%d").date()


def days_until(due: date, today: date) -> int:
    return (due - today).days


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ----------------------------
# 1) SYLLABUS DECODER (RISK)
# ----------------------------

def calc_risk(a: Assignment, today: date) -> Dict[str, object]:
    dleft = days_until(a.due_date, today)

    # urgency bucket
    if dleft <= 1:
        soon = 10
    elif dleft <= 3:
        soon = 8
    elif dleft <= 7:
        soon = 6
    elif dleft <= 14:
        soon = 4
    else:
        soon = 2

    doubt = 6 - clamp(a.confidence, 1, 5)
    weight_scaled = clamp(a.weight_percent, 0, 100) / 10.0

    risk = (0.4 * soon) + (0.4 * weight_scaled) + (0.2 * doubt)

    if risk < 3.5:
        label = "Low"
    elif risk < 5.5:
        label = "Medium"
    else:
        label = "High"

    return {
        "name": a.name,
        "days_left": dleft,
        "risk_score": round(risk, 2),
        "risk_label": label
    }


def rank_assignments(assignments: List[Assignment], today: date) -> List[Dict[str, object]]:
    scored = [calc_risk(a, today) for a in assignments]
    scored.sort(key=lambda x: x["risk_score"], reverse=True)
    return scored


# ----------------------------
# 2) DEADLINE RUSH (URGENCY)
# ----------------------------

def urgency_zone(hours_per_day: float) -> str:
    if hours_per_day <= 1:
        return "Safe"
    if hours_per_day <= 2.5:
        return "Steady"
    if hours_per_day <= 4:
        return "Crunch Zone"
    return "Panic Zone"


def calc_urgency(a: Assignment, today: date, start_delay_days: int = 0) -> Dict[str, object]:
    dleft_after_delay = days_until(a.due_date, today) - start_delay_days

    # overdue is special
    if dleft_after_delay < 0:
        return {
            "name": a.name,
            "start_delay_days": start_delay_days,
            "days_left_after_delay": dleft_after_delay,
            "hours_per_day": None,
            "zone": "Overdue"
        }

    effective_days = max(1, dleft_after_delay)
    hours_day = a.estimated_hours / effective_days

    return {
        "name": a.name,
        "start_delay_days": start_delay_days,
        "days_left_after_delay": dleft_after_delay,
        "hours_per_day": round(hours_day, 2),
        "zone": urgency_zone(hours_day)
    }


def urgency_curve(a: Assignment, today: date, max_delay_days: int = 3) -> List[Dict[str, object]]:
    return [calc_urgency(a, today, delay) for delay in range(0, max_delay_days + 1)]


# ----------------------------
# 3) COMBINED "DANGER" SCORE
# ----------------------------

def danger_score(a: Assignment, today: date) -> float:
    r = calc_risk(a, today)
    risk = float(r["risk_score"])

    u = calc_urgency(a, today, start_delay_days=0)
    hours_per_day = u["hours_per_day"]

    if hours_per_day is None:
        urgency_scaled = 10.0
    else:
        urgency_scaled = min(5.0, float(hours_per_day)) * 2.0  # cap 5 -> 10

    raw = (0.7 * risk) + (0.3 * urgency_scaled)
    return round(raw, 2)


def rank_assignments_by_danger(assignments: List[Assignment], today: date) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    for a in assignments:
        r = calc_risk(a, today)
        u = calc_urgency(a, today, 0)
        results.append({
            "name": a.name,
            "risk_score": r["risk_score"],
            "risk_label": r["risk_label"],
            "hours_per_day": u["hours_per_day"],
            "zone": u["zone"],
            "danger_score": danger_score(a, today)
        })

    results.sort(key=lambda x: x["danger_score"], reverse=True)
    return results


# ----------------------------
# 4) STRESS FORECAST
# ----------------------------

def stress_forecast(assignments: List[Assignment], today: date, window_days: int = 5) -> Dict[str, object]:
    high_risk = []
    for a in assignments:
        r = calc_risk(a, today)
        if 0 <= r["days_left"] <= window_days and r["risk_label"] == "High":
            high_risk.append(a.name)

    count = len(high_risk)
    word = "assignment" if count == 1 else "assignments"

    return {
        "window_days": window_days,
        "high_risk_count": count,
        "high_risk_names": high_risk,
        "message": f"You have {count} high-risk {word} in the next {window_days} days."
    }


def stress_forecast_by_danger(assignments: List[Assignment], today: date, window_days: int = 5) -> Dict[str, object]:
    danger_list = []
    for a in assignments:
        r = calc_risk(a, today)
        dleft = r["days_left"]
        if 0 <= dleft <= window_days:
            u = calc_urgency(a, today, 0)
            if u["zone"] in ("Crunch Zone", "Panic Zone"):
                danger_list.append(a.name)

    return {
        "window_days": window_days,
        "crunch_or_panic_count": len(danger_list),
        "names": danger_list,
        "message": f"You have {len(danger_list)} Crunch/Panic assignments in the next {window_days} days."
    }


# ----------------------------
# 5) START-BY DATE
# ----------------------------

def start_by_date(a: Assignment, today: date, crunch_threshold: float = 2.5) -> Dict[str, object]:
    total_days_left = days_until(a.due_date, today)

    if total_days_left <= 0:
        return {
            "name": a.name,
            "start_by_days": 0,
            "start_by_date": today.isoformat(),
            "message": "Start immediately — already at deadline."
        }

    for delay in range(total_days_left + 1):
        dleft_after_delay = total_days_left - delay
        effective_days = max(1, dleft_after_delay)
        hours_per_day = a.estimated_hours / effective_days

        if hours_per_day > crunch_threshold:
            safe_delay = max(0, delay - 1)
            start_date = today + timedelta(days=safe_delay)
            zone_if_wait = urgency_zone(hours_per_day)

            return {
                "name": a.name,
                "start_by_days": safe_delay,
                "start_by_date": start_date.isoformat(),
                "message": f"Start by {start_date.isoformat()} to avoid {zone_if_wait}."
            }

    return {
        "name": a.name,
        "start_by_days": total_days_left,
        "start_by_date": a.due_date.isoformat(),
        "message": "You can pace this — no Crunch Zone risk."
    }


# ----------------------------
# 6) WORKLOAD PROJECTION
# ----------------------------

def workload_projection(assignments: List[Assignment], today: date, days: int = 7) -> List[Dict[str, object]]:
    projection: List[Dict[str, object]] = []

    for i in range(days):
        day = today + timedelta(days=i)
        total = 0.0
        breakdown: List[Dict[str, object]] = []

        for a in assignments:
            dleft = days_until(a.due_date, day)
            if dleft < 0:
                continue

            effective_days = max(1, dleft)
            daily_hours = a.estimated_hours / effective_days

            total += daily_hours
            breakdown.append({
                "name": a.name,
                "daily_hours": round(daily_hours, 2),
                "due_date": a.due_date.isoformat()
            })

        projection.append({
            "date": day.isoformat(),
            "total_hours": round(total, 2),
            "breakdown": breakdown
        })

    return projection


def hours_next_days(assignments: List[Assignment], today: date, window_days: int = 3) -> List[Dict[str, object]]:
    """
    IMPORTANT: This returns a LIST (so your app.py can do sum(x.get("hours")...)).
    """
    proj = workload_projection(assignments, today, days=window_days)
    return [{"date": d["date"], "hours": float(d["total_hours"])} for d in proj]


def workload_text_bars(assignments: List[Assignment], today: date, window_days: int = 7, blocks_per_hour: int = 2) -> List[str]:
    proj = workload_projection(assignments, today, days=window_days)
    lines: List[str] = []
    for day in proj:
        h = float(day["total_hours"])
        blocks = int(round(h * blocks_per_hour))
        bar = "█" * blocks if blocks > 0 else ""
        lines.append(f"{day['date']} | {h}h | {bar}")
    return lines


# ----------------------------
# 7) GPA IMPACT (FIXED EXPORT)
# ----------------------------

def expected_score_from_confidence(confidence: int) -> float:
    mapping = {
        1: 65.0,
        2: 75.0,
        3: 83.0,
        4: 90.0,
        5: 96.0
    }
    return float(mapping.get(int(confidence), 83.0))


def projected_grade_after_assignment(current_grade: float, weight_percent: float, assignment_score: float) -> float:
    w = clamp(weight_percent / 100.0, 0.0, 1.0)
    current_grade = clamp(current_grade, 0.0, 100.0)
    assignment_score = clamp(assignment_score, 0.0, 100.0)
    return round(current_grade * (1 - w) + assignment_score * w, 2)


def gpa_impact_estimate(a: Assignment, current_grade: float, predicted_score: float = None) -> Dict[str, object]:
    if predicted_score is None:
        predicted_score = expected_score_from_confidence(a.confidence)

    new_grade = projected_grade_after_assignment(current_grade, a.weight_percent, predicted_score)
    delta = round(new_grade - current_grade, 2)

    weight_flag = a.weight_percent >= 20
    confidence_flag = a.confidence <= 2
    drop_risk = bool(weight_flag and confidence_flag)

    mag = abs(delta)
    if mag < 0.5:
        severity = "Tiny"
    elif mag < 1.5:
        severity = "Noticeable"
    else:
        severity = "Big"

    return {
        "name": a.name,
        "current_grade": round(current_grade, 2),
        "weight_percent": a.weight_percent,
        "predicted_score": round(predicted_score, 2),
        "projected_grade": new_grade,
        "delta_points": delta,
        "severity": severity,
        "drop_risk": drop_risk,
        "message": (
            f"Potential grade change: {delta} points."
            + (" ⚠️ High weight + low confidence." if drop_risk else "")
        )
    }


def gpa_impact_estimates(assignments: List[Assignment], current_grade: float) -> List[Dict[str, object]]:
    """
    ✅ This is the function your app.py is trying to import.
    Returns a list of per-assignment GPA/grade impact estimates.
    """
    impacts = [gpa_impact_estimate(a, current_grade) for a in assignments]
    # sort: most negative delta first (biggest possible drop)
    impacts.sort(key=lambda x: x["delta_points"])
    return impacts


# ----------------------------
# 8) DASHBOARD SUMMARY (FIXED)
# ----------------------------

def dashboard_summary(assignments: List[Assignment], today: date) -> Dict[str, object]:
    ranked = rank_assignments_by_danger(assignments, today)
    forecast = stress_forecast(assignments, today, window_days=5)

    by_name = {a.name: a for a in assignments}

    zone_emoji = {
        "Safe": "🌿",
        "Steady": "🚶‍♂️",
        "Crunch Zone": "⏳",
        "Panic Zone": "🚨",
        "Overdue": "🧨"
    }
    risk_emoji = {
        "Low": "✅",
        "Medium": "⚠️",
        "High": "🔥"
    }

    headlines: List[str] = []
    top: List[Dict[str, object]] = []

    for item in ranked[:3]:
        name = item["name"]
        a = by_name.get(name)
        if not a:
            continue

        sb = start_by_date(a, today)

        hp = item["hours_per_day"]
        hp_text = "N/A" if hp is None else f"{hp} hrs/day"

        z_em = zone_emoji.get(item["zone"], "")
        r_em = risk_emoji.get(item["risk_label"], "")

        headline = (
            f"{z_em} {r_em} {name} | "
            f"Danger {item['danger_score']} | "
            f"{item['risk_label']} ({item['risk_score']}) | "
            f"{item['zone']} ({hp_text}) | "
            f"Start-by: {sb['start_by_date']}"
        )
        headlines.append(headline)

        top.append({
            **item,
            "start_by": sb
        })

    return {
        "stress_forecast": forecast,
        "top": top,
        "headlines": headlines
    }


# ----------------------------
# 9) FILE IO (LOAD/SAVE)
# ----------------------------

def assignment_to_dict(a: Assignment) -> Dict[str, object]:
    return {
        "name": a.name,
        "weight_percent": a.weight_percent,
        "due_date": a.due_date.isoformat(),
        "confidence": a.confidence,
        "estimated_hours": a.estimated_hours
    }


def assignment_from_dict(d: Dict[str, object]) -> Assignment:
    return Assignment(
        name=str(d["name"]),
        weight_percent=float(d["weight_percent"]),
        due_date=parse_date(str(d["due_date"])),
        confidence=int(d["confidence"]),
        estimated_hours=float(d["estimated_hours"])
    )


def save_assignments(path: str, assignments: List[Assignment]) -> None:
    data = [assignment_to_dict(a) for a in assignments]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_assignments(path: str) -> List[Assignment]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return [assignment_from_dict(item) for item in data]
    except FileNotFoundError:
        return []