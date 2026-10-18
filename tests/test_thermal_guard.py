import unittest

from thermal_guard import thermal_action


class ThermalGuardTests(unittest.TestCase):
    def test_running_service_pauses_at_hot_threshold(self):
        self.assertIsNone(thermal_action(74.9, False))
        self.assertEqual(thermal_action(75.0, False), "pause")

    def test_guard_paused_service_resumes_only_when_cool(self):
        self.assertIsNone(thermal_action(65.1, True))
        self.assertEqual(thermal_action(65.0, True), "resume")

    def test_hysteresis_does_not_toggle_inside_band(self):
        self.assertIsNone(thermal_action(70.0, False))
        self.assertIsNone(thermal_action(70.0, True))


if __name__ == "__main__":
    unittest.main()
