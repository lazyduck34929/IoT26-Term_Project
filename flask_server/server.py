import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EVENTS_FILE = DATA_DIR / "detection_events.jsonl"

API_KEY = os.environ.get("RECYCLEOPS_API_KEY", "change-this-demo-key")
MAX_CONTENT_LENGTH = 64 * 1024


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
DATA_DIR.mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_pi_event(payload):
    trash = payload.get("trash", {}) or {}
    sensors = payload.get("sensors", {}) or {}
    runtime = payload.get("runtime", {}) or {}
    user = payload.get("user", {}) or {}

    event_id = payload.get("event_id") or str(uuid.uuid4())
    user_id = payload.get("user_id") or user.get("user_id") or "guest"
    user_label = payload.get("user_label") or user.get("user_label") or "Guest"
    trash_type = trash.get("class") or payload.get("trash_type") or "unknown"

    return {
        "event_id": str(event_id),
        "timestamp": payload.get("timestamp") or now_iso(),
        "device_id": payload.get("device_id") or "unknown-device",
        "user_id": str(user_id),
        "user_label": str(user_label),
        "event_type": payload.get("event_type") or "detection",
        "trash_type": str(trash_type).lower(),
        "confidence": safe_float(trash.get("confidence", payload.get("confidence"))),
        "vote_count": safe_int(trash.get("vote_count", payload.get("vote_count"))),
        "vote_stability": safe_float(trash.get("vote_stability", payload.get("vote_stability"))),
        "is_unknown": bool(trash.get("is_unknown", trash_type == "unknown")),
        "disposal_guide": trash.get("disposal_guide") or "-",
        "distance_cm": safe_float(sensors.get("distance_cm", payload.get("distance_cm"))),
        "temperature": safe_float(sensors.get("temperature_c", payload.get("temperature"))),
        "humidity": safe_float(sensors.get("humidity_percent", payload.get("humidity"))),
        "status": sensors.get("hygiene_status") or payload.get("status") or "UNKNOWN",
        "scan_duration_sec": safe_float(runtime.get("scan_duration_sec")),
        "camera_triggered_by": runtime.get("camera_triggered_by") or "ultrasonic",
        "received_at": now_iso(),
    }


def read_events():
    events = []
    if not EVENTS_FILE.exists():
        return events

    with EVENTS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def append_event(event):
    known_ids = {item.get("event_id") for item in read_events()}
    if event["event_id"] in known_ids:
        return False

    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return True


def require_api_key():
    return request.headers.get("X-API-Key") == API_KEY


@app.after_request
def add_no_cache_headers(response):
    if request.path.startswith("/static/") or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
def dashboard():
    return render_template("dashboard.html")


@app.get("/admin")
def admin_dashboard():
    return render_template("dashboard.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "recycleops-flask", "time": now_iso()})


@app.post("/api/events")
def receive_event():
    if not require_api_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    event = normalize_pi_event(payload)
    if event["event_type"] != "detection":
        return jsonify({"ok": False, "error": "unsupported_event_type"}), 400

    saved = append_event(event)
    return jsonify({"ok": True, "saved": saved, "event": event}), 201 if saved else 200


@app.get("/api/events")
def get_events():
    user_id = request.args.get("user_id")
    include_unknown = request.args.get("include_unknown") == "1"

    events = read_events()
    if user_id:
        events = [event for event in events if event.get("user_id") == user_id]
    if not include_unknown:
        events = [event for event in events if event.get("trash_type") != "unknown"]

    events.sort(key=lambda item: item.get("timestamp", ""))
    return jsonify(events)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
