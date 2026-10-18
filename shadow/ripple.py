from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Ripple:
    x: float
    y: float
    started: float


class RippleEngine:
    """Render damped radial waves over an existing 4-bit LED image."""

    def __init__(self, width: int, height: int, config: dict):
        self.width = width
        self.height = height
        self.enabled = bool(config.get("enabled", True))
        self.duration = max(0.5, float(config.get("duration_seconds", 5.0)))
        self.speed = max(0.5, float(config.get("speed_pixels_per_second", 8.5)))
        self.wavelength = max(1.5, float(config.get("wavelength_pixels", 5.0)))
        self.ring_width = max(1.0, float(config.get("ring_width_pixels", 5.5)))
        self.strength = float(np.clip(float(config.get("strength", 0.72)), 0.0, 1.5))
        self.image_modulation = float(
            np.clip(float(config.get("image_modulation", 0.42)), 0.0, 1.0)
        )
        self.attack = max(0.01, float(config.get("attack_seconds", 0.12)))
        self.decay = max(0.2, float(config.get("decay_seconds", 3.2)))
        self.max_active = max(1, int(config.get("max_active", 8)))
        yy, xx = np.mgrid[0:height, 0:width]
        self._xx = xx.astype(np.float32)
        self._yy = yy.astype(np.float32)
        self._ripples: list[Ripple] = []

    @property
    def active_count(self) -> int:
        return len(self._ripples)

    def trigger(self, x: int, y: int, now: float) -> None:
        if not self.enabled or not (0 <= x < self.width and 0 <= y < self.height):
            return
        self._ripples.append(Ripple(float(x), float(y), now))
        self._ripples = self._ripples[-self.max_active :]

    def render(self, levels: np.ndarray, now: float) -> np.ndarray:
        base_levels = np.clip(np.asarray(levels), 0, 15).astype(np.uint8)
        if not self.enabled:
            return base_levels.copy()

        self._ripples = [ripple for ripple in self._ripples if now - ripple.started < self.duration]
        if not self._ripples:
            return base_levels.copy()

        base = base_levels.astype(np.float32) / 15.0
        signed_wave = np.zeros_like(base, dtype=np.float32)
        positive_wave = np.zeros_like(base, dtype=np.float32)

        for ripple in self._ripples:
            age = max(0.0, now - ripple.started)
            radius = self.speed * age
            distance = np.hypot(self._xx - ripple.x, self._yy - ripple.y)
            offset = distance - radius
            envelope = np.exp(-0.5 * np.square(offset / self.ring_width))
            carrier = np.cos((2.0 * math.pi / self.wavelength) * offset)
            attack = min(age / self.attack, 1.0)
            damping = math.exp(-age / self.decay)
            end_fade = min(max((self.duration - age) / 0.7, 0.0), 1.0)
            wave = carrier * envelope * attack * damping * end_fade
            signed_wave += wave
            positive_wave += np.maximum(wave, 0.0)

        # The signed wave makes the camera silhouette flex at each crest and trough.
        # Positive crests also emit light into the dark background, so a key press is
        # visible even when the camera currently sees no foreground at that location.
        modulated_image = base * (1.0 + self.image_modulation * signed_wave)
        emitted_rings = self.strength * positive_wave * (1.0 - 0.35 * base)
        combined = np.clip(modulated_image + emitted_rings, 0.0, 1.0)
        return np.rint(combined * 15.0).astype(np.uint8)
