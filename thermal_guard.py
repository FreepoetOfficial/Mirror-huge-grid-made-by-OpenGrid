from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path


TEMPERATURE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
PAUSED_MARKER = Path("/run/opengrid-thermal-guard.paused")
TARGET_SERVICE = "opengrid-shadow.service"
PAUSE_AT_C = 75.0
RESUME_AT_C = 65.0
POLL_SECONDS = 5.0


def thermal_action(temperature_c: float, paused_by_guard: bool) -> str | None:
    """Return the hysteresis action for the current temperature."""
    if not paused_by_guard and temperature_c >= PAUSE_AT_C:
        return "pause"
    if paused_by_guard and temperature_c <= RESUME_AT_C:
        return "resume"
    return None


def read_temperature_c() -> float:
    return int(TEMPERATURE_PATH.read_text(encoding="ascii").strip()) / 1000.0


def service_is_active() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", TARGET_SERVICE],
        check=False,
    )
    return result.returncode == 0


def control_service(command: str) -> None:
    subprocess.run(["systemctl", command, TARGET_SERVICE], check=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info(
        "Thermal guard started: pause at %.1fC, resume at %.1fC",
        PAUSE_AT_C,
        RESUME_AT_C,
    )
    while True:
        try:
            temperature_c = read_temperature_c()
            paused_by_guard = PAUSED_MARKER.exists()
            action = thermal_action(temperature_c, paused_by_guard)
            if action == "pause" and service_is_active():
                logging.warning("Temperature %.1fC: pausing %s", temperature_c, TARGET_SERVICE)
                control_service("stop")
                PAUSED_MARKER.touch()
            elif action == "resume":
                logging.info("Temperature %.1fC: resuming %s", temperature_c, TARGET_SERVICE)
                control_service("start")
                PAUSED_MARKER.unlink(missing_ok=True)
        except Exception:
            logging.exception("Thermal guard check failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
