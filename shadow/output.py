from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from shadow.ripple import RippleEngine


class NullOutput:
    name = "web-only"
    active_ripple_count = 0

    def send(self, levels: np.ndarray) -> np.ndarray:
        return np.asarray(levels).copy()

    def close(self) -> None:
        pass


@dataclass(frozen=True)
class BoardPlacement:
    address: int
    row: int
    column: int
    rotation: int = 0


class I2COpenGridOutput:
    """Drive official FREEPOET keypad firmware directly over one I2C bus.

    Protocol 0x02 uses packed brightness writes at register 0x17 followed by
    register 0x13 to display the buffered frame. Each board contributes its
    first 8x8 (64-key) LED block.
    """

    PROTOCOL_VERSION = 0x02
    REG_PROTOCOL_VERSION = 0x00
    REG_DEVICE_ADDRESS = 0x01
    REG_KEY_COUNT_LOW = 0x02
    REG_KEY_COUNT_HIGH = 0x03
    REG_LED_SHOW = 0x13
    REG_LED_SET_LEVEL_BLOCK_PACKED = 0x17
    REG_KEY_READ_BLOCK = 0x21
    BOARD_SIZE = 8
    BOARD_PIXELS = 64
    MAX_PACKED_BLOCK = 58

    def __init__(self, config: dict):
        try:
            from smbus2 import SMBus, i2c_msg
        except ImportError as exc:
            raise RuntimeError("I2C output requires the smbus2 package") from exc

        self._i2c_msg = i2c_msg
        self._bus_number = int(config.get("i2c_bus", 1))
        self._retry_seconds = max(0.25, float(config.get("reconnect_seconds", 2.0)))
        ripple_config = dict(config.get("ripple", {}))
        self._key_boards_per_frame = max(
            1, min(12, int(ripple_config.get("boards_per_frame", 4)))
        )
        self._key_cooldown = max(0.05, float(ripple_config.get("key_cooldown_seconds", 0.25)))
        self._placements = self._parse_layout(config)
        self._rows = max(item.row for item in self._placements) + 1
        self._columns = max(item.column for item in self._placements) + 1
        self._expected_shape = (self._rows * self.BOARD_SIZE, self._columns * self.BOARD_SIZE)
        self._bus = SMBus(self._bus_number)
        self._lock = threading.Lock()
        self._online: set[int] = set()
        self._retry_after = {item.address: 0.0 for item in self._placements}
        self._last_frames: dict[int, bytes] = {}
        self._key_states = {
            item.address: np.zeros(self.BOARD_PIXELS, dtype=np.bool_) for item in self._placements
        }
        self._last_key_trigger: dict[tuple[int, int], float] = {}
        self._key_poll_cursor = 0
        self._ripple = RippleEngine(
            self._columns * self.BOARD_SIZE,
            self._rows * self.BOARD_SIZE,
            ripple_config,
        )
        self.name = f"i2c:/dev/i2c-{self._bus_number} ({len(self._placements)} boards)"

    @property
    def active_ripple_count(self) -> int:
        return self._ripple.active_count

    @classmethod
    def _parse_layout(cls, config: dict) -> list[BoardPlacement]:
        raw_layout = config.get("layout")
        if not isinstance(raw_layout, list) or not raw_layout:
            raise ValueError("hardware.layout must be a non-empty list of board rows")

        raw_rotations = config.get("board_rotations")
        placements: list[BoardPlacement] = []
        row_width = None
        for row, entries in enumerate(raw_layout):
            if not isinstance(entries, list) or not entries:
                raise ValueError("Every hardware.layout row must be a non-empty list")
            if row_width is None:
                row_width = len(entries)
            elif len(entries) != row_width:
                raise ValueError("hardware.layout must be rectangular")
            for column, raw_address in enumerate(entries):
                address = cls._parse_address(raw_address)
                rotation = 0
                if raw_rotations is not None:
                    try:
                        rotation = int(raw_rotations[row][column])
                    except (IndexError, TypeError) as exc:
                        raise ValueError("hardware.board_rotations must match hardware.layout") from exc
                if rotation not in (0, 90, 180, 270):
                    raise ValueError("Board rotations must be 0, 90, 180, or 270 degrees")
                placements.append(BoardPlacement(address, row, column, rotation))

        addresses = [item.address for item in placements]
        if len(set(addresses)) != len(addresses):
            raise ValueError("hardware.layout contains duplicate I2C addresses")
        return placements

    @staticmethod
    def _parse_address(value: object) -> int:
        if isinstance(value, int):
            address = value
        elif isinstance(value, str):
            text = value.strip().lower()
            if len(text) == 4 and set(text) <= {"0", "1"}:
                address = 0x20 + int(text, 2)
            else:
                address = int(text, 0)
        else:
            raise ValueError(f"Unsupported I2C address: {value!r}")
        if not 0x20 <= address <= 0x2F:
            raise ValueError(f"OpenGrid I2C address must be 0x20..0x2F, got 0x{address:02X}")
        return address

    @classmethod
    def board_levels(cls, levels: np.ndarray, placement: BoardPlacement) -> np.ndarray:
        y0 = placement.row * cls.BOARD_SIZE
        x0 = placement.column * cls.BOARD_SIZE
        board = np.asarray(levels[y0 : y0 + cls.BOARD_SIZE, x0 : x0 + cls.BOARD_SIZE])
        if board.shape != (cls.BOARD_SIZE, cls.BOARD_SIZE):
            raise ValueError(f"Incomplete board region at row={placement.row}, column={placement.column}")
        if placement.rotation:
            # np.rot90 is counter-clockwise; installation rotation is expressed clockwise.
            board = np.rot90(board, k=-(placement.rotation // 90))
        return np.clip(board, 0, 15).astype(np.uint8)

    @staticmethod
    def _pack_board(board: np.ndarray) -> bytes:
        # Official firmware index: keyIndex = x * 8 + y (column-major).
        flat = board.T.reshape(-1)
        return bytes(((flat[0::2] << 4) | flat[1::2]).tolist())

    def _write(self, address: int, data: bytes) -> None:
        self._bus.i2c_rdwr(self._i2c_msg.write(address, data))

    def _read_register(self, address: int, register: int, length: int = 1) -> bytes:
        return self._read_command(address, [register], length)

    def _read_command(self, address: int, command: list[int], length: int) -> bytes:
        request = self._i2c_msg.write(address, command)
        response = self._i2c_msg.read(address, length)
        self._bus.i2c_rdwr(request, response)
        return bytes(response)

    def _connect(self, address: int) -> None:
        protocol = self._read_register(address, self.REG_PROTOCOL_VERSION)[0]
        reported_address = self._read_register(address, self.REG_DEVICE_ADDRESS)[0]
        key_count_low = self._read_register(address, self.REG_KEY_COUNT_LOW)[0]
        key_count_high = self._read_register(address, self.REG_KEY_COUNT_HIGH)[0]
        key_count = key_count_low | (key_count_high << 8)
        if protocol != self.PROTOCOL_VERSION:
            raise RuntimeError(f"0x{address:02X} protocol is 0x{protocol:02X}, expected 0x02")
        if reported_address != address:
            raise RuntimeError(
                f"0x{address:02X} reports address 0x{reported_address:02X}; check address links"
            )
        if key_count < self.BOARD_PIXELS:
            raise RuntimeError(f"0x{address:02X} reports only {key_count} LEDs")
        self._online.add(address)
        self._last_frames.pop(address, None)
        self._key_states[address].fill(False)

    def _read_keys(self, address: int) -> np.ndarray:
        states = np.zeros(self.BOARD_PIXELS, dtype=np.bool_)
        for start in range(0, self.BOARD_PIXELS, 32):
            count = min(32, self.BOARD_PIXELS - start)
            data = self._read_command(
                address, [self.REG_KEY_READ_BLOCK, start, count], count
            )
            states[start : start + count] = np.frombuffer(data, dtype=np.uint8) != 0
        return states

    @classmethod
    def key_to_global(cls, placement: BoardPlacement, key_index: int) -> tuple[int, int]:
        if not 0 <= key_index < cls.BOARD_PIXELS:
            raise ValueError(f"Key index must be 0..63, got {key_index}")
        local = np.zeros((cls.BOARD_SIZE, cls.BOARD_SIZE), dtype=np.uint8)
        local_y = key_index % cls.BOARD_SIZE
        local_x = key_index // cls.BOARD_SIZE
        local[local_y, local_x] = 1
        logical = np.rot90(local, k=placement.rotation // 90)
        logical_y, logical_x = (int(value) for value in np.argwhere(logical)[0])
        return (
            placement.column * cls.BOARD_SIZE + logical_x,
            placement.row * cls.BOARD_SIZE + logical_y,
        )

    def _poll_keys(self, now: float, failures: list[str]) -> None:
        count = len(self._placements)
        for offset in range(self._key_boards_per_frame):
            placement = self._placements[(self._key_poll_cursor + offset) % count]
            address = placement.address
            if address not in self._online:
                continue
            try:
                current = self._read_keys(address)
                previous = self._key_states[address]
                for key_index in np.flatnonzero(current & ~previous):
                    key = (address, int(key_index))
                    if now - self._last_key_trigger.get(key, -1e9) < self._key_cooldown:
                        continue
                    x, y = self.key_to_global(placement, int(key_index))
                    self._ripple.trigger(x, y, now)
                    self._last_key_trigger[key] = now
                self._key_states[address] = current
            except OSError as exc:
                self._online.discard(address)
                self._last_frames.pop(address, None)
                self._retry_after[address] = now + self._retry_seconds
                failures.append(f"0x{address:02X} key read ({exc})")
        self._key_poll_cursor = (self._key_poll_cursor + self._key_boards_per_frame) % count

    def _send_board(self, address: int, packed: bytes) -> None:
        # Keep each Linux I2C write at 32 bytes or fewer, matching the official
        # library's conservative packed-block fallback.
        first_count = self.MAX_PACKED_BLOCK
        first_bytes = (first_count + 1) // 2
        self._write(
            address,
            bytes((self.REG_LED_SET_LEVEL_BLOCK_PACKED, 0, first_count))
            + packed[:first_bytes],
        )
        remaining = self.BOARD_PIXELS - first_count
        self._write(
            address,
            bytes((self.REG_LED_SET_LEVEL_BLOCK_PACKED, first_count, remaining))
            + packed[first_bytes:],
        )
        self._write(address, bytes((self.REG_LED_SHOW,)))

    def send(self, levels: np.ndarray) -> np.ndarray:
        source = np.asarray(levels)
        if source.ndim != 2 or source.shape != self._expected_shape:
            got = "x".join(str(value) for value in reversed(source.shape))
            raise ValueError(
                f"I2C layout expects {self._expected_shape[1]}x{self._expected_shape[0]} levels, "
                f"got {got}"
            )

        now = time.monotonic()
        failures: list[str] = []
        with self._lock:
            for placement in self._placements:
                address = placement.address
                if address in self._online or now < self._retry_after[address]:
                    continue
                try:
                    self._connect(address)
                except (OSError, RuntimeError) as exc:
                    self._retry_after[address] = now + self._retry_seconds
                    failures.append(f"0x{address:02X} ({exc})")

            self._poll_keys(now, failures)
            display = self._ripple.render(source, now)
            for placement in self._placements:
                address = placement.address
                try:
                    if address not in self._online:
                        failures.append(f"0x{address:02X}")
                        continue

                    packed = self._pack_board(self.board_levels(display, placement))
                    if self._last_frames.get(address) != packed:
                        self._send_board(address, packed)
                        self._last_frames[address] = packed
                except (OSError, RuntimeError) as exc:
                    self._online.discard(address)
                    self._last_frames.pop(address, None)
                    self._retry_after[address] = now + self._retry_seconds
                    failures.append(f"0x{address:02X} ({exc})")

        if failures:
            raise RuntimeError("OpenGrid boards unavailable: " + ", ".join(failures))
        return display

    def close(self) -> None:
        with self._lock:
            zero = bytes(self.BOARD_PIXELS // 2)
            for address in tuple(self._online):
                try:
                    self._send_board(address, zero)
                except OSError:
                    pass
            self._online.clear()
            self._bus.close()


def create_output(config: dict):
    if not bool(config.get("enabled", False)):
        return NullOutput()
    driver = str(config.get("driver", "i2c")).lower()
    if driver != "i2c":
        raise ValueError(f"Unsupported hardware driver: {driver}; use 'i2c'")
    return I2COpenGridOutput(config)
