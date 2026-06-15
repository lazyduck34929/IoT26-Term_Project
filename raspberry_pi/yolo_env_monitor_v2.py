import csv
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import gpiod
import numpy as np
from gpiozero import Buzzer, DistanceSensor
from picamera2 import Picamera2
from smbus2 import SMBus
from ultralytics import YOLO


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_PATH = PROJECT_DIR / "best_v11_trash.pt"
if not MODEL_PATH.exists():
    MODEL_PATH = Path("/home/berry/best_v11_trash.pt")

ASSET_DIR = PROJECT_DIR / "assets"
LOG_PATH = PROJECT_DIR / "data" / "hygiene_log.csv"
DETECTION_EVENT_PATH = PROJECT_DIR / "data" / "detection_events.jsonl"
SCREENSHOT_DIR = PROJECT_DIR / "screenshots"

AWS_EVENT_API_URL = os.environ.get("RECYCLEOPS_EVENT_API_URL", "http://13.236.1.46:5000/api/events")
AWS_API_KEY = os.environ.get("RECYCLEOPS_API_KEY", "")

SHT30_ADDRESS = 0x45

# BCM GPIO numbers. Keep these aligned with your tested ultrasonic wiring.
TRIG_PIN = 17
ECHO_PIN = 27
BUZZER_PIN = 22

# HW-136 / TTP229 touch keypad, BCM GPIO numbers.
# SCL=clock, SDO=data. These are physical pins 16 and 18 on Raspberry Pi.
TTP229_SCL_PIN = 23
TTP229_SDO_PIN = 24
KEYPAD_USER_BUTTONS = set(range(1, 8))
KEYPAD_LOGOUT_BUTTON = 8
KEYPAD_ACCEPTED_BUTTONS = KEYPAD_USER_BUTTONS | {KEYPAD_LOGOUT_BUTTON}
KEYPAD_DEBOUNCE_SEC = 0.08
KEYPAD_RELEASE_GRACE_SEC = 0.25
TTP229_READY_TIMEOUT_SEC = 0.05

TRIGGER_DISTANCE_CM = 10.0
RELEASE_DISTANCE_CM = 14.0
SCAN_COOLDOWN_SEC = 3.0

CAMERA_SIZE = (640, 480)
DISPLAY_SIZE = (640, 480)
CAMERA_VIEW_WIDTH = 380
CAMERA_VIEW_PADDING = 4
CAMERA_WARMUP_SEC = 0.35
YOLO_CONF_THRESHOLD = 0.40
YOLO_IMAGE_SIZE = 640
VOTE_SAMPLE_COUNT = 5
VOTE_SAMPLE_INTERVAL_SEC = 0.12
ENV_READ_INTERVAL_SEC = 2.0
LOG_INTERVAL_SEC = 10.0

MY_CLASSES = [
    "battery",
    "can",
    "cardboard",
    "drink carton",
    "glass bottle",
    "paper",
    "plastic bag",
    "plastic bottle",
    "plastic bottle cap",
    "pop tab",
]

ASSET_BY_CLASS = {
    "can": "can.jpg",
    "plastic": "pet_bottle.jpg",
    "paper": "paper.jpg",
    "glass": "glass_bottle.jpg",
    "unknown": "unknown.jpg",
}

DISPOSAL_GUIDE = {
    "can": "CAN / METAL BIN",
    "plastic": "PLASTIC BIN",
    "paper": "PAPER BIN",
    "glass": "GLASS BIN",
    "unknown": "ASK STAFF / CHECK AGAIN",
}


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int] | None = None


class SHT30:
    def __init__(self, bus_id=1, address=0x45):
        self.bus = SMBus(bus_id)
        self.address = address

    def read(self):
        self.bus.write_i2c_block_data(self.address, 0x24, [0x00])
        time.sleep(0.02)

        data = self.bus.read_i2c_block_data(self.address, 0x00, 6)
        temp_raw = data[0] << 8 | data[1]
        hum_raw = data[3] << 8 | data[4]

        temperature = -45 + (175 * temp_raw / 65535.0)
        humidity = 100 * hum_raw / 65535.0
        return round(temperature, 2), round(humidity, 2)

    def close(self):
        self.bus.close()


class UltrasonicPresenceSensor:
    def __init__(self, trigger_pin, echo_pin):
        self.sensor = DistanceSensor(
            echo=echo_pin,
            trigger=trigger_pin,
            queue_len=1,
            max_distance=2.0,
            threshold_distance=TRIGGER_DISTANCE_CM / 100.0,
        )

    def distance_cm(self):
        try:
            return round(self.sensor.distance * 100.0, 2)
        except Exception:
            return 999.0

    def is_present(self):
        return self.distance_cm() <= TRIGGER_DISTANCE_CM

    def close(self):
        self.sensor.close()


class TTP229UserSession:
    def __init__(self, scl_pin, sdo_pin):
        self.scl_pin = scl_pin
        self.sdo_pin = sdo_pin
        self.chip_path = self._find_gpiochip()
        self.active_button = None
        self.active_user_id = None
        self.active_user_label = "Guest"
        self.pressed_button = None
        self.pressed_at = 0.0
        self.press_started_with_active_user = False
        self.last_key_change_at = 0.0
        self.last_raw_button = None
        self.last_raw_seen_at = 0.0
        self.ignore_until_release = False
        self.message = "PLEASE LOGIN (KEY 1-7)"
        self.message_until = 0.0

        self.active_value = gpiod.line.Value.ACTIVE if hasattr(gpiod.line.Value, "ACTIVE") else 1
        self.inactive_value = gpiod.line.Value.INACTIVE if hasattr(gpiod.line.Value, "INACTIVE") else 0
        self.request_context = gpiod.request_lines(
            self.chip_path,
            consumer="RecycleOps_TTP229_Keypad",
            config={
                self.scl_pin: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
                self.sdo_pin: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT),
            },
        )
        self.lines = self.request_context.__enter__()
        self.lines.set_value(self.scl_pin, self.active_value)

    def _find_gpiochip(self):
        chip_path = None
        for dev in sorted(os.listdir("/dev")):
            if dev.startswith("gpiochip"):
                chip_path = f"/dev/{dev}"

        if chip_path is None:
            raise RuntimeError("No GPIO chip found under /dev")

        return chip_path

    def _is_active(self, value):
        return value in (self.active_value, 1)

    def _read_button_raw(self):
        sdo_is_active = self._is_active(self.lines.get_value(self.sdo_pin))
        if not sdo_is_active:
            return None

        wait_until = time.monotonic() + TTP229_READY_TIMEOUT_SEC
        while self._is_active(self.lines.get_value(self.sdo_pin)):
            if time.monotonic() >= wait_until:
                return None

        time.sleep(0.00001)

        touch_value = 0
        for bit_index in range(16):
            self.lines.set_value(self.scl_pin, self.inactive_value)
            time.sleep(0.000002)

            if not self._is_active(self.lines.get_value(self.sdo_pin)):
                touch_value |= 1 << bit_index

            self.lines.set_value(self.scl_pin, self.active_value)
            time.sleep(0.000002)

        if touch_value == 0:
            return None

        for button_index in range(16):
            if (touch_value >> button_index) & 1:
                return button_index + 1

        return None

    def scan_button(self, now):
        raw_button = self._read_button_raw()
        if raw_button in KEYPAD_ACCEPTED_BUTTONS:
            self.last_raw_button = raw_button
            self.last_raw_seen_at = now
            return raw_button

        if self.last_raw_button is not None and now - self.last_raw_seen_at <= KEYPAD_RELEASE_GRACE_SEC:
            return self.last_raw_button

        self.last_raw_button = None
        return None

    def update(self, now=None):
        if now is None:
            now = time.time()

        scanned_button = self.scan_button(now)

        if self.ignore_until_release:
            if scanned_button is None:
                self.ignore_until_release = False
                self.pressed_button = None
                self.pressed_at = 0.0
                self.press_started_with_active_user = False
                self.last_key_change_at = now
            return None

        if scanned_button != self.pressed_button:
            if now - self.last_key_change_at < KEYPAD_DEBOUNCE_SEC:
                return None

            self.pressed_button = scanned_button
            self.last_key_change_at = now

            if scanned_button is None:
                self.pressed_at = 0.0
                self.press_started_with_active_user = False
                return None

            self.pressed_at = now
            self.press_started_with_active_user = self.active_button == scanned_button

            if scanned_button == KEYPAD_LOGOUT_BUTTON:
                if self.active_button is None:
                    self._set_message("Already logged out", now)
                    self.ignore_until_release = True
                    return ("logout_empty", "guest")

                user_id = self.active_user_id
                self._logout()
                return ("logout", user_id)

            if self.active_button is None:
                self._login(scanned_button)
                return ("login", self.active_user_id)

            if self.active_button == scanned_button:
                self._set_message(f"{self.active_user_label} already logged in", now)
                self.ignore_until_release = True
                return ("already_login", self.active_user_id)

            if self.active_button != scanned_button:
                self._set_message(f"{self.active_user_label} active. Press 8 to logout.", now)
                return ("ignored", self.active_user_id)

        return None

    def _login(self, button):
        self.active_button = button
        self.active_user_id = f"user_{button:02d}"
        self.active_user_label = f"User {button}"
        self._set_message(f"{self.active_user_label} logged in", time.time())

    def _logout(self):
        logged_out_user = self.active_user_label
        self._set_message(f"LOGOUT COMPLETE: {logged_out_user}", time.time())
        self.active_button = None
        self.active_user_id = None
        self.active_user_label = "Guest"
        self.pressed_button = None
        self.pressed_at = 0.0
        self.press_started_with_active_user = False
        self.last_raw_button = None
        self.last_raw_seen_at = 0.0
        self.ignore_until_release = True

    def _set_message(self, message, now):
        self.message = message
        self.message_until = now + 2.0

    def display_message(self):
        if time.time() <= self.message_until:
            return self.message
        if self.active_user_id is None:
            return "LOGIN: KEY 1-7"
        return "LOGOUT: PRESS KEY 8"

    def event_user_id(self):
        return self.active_user_id or "guest"

    def event_user_label(self):
        return self.active_user_label

    def close(self):
        if hasattr(self, "lines"):
            self.lines.set_value(self.scl_pin, self.active_value)
        if hasattr(self, "request_context"):
            self.request_context.__exit__(None, None, None)


class CameraController:
    def __init__(self):
        self.picam = Picamera2()
        camera_config = self.picam.create_preview_configuration(
            main={"size": CAMERA_SIZE, "format": "BGR888"},
            controls={"FrameRate": 30},
        )
        self.picam.configure(camera_config)
        self.running = False

    def start(self):
        if self.running:
            return
        self.picam.start()
        self.running = True
        time.sleep(CAMERA_WARMUP_SEC)

    def stop(self):
        if not self.running:
            return
        self.picam.stop()
        self.running = False

    def capture_bgr(self):
        frame = self.picam.capture_array()
        if frame is None:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def close(self):
        self.stop()
        try:
            self.picam.close()
        except Exception:
            pass


def normalize_class(raw_name):
    raw_name = raw_name.lower().strip()

    if "plastic" in raw_name:
        return "plastic"
    if raw_name in {"paper", "cardboard", "drink carton"}:
        return "paper"
    if raw_name in {"can", "pop tab"}:
        return "can"
    if raw_name == "glass bottle":
        return "glass"
    return "unknown"


def classify_hygiene_status(temp_c, humidity):
    if humidity >= 80 or temp_c >= 35:
        return "WARNING"
    if humidity >= 70 or temp_c >= 30:
        return "CAUTION"
    return "GOOD"


def ensure_log_file():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        with LOG_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "temperature_c",
                "humidity_percent",
                "hygiene_status",
                "distance_cm",
                "object_present",
                "final_class",
                "final_confidence",
                "vote_count",
            ])

    DETECTION_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DETECTION_EVENT_PATH.touch(exist_ok=True)


def append_log(temp_c, humidity, status, distance_cm, object_present, final_class, confidence, vote_count):
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            temp_c,
            humidity,
            status,
            distance_cm,
            object_present,
            final_class,
            round(confidence, 3),
            vote_count,
        ])


def append_detection_event(
    detection,
    vote_count,
    distance_cm,
    temp_c,
    humidity,
    hygiene_status,
    scan_duration_sec,
    user_id,
    user_label,
):
    timestamp = datetime.now().isoformat(timespec="seconds")
    vote_stability = round(vote_count / VOTE_SAMPLE_COUNT, 3)
    is_unknown = detection.class_name == "unknown"
    disposal_guide = DISPOSAL_GUIDE.get(detection.class_name, DISPOSAL_GUIDE["unknown"])

    DETECTION_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "device_id": "rasp-smart-bin-01",
        "user_id": user_id,
        "user_label": user_label,
        "timestamp": timestamp,
        "event_type": "detection",
        "user": {
            "user_id": user_id,
            "user_label": user_label,
            "login_method": "hw136_keypad",
        },
        "trash": {
            "class": detection.class_name,
            "confidence": round(detection.confidence, 3),
            "vote_count": vote_count,
            "vote_stability": vote_stability,
            "is_unknown": is_unknown,
            "disposal_guide": disposal_guide,
        },
        "sensors": {
            "distance_cm": distance_cm,
            "temperature_c": temp_c,
            "humidity_percent": humidity,
            "hygiene_status": hygiene_status,
        },
        "runtime": {
            "scan_duration_sec": round(scan_duration_sec, 3),
            "camera_triggered_by": "ultrasonic",
        },
    }

    with DETECTION_EVENT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event


def send_event_to_aws(event):
    if not AWS_API_KEY:
        print("AWS upload skipped: RECYCLEOPS_API_KEY is not set.")
        return False

    data = json.dumps(event, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        AWS_EVENT_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": AWS_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            print(f"AWS upload ok: {response.status}")
            return 200 <= response.status < 300
    except urllib.error.HTTPError as e:
        print(f"AWS upload failed: HTTP {e.code}")
    except Exception as e:
        print(f"AWS upload failed: {e}")

    return False


def load_assets():
    assets = {}
    for class_name, filename in ASSET_BY_CLASS.items():
        image_path = ASSET_DIR / filename
        image = cv2.imread(str(image_path))
        if image is None:
            print(f"Warning: asset not found or unreadable: {image_path}")
            continue
        assets[class_name] = image
    return assets


def resize_to_fit(image, max_width, max_height):
    h, w = image.shape[:2]
    scale = min(max_width / w, max_height / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def overlay_image(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas_h, canvas_w = canvas.shape[:2]
    if x >= canvas_w or y >= canvas_h:
        return

    x2 = min(canvas_w, x + w)
    y2 = min(canvas_h, y + h)
    crop_w = x2 - x
    crop_h = y2 - y
    if crop_w <= 0 or crop_h <= 0:
        return

    canvas[y:y2, x:x2] = image[:crop_h, :crop_w]


def compose_display_frame(camera_frame):
    display_w, display_h = DISPLAY_SIZE
    display = np.full((display_h, display_w, 3), (18, 22, 26), dtype=np.uint8)

    if camera_frame is None:
        return display

    frame_h, frame_w = camera_frame.shape[:2]
    max_w = CAMERA_VIEW_WIDTH - (CAMERA_VIEW_PADDING * 2)
    max_h = display_h - (CAMERA_VIEW_PADDING * 2)
    scale = min(max_w / frame_w, max_h / frame_h)
    new_w = max(1, int(frame_w * scale))
    new_h = max(1, int(frame_h * scale))

    resized = cv2.resize(camera_frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    x = (CAMERA_VIEW_WIDTH - new_w) // 2
    y = (display_h - new_h) // 2

    display[y:y + new_h, x:x + new_w] = resized
    cv2.rectangle(display, (x - 1, y - 1), (x + new_w, y + new_h), (70, 80, 86), 1)
    cv2.line(display, (CAMERA_VIEW_WIDTH, 0), (CAMERA_VIEW_WIDTH, display_h), (48, 54, 60), 1)
    return display


def detect_best_object(model, frame):
    results = model(frame, stream=True, conf=YOLO_CONF_THRESHOLD, imgsz=YOLO_IMAGE_SIZE, verbose=False)
    best = Detection("unknown", 0.0, None)

    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])

            raw_name = MY_CLASSES[cls_id] if cls_id < len(MY_CLASSES) else "unknown"
            class_name = normalize_class(raw_name)

            box_area = (x2 - x1) * (y2 - y1)
            if class_name == "paper" and box_area > (CAMERA_SIZE[0] * CAMERA_SIZE[1] * 0.70):
                continue

            if conf > best.confidence:
                best = Detection(class_name, conf, (x1, y1, x2, y2))

    return best


def decide_by_votes(detections):
    valid = [d for d in detections if d.class_name != "unknown" and d.confidence > 0]
    if not valid:
        return Detection("unknown", 0.0, None), 0

    class_counts = Counter(d.class_name for d in valid)
    confidence_sums = defaultdict(float)
    best_by_class = {}

    for detection in valid:
        confidence_sums[detection.class_name] += detection.confidence
        previous = best_by_class.get(detection.class_name)
        if previous is None or detection.confidence > previous.confidence:
            best_by_class[detection.class_name] = detection

    winning_class = max(
        class_counts,
        key=lambda name: (class_counts[name], confidence_sums[name] / class_counts[name]),
    )
    return best_by_class[winning_class], class_counts[winning_class]


def draw_detection_box(frame, detection):
    if detection.bbox is None:
        return

    x1, y1, x2, y2 = detection.bbox
    label = f"{detection.class_name} {detection.confidence * 100:.1f}%"

    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.rectangle(frame, (x1, max(0, y1 - 26)), (min(639, x1 + 180), y1), (0, 255, 0), -1)
    cv2.putText(
        frame,
        label,
        (x1 + 5, max(18, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        2,
    )


def draw_environment_panel(frame, temp_c, humidity, status):
    if status == "GOOD":
        color = (0, 200, 0)
    elif status == "CAUTION":
        color = (0, 200, 255)
    else:
        color = (0, 0, 255)

    cv2.rectangle(frame, (10, 10), (275, 86), (30, 30, 30), -1)
    cv2.rectangle(frame, (10, 10), (275, 86), color, 2)
    cv2.putText(frame, "Environment", (22, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
    cv2.putText(frame, f"T {temp_c:.1f}C", (22, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
    cv2.putText(frame, f"H {humidity:.1f}%", (112, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
    cv2.putText(frame, status, (205, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.46, color, 1)


def draw_proximity_panel(frame, distance_cm, object_present, scanning):
    panel_x1, panel_y1 = 10, 94
    panel_x2, panel_y2 = 275, 152
    color = (0, 180, 255) if object_present else (180, 180, 180)
    mode_text = "SCANNING" if scanning else ("OBJECT DETECTED" if object_present else "IDLE")

    cv2.rectangle(frame, (panel_x1, panel_y1), (panel_x2, panel_y2), (30, 30, 30), -1)
    cv2.rectangle(frame, (panel_x1, panel_y1), (panel_x2, panel_y2), color, 2)
    cv2.putText(frame, "Proximity", (22, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)
    cv2.putText(frame, f"{distance_cm:.1f} cm", (22, 142), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)
    cv2.putText(frame, mode_text[:14], (128, 142), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)


def draw_user_panel(frame, user_session):
    panel_x1, panel_y1 = 10, 160
    panel_x2, panel_y2 = 275, 222
    logged_in = user_session.active_user_id is not None
    color = (70, 220, 120) if logged_in else (180, 180, 180)
    user_text = user_session.event_user_label()
    message = user_session.display_message()

    cv2.rectangle(frame, (panel_x1, panel_y1), (panel_x2, panel_y2), (30, 30, 30), -1)
    cv2.rectangle(frame, (panel_x1, panel_y1), (panel_x2, panel_y2), color, 2)
    cv2.putText(frame, "User", (22, 184), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)
    cv2.putText(frame, user_text, (82, 184), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 1)
    cv2.putText(frame, message[:34], (22, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (220, 220, 220), 1)


def draw_guidance_panel(
    frame,
    assets,
    detection,
    vote_count,
    object_present,
    login_required=False,
    temp_c=0.0,
    humidity=0.0,
    hygiene_status="READY",
    distance_cm=999.0,
    user_session=None,
):
    panel_x1, panel_y1 = 380, 10
    panel_x2, panel_y2 = 630, 470

    cv2.rectangle(frame, (panel_x1, panel_y1), (panel_x2, panel_y2), (245, 245, 245), -1)
    cv2.rectangle(frame, (panel_x1, panel_y1), (panel_x2, panel_y2), (30, 30, 30), 2)

    if login_required:
        title = "LOGIN FIRST"
        guide = "PRESS USER KEY 1-7"
    elif object_present:
        title = detection.class_name.upper()
        guide = DISPOSAL_GUIDE.get(detection.class_name, DISPOSAL_GUIDE["unknown"])
    else:
        title = "WAITING"
        guide = "PLACE WASTE NEAR SENSOR"

    cv2.putText(frame, "SORTING GUIDE", (398, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (30, 30, 30), 2)
    cv2.putText(frame, title, (398, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.76, (0, 110, 255), 2)
    cv2.putText(frame, f"Conf: {detection.confidence * 100:.1f}%", (398, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 2)

    asset_key = detection.class_name if object_present and not login_required else "unknown"
    asset = assets.get(asset_key)
    if asset is None:
        asset = assets.get("unknown")
    if asset is not None:
        resized = resize_to_fit(asset, 220, 175)
        image_x = panel_x1 + (panel_x2 - panel_x1 - resized.shape[1]) // 2
        overlay_image(frame, resized, image_x, 130)

    info_y = 325
    user_text = user_session.event_user_label() if user_session is not None else "Guest"
    session_text = user_session.display_message() if user_session is not None else guide

    cv2.line(frame, (398, info_y - 16), (612, info_y - 16), (215, 215, 215), 1)
    cv2.putText(frame, "User", (398, info_y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (35, 35, 35), 2)
    cv2.putText(frame, f": {user_text}", (452, info_y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (35, 35, 35), 2)
    cv2.putText(frame, f"Dist  : {distance_cm:.1f} cm", (398, info_y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (35, 35, 35), 1)
    cv2.putText(frame, f"Env   : {temp_c:.1f}C / {humidity:.1f}%", (398, info_y + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (35, 35, 35), 1)
    cv2.putText(frame, f"Status: {hygiene_status}", (398, info_y + 75), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 120, 80), 1)

    cv2.putText(frame, session_text[:31], (398, 430), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (0, 90, 180), 1)
    cv2.putText(frame, guide[:31], (398, 452), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (0, 90, 180), 1)


def draw_countdown(frame, current_sample, total_samples):
    cv2.rectangle(frame, (10, 430), (275, 470), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"Scanning... {current_sample}/{total_samples}",
        (25, 456),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (255, 255, 255),
        1,
    )


def save_display_screenshot(frame):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = SCREENSHOT_DIR / f"recycleops_screen_{timestamp}.png"
    cv2.imwrite(str(output_path), frame)
    print(f"Saved display screenshot: {output_path}")
    return output_path


def make_standby_frame(login_required=False):
    frame = np.full((CAMERA_SIZE[1], CAMERA_SIZE[0], 3), (18, 24, 28), dtype=np.uint8)
    title = "PLEASE LOGIN" if login_required else "CAMERA STANDBY"
    subtitle = "KEY 1-7 TO LOGIN" if login_required else "MOVE WASTE WITHIN 10 CM"

    cv2.putText(
        frame,
        title,
        (58, 245) if login_required else (52, 245),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95 if login_required else 0.88,
        (210, 225, 235),
        2,
    )
    cv2.putText(
        frame,
        subtitle,
        (70, 292) if login_required else (35, 292),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (170, 185, 195),
        1,
    )
    return frame


def capture_vote_result(
    model,
    camera,
    window_name,
    assets,
    temp_c,
    humidity,
    status,
    distance_cm,
    buzzer,
    user_session,
):
    detections = []
    preview_frame = None

    for sample_index in range(1, VOTE_SAMPLE_COUNT + 1):
        frame = camera.capture_bgr()
        if frame is None:
            continue

        detection = detect_best_object(model, frame)
        detections.append(detection)

        draw_detection_box(frame, detection)
        display_frame = compose_display_frame(frame)
        draw_guidance_panel(
            display_frame,
            assets,
            detection,
            1 if detection.class_name != "unknown" else 0,
            True,
            temp_c=temp_c,
            humidity=humidity,
            hygiene_status=status,
            distance_cm=distance_cm,
            user_session=user_session,
        )
        draw_countdown(display_frame, sample_index, VOTE_SAMPLE_COUNT)
        cv2.imshow(window_name, display_frame)
        cv2.waitKey(1)

        preview_frame = frame
        time.sleep(VOTE_SAMPLE_INTERVAL_SEC)

    final_detection, vote_count = decide_by_votes(detections)

    if final_detection.class_name != "unknown" and vote_count > 0:
        buzzer.on()
        time.sleep(0.15)
        buzzer.off()
        time.sleep(0.06)
        buzzer.on()
        time.sleep(0.15)
        buzzer.off()

    return final_detection, vote_count, preview_frame


def main():
    ensure_log_file()

    print("Loading YOLO model...")
    model = YOLO(str(MODEL_PATH))

    print("Loading guide images...")
    assets = load_assets()

    print("Initializing SHT30...")
    env_sensor = SHT30(address=SHT30_ADDRESS)

    print("Initializing ultrasonic sensor...")
    proximity_sensor = UltrasonicPresenceSensor(trigger_pin=TRIG_PIN, echo_pin=ECHO_PIN)

    print("Initializing buzzer...")
    buzzer = Buzzer(BUZZER_PIN)

    print("Initializing HW-136/TTP229 keypad...")
    user_session = TTP229UserSession(TTP229_SCL_PIN, TTP229_SDO_PIN)
    print(f"Keypad GPIO chip: {user_session.chip_path}")

    print("Initializing Raspberry Pi Camera configuration...")
    camera = CameraController()

    window_name = "AIoT Smart Recycling Monitor"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    latest_temp = 0.0
    latest_humidity = 0.0
    latest_status = "READY"
    latest_distance_cm = 999.0
    last_env_read_time = 0.0
    last_log_time = 0.0
    last_scan_time = 0.0
    stable_detection = Detection("unknown", 0.0, None)
    stable_vote_count = 0
    object_locked = False

    print("System ready. Camera stays off until distance is close enough.")

    try:
        while True:
            now = time.time()

            keypad_event = user_session.update(now)
            if keypad_event is not None:
                action, user_id = keypad_event
                if action == "login":
                    print(f"Keypad login: {user_session.event_user_label()} ({user_id})")
                elif action == "logout":
                    print(f"Keypad logout: {user_id}")
                    object_locked = False
                    stable_detection = Detection("unknown", 0.0, None)
                    stable_vote_count = 0
                    camera.stop()
                elif action == "logout_empty":
                    print("Keypad logout: already logged out")

            if now - last_env_read_time >= ENV_READ_INTERVAL_SEC:
                latest_temp, latest_humidity = env_sensor.read()
                latest_status = classify_hygiene_status(latest_temp, latest_humidity)
                last_env_read_time = now

            latest_distance_cm = proximity_sensor.distance_cm()
            object_present = latest_distance_cm <= TRIGGER_DISTANCE_CM
            login_ready = user_session.active_user_id is not None

            if object_locked and latest_distance_cm >= RELEASE_DISTANCE_CM:
                object_locked = False
                stable_detection = Detection("unknown", 0.0, None)
                stable_vote_count = 0
                camera.stop()
                print(f"Object released at {latest_distance_cm:.1f} cm. Camera stopped.")

            if login_ready and object_present and not object_locked and now - last_scan_time >= SCAN_COOLDOWN_SEC:
                print(f"Object detected at {latest_distance_cm:.1f} cm. Running YOLO vote scan.")
                scan_started_at = time.time()
                camera.start()
                stable_detection, stable_vote_count, frame = capture_vote_result(
                    model,
                    camera,
                    window_name,
                    assets,
                    latest_temp,
                    latest_humidity,
                    latest_status,
                    latest_distance_cm,
                    buzzer,
                    user_session,
                )
                event = append_detection_event(
                    stable_detection,
                    stable_vote_count,
                    latest_distance_cm,
                    latest_temp,
                    latest_humidity,
                    latest_status,
                    time.time() - scan_started_at,
                    user_session.event_user_id(),
                    user_session.event_user_label(),
                )
                send_event_to_aws(event)
                last_scan_time = time.time()
                object_locked = True
            else:
                if camera.running:
                    frame = camera.capture_bgr()
                    if frame is None:
                        continue
                else:
                    frame = make_standby_frame(login_required=not login_ready)

            display_detection = stable_detection if object_locked and login_ready else Detection("unknown", 0.0, None)
            display_vote_count = stable_vote_count if object_locked and login_ready else 0
            display_object_present = (object_present or object_locked) and login_ready

            draw_detection_box(frame, display_detection)
            display_frame = compose_display_frame(frame)
            draw_guidance_panel(
                display_frame,
                assets,
                display_detection,
                display_vote_count,
                display_object_present,
                login_required=not login_ready,
                temp_c=latest_temp,
                humidity=latest_humidity,
                hygiene_status=latest_status,
                distance_cm=latest_distance_cm,
                user_session=user_session,
            )
            cv2.imshow(window_name, display_frame)

            now = time.time()
            if now - last_log_time >= LOG_INTERVAL_SEC:
                append_log(
                    latest_temp,
                    latest_humidity,
                    latest_status,
                    latest_distance_cm,
                    object_present or object_locked,
                    display_detection.class_name,
                    display_detection.confidence,
                    display_vote_count,
                )
                last_log_time = now

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                save_display_screenshot(display_frame)

            time.sleep(0.03)

    except KeyboardInterrupt:
        print("\nStopping AIoT monitor...")

    finally:
        camera.close()
        proximity_sensor.close()
        env_sensor.close()
        user_session.close()
        buzzer.off()
        buzzer.close()
        cv2.destroyAllWindows()
        print("Program terminated.")


if __name__ == "__main__":
    main()
