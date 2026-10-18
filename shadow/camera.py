from __future__ import annotations

import math
import logging
import time
from abc import ABC, abstractmethod

import cv2
import numpy as np


class CameraSource(ABC):
    name = "camera"

    @abstractmethod
    def read(self) -> np.ndarray:
        raise NotImplementedError

    def close(self) -> None:
        pass


class Picamera2Source(CameraSource):
    name = "picamera2"

    def __init__(self, width: int, height: int, fps: int):
        from picamera2 import Picamera2  # Raspberry Pi only

        self.camera = Picamera2()
        config = self.camera.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"},
            controls={"FrameRate": fps},
            buffer_count=4,
        )
        self.camera.configure(config)
        self.camera.start()
        # The OV5647 changes exposure substantially during its first frames. Let AE/AWB
        # settle before the processor starts learning the empty-scene background.
        time.sleep(2.5)
        # Background subtraction is easily disturbed by AE/AWB hunting. Preserve the
        # converged values after warm-up so a static scene remains numerically stable.
        try:
            metadata = self.camera.capture_metadata()
            locked_controls = {"AeEnable": False, "AwbEnable": False}
            if "ExposureTime" in metadata:
                locked_controls["ExposureTime"] = int(metadata["ExposureTime"])
            if "AnalogueGain" in metadata:
                locked_controls["AnalogueGain"] = float(metadata["AnalogueGain"])
            if "ColourGains" in metadata:
                locked_controls["ColourGains"] = tuple(metadata["ColourGains"])
            self.camera.set_controls(locked_controls)
            time.sleep(0.3)
        except Exception as exc:
            logging.warning("Unable to lock camera auto controls: %s", exc)

    def read(self) -> np.ndarray:
        return self.camera.capture_array("main")

    def close(self) -> None:
        self.camera.stop()
        self.camera.close()


class OpenCVCameraSource(CameraSource):
    name = "opencv-camera"

    def __init__(self, index: int, width: int, height: int, fps: int):
        self.capture = cv2.VideoCapture(index)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_FPS, fps)
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open camera index {index}")

    def read(self) -> np.ndarray:
        ok, frame = self.capture.read()
        if not ok:
            raise RuntimeError("Camera frame read failed")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self.capture.release()


class SyntheticSource(CameraSource):
    """Moving person-like shape for development without camera hardware."""

    name = "synthetic"

    def __init__(self, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.period = 1.0 / max(fps, 1)
        self.started_at = time.monotonic()
        self.last_frame_at = 0.0

    def read(self) -> np.ndarray:
        now = time.monotonic()
        remaining = self.period - (now - self.last_frame_at)
        if remaining > 0:
            time.sleep(remaining)
        self.last_frame_at = time.monotonic()
        elapsed = self.last_frame_at - self.started_at

        yy, xx = np.mgrid[0 : self.height, 0 : self.width]
        background = 24 + 12 * (xx / max(self.width - 1, 1))
        frame = np.repeat(background[:, :, None], 3, axis=2).astype(np.uint8)
        if elapsed < 2.4:
            return frame

        center_x = self.width * (0.5 + 0.24 * math.sin(elapsed * 0.7))
        center_y = self.height * 0.55
        scale = 0.92 + 0.12 * math.sin(elapsed * 0.43)
        mask = np.zeros((self.height, self.width), dtype=np.uint8)
        cv2.circle(mask, (int(center_x), int(center_y - 66 * scale)), int(25 * scale), 255, -1)
        cv2.ellipse(
            mask,
            (int(center_x), int(center_y + 12 * scale)),
            (int(51 * scale), int(80 * scale)),
            0,
            0,
            360,
            255,
            -1,
        )
        arm = int(22 * math.sin(elapsed * 1.3))
        cv2.line(
            mask,
            (int(center_x - 38 * scale), int(center_y - 8 * scale)),
            (int(center_x - 70 * scale), int(center_y + arm)),
            255,
            int(18 * scale),
        )
        cv2.line(
            mask,
            (int(center_x + 38 * scale), int(center_y - 8 * scale)),
            (int(center_x + 70 * scale), int(center_y - arm)),
            255,
            int(18 * scale),
        )
        frame[mask > 0] = (205, 210, 218)
        return frame


def create_camera(config: dict) -> CameraSource:
    mode = str(config.get("mode", "auto")).lower()
    width = int(config["width"])
    height = int(config["height"])
    fps = int(config["fps"])

    if mode in {"auto", "picamera2"}:
        try:
            return Picamera2Source(width, height, fps)
        except Exception:
            if mode == "picamera2":
                raise
    if mode in {"auto", "opencv"}:
        try:
            return OpenCVCameraSource(int(config.get("index", 0)), width, height, fps)
        except Exception:
            if mode == "opencv":
                raise
    return SyntheticSource(width, height, fps)
