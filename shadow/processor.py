from __future__ import annotations

import math
import threading
import time

import cv2
import numpy as np


class SilhouetteProcessor:
    OUTPUT_WIDTH = 24
    OUTPUT_HEIGHT = 32

    def __init__(self, config: dict, fps: int):
        self._lock = threading.Lock()
        self.config = dict(config)
        self.fps = fps
        self.background: np.ndarray | None = None
        self.smoothed = np.zeros((self.OUTPUT_HEIGHT, self.OUTPUT_WIDTH), dtype=np.float32)
        self.previous_bbox: tuple[int, int, int, int] | None = None
        self.previous_gray: np.ndarray | None = None
        self.previous_selected: np.ndarray | None = None
        self.stationary_score = 0.0
        self.calibration_started = time.monotonic()
        self.last_time = time.monotonic()

    def recalibrate(self) -> None:
        with self._lock:
            self.background = None
            self.previous_bbox = None
            self.previous_gray = None
            self.previous_selected = None
            self.stationary_score = 0.0
            self.smoothed.fill(0.0)
            self.calibration_started = time.monotonic()

    def update_config(self, values: dict) -> dict:
        allowed = {
            "threshold",
            "adaptive_threshold",
            "noise_sigma",
            "hysteresis_ratio",
            "max_brightness_shift",
            "min_area_ratio",
            "rise_ms",
            "fall_ms",
            "edge_blur",
            "pixel_on_threshold",
            "edge_min_brightness",
            "depth_gradient_pixels",
            "output_cutoff",
            "gamma",
            "max_level",
            "mirror",
            "background_learning_rate",
            "stationary_timeout_seconds",
            "stationary_motion_ratio",
            "stationary_iou",
            "stationary_decay_multiplier",
        }
        with self._lock:
            for key, value in values.items():
                if key in allowed:
                    self.config[key] = value
            self.config["threshold"] = int(np.clip(int(self.config["threshold"]), 5, 120))
            self.config["adaptive_threshold"] = bool(self.config.get("adaptive_threshold", True))
            self.config["noise_sigma"] = float(
                np.clip(float(self.config.get("noise_sigma", 6.0)), 1.0, 12.0)
            )
            self.config["hysteresis_ratio"] = float(
                np.clip(float(self.config.get("hysteresis_ratio", 0.65)), 0.3, 0.95)
            )
            self.config["max_brightness_shift"] = int(
                np.clip(int(self.config.get("max_brightness_shift", 35)), 0, 80)
            )
            self.config["min_area_ratio"] = float(np.clip(float(self.config["min_area_ratio"]), 0.001, 0.5))
            self.config["rise_ms"] = int(np.clip(int(self.config["rise_ms"]), 10, 3000))
            self.config["fall_ms"] = int(np.clip(int(self.config["fall_ms"]), 10, 5000))
            self.config["edge_blur"] = int(np.clip(int(self.config["edge_blur"]), 1, 31)) | 1
            self.config["pixel_on_threshold"] = float(
                np.clip(float(self.config.get("pixel_on_threshold", 0.35)), 0.05, 0.95)
            )
            self.config["edge_min_brightness"] = float(
                np.clip(float(self.config.get("edge_min_brightness", 0.28)), 0.05, 0.9)
            )
            self.config["depth_gradient_pixels"] = float(
                np.clip(float(self.config.get("depth_gradient_pixels", 6.0)), 1.0, 12.0)
            )
            self.config["output_cutoff"] = float(
                np.clip(float(self.config.get("output_cutoff", 0.10)), 0.0, 0.5)
            )
            self.config["gamma"] = float(np.clip(float(self.config["gamma"]), 0.4, 3.0))
            self.config["max_level"] = int(np.clip(int(self.config["max_level"]), 1, 15))
            self.config["stationary_timeout_seconds"] = float(
                np.clip(float(self.config.get("stationary_timeout_seconds", 8.0)), 3.0, 120.0)
            )
            self.config["stationary_motion_ratio"] = float(
                np.clip(float(self.config.get("stationary_motion_ratio", 0.006)), 0.0005, 0.1)
            )
            self.config["stationary_iou"] = float(
                np.clip(float(self.config.get("stationary_iou", 0.92)), 0.5, 0.999)
            )
            self.config["stationary_decay_multiplier"] = float(
                np.clip(float(self.config.get("stationary_decay_multiplier", 2.0)), 0.5, 10.0)
            )
            return dict(self.config)

    @staticmethod
    def _bbox_iou(a: tuple[int, int, int, int] | None, b: tuple[int, int, int, int]) -> float:
        if a is None:
            return 0.0
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        left, top = max(ax, bx), max(ay, by)
        right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        intersection = max(0, right - left) * max(0, bottom - top)
        union = aw * ah + bw * bh - intersection
        return intersection / union if union else 0.0

    @staticmethod
    def _exposure_compensated_difference(
        current: np.ndarray,
        reference: np.ndarray,
        max_shift: int,
    ) -> tuple[np.ndarray, float, float]:
        """Compare frames after robust affine exposure alignment.

        Camera exposure and mains-powered lighting change contrast as well as brightness.
        Two robust percentiles estimate the gain, while the median residual estimates the
        offset. Sparse sampling keeps this inexpensive on the Pi.
        """
        current_sample = current[::4, ::4].astype(np.float32)
        reference_sample = reference[::4, ::4].astype(np.float32)
        ref_low, ref_high = np.percentile(reference_sample, (15.0, 85.0))
        cur_low, cur_high = np.percentile(current_sample, (15.0, 85.0))
        reference_range = float(ref_high - ref_low)
        if reference_range >= 8.0:
            gain = float(np.clip((cur_high - cur_low) / reference_range, 0.75, 1.25))
        else:
            gain = 1.0
        residual_sample = current_sample - gain * reference_sample
        shift = float(np.clip(np.median(residual_sample), -max_shift, max_shift))
        expected = gain * reference.astype(np.float32) + shift
        difference = np.clip(np.abs(current.astype(np.float32) - expected), 0, 255).astype(
            np.uint8
        )
        return difference, gain, shift

    def process(self, rgb: np.ndarray) -> tuple[np.ndarray, dict]:
        now = time.monotonic()
        dt = min(max(now - self.last_time, 1.0 / 120.0), 0.25)
        self.last_time = now
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        # Suppress sensor-level flicker before comparing against the background.
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        with self._lock:
            cfg = dict(self.config)
            if self.previous_gray is None:
                motion_ratio = 1.0
                motion_difference = np.full_like(gray, 255, dtype=np.int16)
                frame_gain = 1.0
            else:
                # Remove both exposure gain and offset before measuring scene motion.
                motion_difference, frame_gain, _ = self._exposure_compensated_difference(
                    gray, self.previous_gray, 35
                )
                motion_ratio = float(np.count_nonzero(motion_difference >= 8) / gray.size)
            self.previous_gray = gray.copy()
            background_rebased = False
            component_motion_ratio = 1.0
            component_iou = 0.0
            if self.background is None:
                self.background = gray.astype(np.float32)
                self.calibration_started = now

            calibration_seconds = float(cfg.get("calibration_seconds", 2.0))
            calibrating = now - self.calibration_started < calibration_seconds
            if calibrating:
                cv2.accumulateWeighted(gray, self.background, 0.12)
                target = np.zeros_like(self.smoothed)
                area_ratio = 0.0
                state = "calibrating"
                self.previous_selected = None
                self.stationary_score = 0.0
                effective_threshold = int(cfg["threshold"])
                brightness_shift = 0
            else:
                background_u8 = cv2.convertScaleAbs(self.background)
                # Camera auto exposure can shift almost every pixel at once. Estimate that
                # shift from a sparse sample so scene structure, not raw brightness, drives
                # foreground detection. Clamping prevents a very large object from fully
                # cancelling itself out by dominating the estimate.
                max_shift = int(cfg.get("max_brightness_shift", 35))
                difference, exposure_gain, exposure_shift = self._exposure_compensated_difference(
                    gray, background_u8, max_shift
                )
                brightness_shift = int(round(exposure_shift))

                # Raise the threshold automatically when sensor noise increases, but never
                # below the user's selected base threshold. Median/MAD stays robust while
                # the foreground covers less than half of the camera image.
                effective_threshold = int(cfg["threshold"])
                if bool(cfg.get("adaptive_threshold", True)):
                    noise_sample = difference[::4, ::4].astype(np.float32).ravel()
                    # Estimate noise from the quieter 60% of pixels so a person or a
                    # temporarily stale background cannot inflate the threshold. The
                    # bounded headroom is important after camera start-up, when exposure
                    # and white balance may still be settling.
                    quiet_limit = float(np.percentile(noise_sample, 60.0))
                    quiet_sample = noise_sample[noise_sample <= quiet_limit]
                    noise_median = float(np.median(quiet_sample))
                    noise_mad = float(np.median(np.abs(quiet_sample - noise_median)))
                    noise_limit = round(
                        noise_median
                        + float(cfg.get("noise_sigma", 6.0)) * 1.4826 * noise_mad
                        + 2.0
                    )
                    adaptive_ceiling = min(120, effective_threshold + 24)
                    effective_threshold = int(
                        np.clip(max(effective_threshold, noise_limit), 5, adaptive_ceiling)
                    )

                # Hysteresis admits weak edge pixels only when they connect to a confidently
                # changed region. This retains limbs without admitting isolated shimmer.
                strong = np.where(difference >= effective_threshold, 255, 0).astype(np.uint8)
                weak_threshold = max(
                    5,
                    round(effective_threshold * float(cfg.get("hysteresis_ratio", 0.65))),
                )
                weak = difference >= weak_threshold
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                foreground = strong
                for _ in range(3):
                    foreground = cv2.dilate(foreground, kernel)
                    foreground = np.where(weak, foreground, 0).astype(np.uint8)

                # One opening removes speckles without eroding thin limbs. A wider closing
                # reconnects nearby pieces of one body before component selection.
                foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel, iterations=1)
                close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                foreground = cv2.morphologyEx(
                    foreground, cv2.MORPH_CLOSE, close_kernel, iterations=2
                )

                count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)
                frame_area = gray.shape[0] * gray.shape[1]
                minimum_area = max(32, int(frame_area * float(cfg["min_area_ratio"])))
                best_label = -1
                best_score = -1.0
                best_bbox = None
                best_area = 0
                for label in range(1, count):
                    x, y, width, height, area = (int(v) for v in stats[label])
                    if area < minimum_area:
                        continue
                    bbox = (x, y, width, height)
                    area_score = min(area / (frame_area * 0.45), 1.0)
                    bottom_score = min((y + height) / gray.shape[0], 1.0)
                    persistence = self._bbox_iou(self.previous_bbox, bbox)
                    # Projected area is the most useful lightweight monocular proxy for
                    # closeness. Bottom position and continuity only break close decisions.
                    score = 0.72 * area_score + 0.12 * bottom_score + 0.16 * persistence
                    if score > best_score:
                        best_score, best_label, best_bbox, best_area = score, label, bbox, area

                selected = np.zeros_like(foreground)
                if best_label >= 0 and best_bbox is not None:
                    selected[labels == best_label] = 255
                    self.previous_bbox = best_bbox
                    # Draw external contours as solid shapes, eliminating small holes and
                    # texture inside the silhouette.
                    contours, _ = cv2.findContours(selected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    solid = np.zeros_like(selected)
                    cv2.drawContours(solid, contours, -1, 255, cv2.FILLED)
                    blur = int(cfg["edge_blur"]) | 1
                    solid = cv2.GaussianBlur(solid, (blur, blur), 0)
                    coverage = cv2.resize(
                        solid.astype(np.float32) / 255.0,
                        (self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT),
                        interpolation=cv2.INTER_AREA,
                    )
                    # Keep the background strictly off, but grade brightness inside the
                    # silhouette by distance from its edge. This creates several real
                    # hardware levels instead of relying on the browser's cosmetic glow.
                    on_pixels = coverage >= float(cfg.get("pixel_on_threshold", 0.35))
                    distance = cv2.distanceTransform(
                        on_pixels.astype(np.uint8), cv2.DIST_L2, 3
                    )
                    depth = np.clip(
                        distance / float(cfg.get("depth_gradient_pixels", 6.0)), 0.0, 1.0
                    )
                    edge_level = float(cfg.get("edge_min_brightness", 0.28))
                    target = np.where(
                        on_pixels,
                        edge_level + (1.0 - edge_level) * depth,
                        0.0,
                    ).astype(np.float32)
                    area_ratio = best_area / frame_area
                    state = "tracking"
                else:
                    self.previous_bbox = None
                    target = np.zeros_like(self.smoothed)
                    area_ratio = 0.0
                    state = "idle"

                # Track the chosen component rather than the whole frame. A residual has
                # high mask overlap and almost no local pixel motion. Evidence accumulates
                # across brief sensor-noise spikes instead of restarting from zero.
                if state == "tracking":
                    selected_pixels = selected > 0
                    selected_count = int(np.count_nonzero(selected_pixels))
                    if selected_count:
                        component_motion_ratio = float(
                            np.count_nonzero(motion_difference[selected_pixels] >= 8)
                            / selected_count
                        )
                    if self.previous_selected is not None:
                        previous_pixels = self.previous_selected > 0
                        intersection = int(np.count_nonzero(selected_pixels & previous_pixels))
                        union = int(np.count_nonzero(selected_pixels | previous_pixels))
                        component_iou = intersection / union if union else 0.0

                    stable_component = (
                        component_iou >= float(cfg.get("stationary_iou", 0.92))
                        and component_motion_ratio
                        <= float(cfg.get("stationary_motion_ratio", 0.003))
                    )
                    if stable_component:
                        self.stationary_score += dt
                    else:
                        decay = float(cfg.get("stationary_decay_multiplier", 2.0))
                        self.stationary_score = max(0.0, self.stationary_score - dt * decay)
                    self.previous_selected = selected.copy()

                    timeout = float(cfg.get("stationary_timeout_seconds", 10.0))
                    if stable_component and self.stationary_score >= timeout:
                        # Rebase just this component plus its edge, preserving unrelated
                        # moving silhouettes elsewhere in the scene.
                        rebase_mask = cv2.dilate(selected, close_kernel, iterations=1) > 0
                        self.background[rebase_mask] = gray[rebase_mask].astype(np.float32)
                        self.previous_bbox = None
                        self.previous_selected = None
                        self.stationary_score = 0.0
                        target = np.zeros_like(self.smoothed)
                        area_ratio = 0.0
                        state = "idle"
                        background_rebased = True
                else:
                    self.previous_selected = None
                    self.stationary_score = 0.0

                update_mask = cv2.bitwise_not(cv2.dilate(foreground, kernel, iterations=2))
                learning_rate = float(cfg.get("background_learning_rate", 0.001))
                cv2.accumulateWeighted(gray, self.background, learning_rate, mask=update_mask)

            tau_on = max(float(cfg["rise_ms"]) / 1000.0, 0.01)
            tau_off = max(float(cfg["fall_ms"]) / 1000.0, 0.01)
            alpha_on = 1.0 - math.exp(-dt / tau_on)
            alpha_off = 1.0 - math.exp(-dt / tau_off)
            alpha = np.where(target > self.smoothed, alpha_on, alpha_off)
            self.smoothed += alpha * (target - self.smoothed)
            output = self.smoothed[:, ::-1] if bool(cfg["mirror"]) else self.smoothed
            output = np.where(output >= float(cfg.get("output_cutoff", 0.10)), output, 0.0)
            corrected = np.power(np.clip(output, 0.0, 1.0), float(cfg["gamma"]))
            levels = np.rint(corrected * int(cfg["max_level"])).astype(np.uint8)

        return levels, {
            "state": state,
            "area_ratio": round(area_ratio, 4),
            "effective_threshold": effective_threshold,
            "brightness_shift": brightness_shift,
            "exposure_gain": round(exposure_gain if not calibrating else 1.0, 3),
            "frame_gain": round(frame_gain, 3),
            "motion_ratio": round(motion_ratio, 4),
            "component_motion_ratio": round(component_motion_ratio, 4),
            "component_iou": round(component_iou, 4),
            "stationary_score": round(self.stationary_score, 2),
            "background_rebased": background_rebased,
            "calibration_remaining": round(max(0.0, calibration_seconds - (now - self.calibration_started)), 1),
        }
