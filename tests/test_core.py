import unittest

import numpy as np

from shadow.output import BoardPlacement, I2COpenGridOutput
from shadow.processor import SilhouetteProcessor
from shadow.ripple import RippleEngine


class CoreTests(unittest.TestCase):
    @staticmethod
    def processor_config(**overrides):
        config = {
            "threshold": 30,
            "adaptive_threshold": True,
            "noise_sigma": 6.0,
            "hysteresis_ratio": 0.65,
            "max_brightness_shift": 35,
            "min_area_ratio": 0.02,
            "calibration_seconds": 0.0,
            "background_learning_rate": 0.0,
            "stationary_timeout_seconds": 10.0,
            "stationary_motion_ratio": 0.003,
            "stationary_iou": 0.92,
            "stationary_decay_multiplier": 2.0,
            "rise_ms": 10,
            "fall_ms": 300,
            "edge_blur": 3,
            "pixel_on_threshold": 0.35,
            "output_cutoff": 0.10,
            "gamma": 1.0,
            "max_level": 15,
            "mirror": False,
        }
        config.update(overrides)
        return config

    def test_i2c_address_bits_and_layout(self):
        placements = I2COpenGridOutput._parse_layout(
            {
                "layout": [
                    ["0x27", "0x2B", "0x2F"],
                    ["0x26", "0x2A", "0x2E"],
                    ["0x25", "0x29", "0x2D"],
                    ["0x24", "0x28", "0x2C"],
                ]
            }
        )
        self.assertEqual(
            [item.address for item in placements],
            [0x27, 0x2B, 0x2F, 0x26, 0x2A, 0x2E, 0x25, 0x29, 0x2D, 0x24, 0x28, 0x2C],
        )
        self.assertEqual((placements[0].row, placements[0].column), (0, 0))
        self.assertEqual((placements[-1].row, placements[-1].column), (3, 2))

    def test_i2c_board_mapping_uses_official_column_major_index(self):
        levels = np.zeros((32, 24), dtype=np.uint8)
        levels[0, 0] = 1
        levels[1, 0] = 2
        levels[0, 1] = 3
        board = I2COpenGridOutput.board_levels(levels, BoardPlacement(0x28, 0, 0))
        packed = I2COpenGridOutput._pack_board(board)
        self.assertEqual(len(packed), 32)
        self.assertEqual(packed[0], 0x12)
        self.assertEqual(packed[4], 0x30)

    def test_i2c_board_rotation_is_clockwise(self):
        levels = np.zeros((32, 24), dtype=np.uint8)
        levels[0, 0] = 9
        rotated = I2COpenGridOutput.board_levels(
            levels, BoardPlacement(0x28, 0, 0, rotation=90)
        )
        self.assertEqual(rotated[0, 7], 9)

    def test_i2c_protocol_uses_packed_blocks_then_show(self):
        output = object.__new__(I2COpenGridOutput)
        writes = []
        output._write = lambda address, data: writes.append((address, data))
        output._send_board(0x28, bytes(range(32)))
        self.assertEqual([len(data) for _, data in writes], [32, 6, 1])
        self.assertEqual(writes[0][1][:3], bytes((0x17, 0, 58)))
        self.assertEqual(writes[1][1][:3], bytes((0x17, 58, 6)))
        self.assertEqual(writes[2], (0x28, bytes((0x13,))))

    def test_key_coordinates_follow_board_rotation_and_position(self):
        placement = BoardPlacement(0x28, row=1, column=2, rotation=270)
        self.assertEqual(I2COpenGridOutput.key_to_global(placement, 0), (23, 8))
        self.assertEqual(I2COpenGridOutput.key_to_global(placement, 63), (16, 15))

    def test_key_reader_uses_official_block_command(self):
        output = object.__new__(I2COpenGridOutput)
        calls = []

        def read_command(address, command, length):
            calls.append((address, command, length))
            return bytes([1 if index == 3 else 0 for index in range(length)])

        output._read_command = read_command
        states = output._read_keys(0x27)
        self.assertEqual(calls, [(0x27, [0x21, 0, 32], 32), (0x27, [0x21, 32, 32], 32)])
        self.assertTrue(states[3])
        self.assertTrue(states[35])

    def test_ripple_emits_light_and_modulates_camera_image(self):
        engine = RippleEngine(
            24,
            32,
            {
                "duration_seconds": 5.0,
                "speed_pixels_per_second": 8.5,
                "wavelength_pixels": 5.0,
                "ring_width_pixels": 5.5,
                "strength": 0.72,
                "image_modulation": 0.42,
            },
        )
        engine.trigger(12, 16, 10.0)
        blank = engine.render(np.zeros((32, 24), dtype=np.uint8), 10.8)
        self.assertGreater(np.count_nonzero(blank), 20)
        self.assertGreaterEqual(len(np.unique(blank[blank > 0])), 4)

        camera = np.full((32, 24), 8, dtype=np.uint8)
        affected = engine.render(camera, 10.8)
        self.assertGreater(int(affected.max()), 8)
        self.assertLess(int(affected.min()), 8)
        self.assertEqual(engine.active_count, 1)

    def test_small_noise_is_rejected_and_silhouette_is_solid(self):
        processor = SilhouetteProcessor(self.processor_config(), 15)
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        frame = background.copy()
        frame[60:210, 105:215] = 255
        frame[10, 10] = 255
        levels, status = processor.process(frame)
        self.assertEqual(status["state"], "tracking")
        self.assertGreater(np.count_nonzero(levels), 40)
        self.assertEqual(levels[1, 1], 0)

    def test_silhouette_depth_gradient_generates_real_brightness_levels(self):
        processor = SilhouetteProcessor(
            self.processor_config(
                gamma=1.0,
                max_level=15,
                edge_min_brightness=0.28,
                depth_gradient_pixels=6.0,
            ),
            15,
        )
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        frame = background.copy()
        frame[30:225, 65:255] = 255
        levels = None
        for _ in range(8):
            processor.last_time -= 0.08
            levels, _ = processor.process(frame)
        nonzero_levels = np.unique(levels[levels > 0])
        self.assertGreaterEqual(len(nonzero_levels), 5)
        self.assertEqual(levels[0, 0], 0)
        self.assertEqual(int(levels.max()), 15)

    def test_global_exposure_change_is_not_foreground(self):
        processor = SilhouetteProcessor(self.processor_config(), 15)
        background = np.full((240, 320, 3), 80, dtype=np.uint8)
        processor.process(background)
        brighter = np.full_like(background, 103)
        levels, status = processor.process(brighter)
        self.assertEqual(status["state"], "idle")
        self.assertEqual(np.count_nonzero(levels), 0)
        self.assertEqual(status["brightness_shift"], 23)

    def test_multiplicative_exposure_change_is_not_foreground(self):
        processor = SilhouetteProcessor(self.processor_config(), 12)
        gradient = np.tile(np.linspace(30, 180, 320, dtype=np.uint8), (240, 1))
        background = np.repeat(gradient[:, :, None], 3, axis=2)
        processor.process(background)
        changed = np.clip(background.astype(np.float32) * 1.18 + 8, 0, 255).astype(np.uint8)
        levels, status = processor.process(changed)
        self.assertEqual(status["state"], "idle")
        self.assertEqual(np.count_nonzero(levels), 0)
        self.assertAlmostEqual(status["exposure_gain"], 1.18, delta=0.03)

    def test_largest_component_wins(self):
        processor = SilhouetteProcessor(self.processor_config(min_area_ratio=0.005), 15)
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        frame = background.copy()
        frame[40:90, 20:60] = 255
        frame[55:220, 150:270] = 255
        levels, status = processor.process(frame)
        self.assertEqual(status["state"], "tracking")
        self.assertEqual(levels[5, 4], 0)
        self.assertGreater(np.count_nonzero(levels[:, 10:24]), 60)

    def test_recalibration_clears_fading_ghost(self):
        processor = SilhouetteProcessor(self.processor_config(fall_ms=2000), 15)
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        frame = background.copy()
        frame[50:220, 100:220] = 255
        levels, _ = processor.process(frame)
        self.assertGreater(np.count_nonzero(levels), 0)
        processor.recalibrate()
        levels, status = processor.process(background)
        self.assertEqual(status["state"], "idle")
        self.assertEqual(np.count_nonzero(levels), 0)

    def test_extreme_contrast_does_not_wrap_uint8(self):
        processor = SilhouetteProcessor(self.processor_config(), 15)
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        frame = background.copy()
        frame[40:220, 100:220] = 255
        levels, status = processor.process(frame)
        self.assertEqual(status["state"], "tracking")
        self.assertGreater(np.count_nonzero(levels), 80)

    def test_adaptive_threshold_has_bounded_headroom(self):
        processor = SilhouetteProcessor(self.processor_config(), 15)
        background = np.full((240, 320, 3), 100, dtype=np.uint8)
        processor.process(background)
        rng = np.random.default_rng(9)
        noisy = np.clip(
            background.astype(np.int16)
            + rng.integers(-70, 71, background.shape, dtype=np.int16),
            0,
            255,
        ).astype(np.uint8)
        _, status = processor.process(noisy)
        self.assertGreaterEqual(status["effective_threshold"], 30)
        self.assertLessEqual(status["effective_threshold"], 54)

    def test_stationary_residual_is_rebased_after_timeout(self):
        processor = SilhouetteProcessor(
            self.processor_config(stationary_timeout_seconds=3.0), 12
        )
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        residual = background.copy()
        residual[70:190, 120:200] = 180
        first_levels, first = processor.process(residual)
        self.assertEqual(first["state"], "tracking")
        processor.stationary_score = 4.0
        # Make the fade assertion independent of host speed. Back-to-back calls can
        # otherwise quantize to the same 4-bit level on a fast development machine.
        processor.last_time -= 0.25
        levels, cleared = processor.process(residual)
        self.assertEqual(cleared["state"], "idle")
        self.assertTrue(cleared["background_rebased"])
        self.assertEqual(cleared["area_ratio"], 0.0)
        self.assertLess(int(np.sum(levels)), int(np.sum(first_levels)))

    def test_motion_prevents_stationary_rebase(self):
        processor = SilhouetteProcessor(
            self.processor_config(stationary_timeout_seconds=3.0), 12
        )
        background = np.zeros((240, 320, 3), dtype=np.uint8)
        processor.process(background)
        first_frame = background.copy()
        first_frame[70:190, 100:180] = 180
        processor.process(first_frame)
        processor.stationary_score = 4.0
        moved = background.copy()
        moved[70:190, 150:230] = 180
        _, status = processor.process(moved)
        self.assertEqual(status["state"], "tracking")
        self.assertFalse(status["background_rebased"])



if __name__ == "__main__":
    unittest.main()
