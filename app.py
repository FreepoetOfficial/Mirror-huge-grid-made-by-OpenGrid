from __future__ import annotations

import argparse
import base64
import json
import logging
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request

from shadow.camera import create_camera
from shadow.config import load_config
from shadow.output import create_output
from shadow.processor import SilhouetteProcessor


ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class FrameHub:
    def __init__(self):
        self.condition = threading.Condition()
        self.version = 0
        self.latest = {"levels": "", "state": "starting", "fps": 0.0}

    def publish(self, payload: dict) -> None:
        with self.condition:
            self.version += 1
            self.latest = payload
            self.condition.notify_all()

    def wait(self, after: int, timeout: float = 2.0) -> tuple[int, dict]:
        with self.condition:
            if self.version <= after:
                self.condition.wait(timeout)
            return self.version, dict(self.latest)


hub = FrameHub()
processor: SilhouetteProcessor | None = None
runtime_config: dict = {}


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/state")
def api_state():
    _, state = hub.wait(-1, 0)
    return jsonify(state)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if processor is None:
        return jsonify({"error": "processor not ready"}), 503
    if request.method == "POST":
        values = request.get_json(silent=True) or {}
        return jsonify(processor.update_config(values))
    return jsonify(dict(processor.config))


@app.post("/api/recalibrate")
def api_recalibrate():
    if processor is None:
        return jsonify({"error": "processor not ready"}), 503
    processor.recalibrate()
    return jsonify({"ok": True})


@app.get("/api/stream")
def api_stream():
    def events():
        version = -1
        while True:
            version, state = hub.wait(version)
            yield f"id: {version}\ndata: {json.dumps(state, separators=(',', ':'))}\n\n"

    return Response(events(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


def processing_loop(config: dict) -> None:
    global processor
    camera = create_camera(config["camera"])
    processor = SilhouetteProcessor(config["processing"], int(config["camera"]["fps"]))
    try:
        hardware = create_output(config["hardware"])
    except Exception as exc:
        logging.exception("Hardware output unavailable; continuing in web-only mode: %s", exc)
        from shadow.output import NullOutput

        hardware = NullOutput()

    logging.info("Camera source: %s; output: %s", camera.name, hardware.name)
    frame_count = 0
    fps_started = time.monotonic()
    measured_fps = 0.0
    try:
        while True:
            frame = camera.read()
            levels, status = processor.process(frame)
            display_levels = levels
            try:
                display_levels = hardware.send(levels)
                hardware_error = ""
            except Exception as exc:
                hardware_error = str(exc)

            frame_count += 1
            now = time.monotonic()
            elapsed = now - fps_started
            if elapsed >= 1.0:
                measured_fps = frame_count / elapsed
                frame_count = 0
                fps_started = now
            hub.publish(
                {
                    "levels": base64.b64encode(display_levels.tobytes()).decode("ascii"),
                    "state": status["state"],
                    "area_ratio": status["area_ratio"],
                    "effective_threshold": status["effective_threshold"],
                    "brightness_shift": status["brightness_shift"],
                    "exposure_gain": status["exposure_gain"],
                    "frame_gain": status["frame_gain"],
                    "motion_ratio": status["motion_ratio"],
                    "component_motion_ratio": status["component_motion_ratio"],
                    "component_iou": status["component_iou"],
                    "stationary_score": status["stationary_score"],
                    "background_rebased": status["background_rebased"],
                    "calibration_remaining": status["calibration_remaining"],
                    "fps": round(measured_fps, 1),
                    "camera": camera.name,
                    "output": hardware.name,
                    "active_ripples": hardware.active_ripple_count,
                    "hardware_error": hardware_error,
                }
            )
    finally:
        camera.close()
        hardware.close()


def main() -> None:
    global runtime_config
    parser = argparse.ArgumentParser(description="Realtime 24x32 OpenGrid silhouette server")
    parser.add_argument("--config", help="JSON configuration path")
    parser.add_argument("--synthetic", action="store_true", help="Force generated test scene")
    args = parser.parse_args()
    runtime_config = load_config(args.config)
    if args.synthetic:
        runtime_config["camera"]["mode"] = "synthetic"
    thread = threading.Thread(target=processing_loop, args=(runtime_config,), daemon=True)
    thread.start()
    web = runtime_config["web"]
    app.run(host=str(web["host"]), port=int(web["port"]), threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
