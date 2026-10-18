from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


DEFAULT_CONFIG = {
    "camera": {"mode": "auto", "index": 0, "width": 320, "height": 240, "fps": 12},
    "processing": {
        "threshold": 40,
        "adaptive_threshold": True,
        "noise_sigma": 6.0,
        "hysteresis_ratio": 0.65,
        "max_brightness_shift": 35,
        "min_area_ratio": 0.025,
        "calibration_seconds": 4.0,
        "background_learning_rate": 0.001,
        "stationary_timeout_seconds": 10.0,
        "stationary_motion_ratio": 0.003,
        "stationary_iou": 0.92,
        "stationary_decay_multiplier": 2.0,
        "rise_ms": 160,
        "fall_ms": 550,
        "edge_blur": 3,
        "pixel_on_threshold": 0.35,
        "edge_min_brightness": 0.28,
        "depth_gradient_pixels": 6.0,
        "output_cutoff": 0.10,
        "gamma": 1.0,
        "max_level": 15,
        "mirror": True,
    },
    "hardware": {
        "enabled": False,
        "driver": "i2c",
        "i2c_bus": 1,
        "reconnect_seconds": 2.0,
        "layout": [
            ["0x27", "0x2B", "0x2F"],
            ["0x26", "0x2A", "0x2E"],
            ["0x25", "0x29", "0x2D"],
            ["0x24", "0x28", "0x2C"],
        ],
        "board_rotations": [[270, 270, 270], [270, 270, 270], [270, 270, 270], [270, 270, 270]],
        "ripple": {
            "enabled": True,
            "boards_per_frame": 4,
            "key_cooldown_seconds": 0.25,
            "duration_seconds": 5.0,
            "speed_pixels_per_second": 8.5,
            "wavelength_pixels": 5.0,
            "ring_width_pixels": 5.5,
            "strength": 0.72,
            "image_modulation": 0.42,
            "attack_seconds": 0.12,
            "decay_seconds": 3.2,
            "max_active": 8,
        },
    },
    "web": {"host": "0.0.0.0", "port": 8080},
}


def _merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None) -> dict:
    if not path:
        return deepcopy(DEFAULT_CONFIG)
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    return _merge(DEFAULT_CONFIG, json.loads(config_path.read_text(encoding="utf-8")))
