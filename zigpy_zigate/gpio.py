"""Minimal Raspberry Pi GPIO access through `/dev/gpiomem`."""

import mmap
import os

GPIOMEM = "/dev/gpiomem"
DEVICE_TREE_REVISION = "/proc/device-tree/system/linux,revision"
CPUINFO = "/proc/cpuinfo"

# SoC field (bits 12-15) of new-style board revision codes
SOC_NAMES = {0: "BCM2835", 1: "BCM2836", 2: "BCM2837", 3: "BCM2711", 4: "BCM2712"}

# Raspberry Pi 1-4, Zero and CM1-4: their GPIO block has the BCM2835 register layout.
# The Pi 5 (BCM2712) has its header GPIOs on the RP1 chip, with different registers.
SUPPORTED_SOCS = {0, 1, 2, 3}


class GPIOError(RuntimeError):
    """The PiZiGate's GPIO pins cannot be driven."""


def read_board_revision() -> int | None:
    """Read the Raspberry Pi board revision code, from the same places as gpiozero."""
    try:
        with open(DEVICE_TREE_REVISION, "rb") as f:
            data = f.read()
        if len(data) == 4:
            return int.from_bytes(data, "big")
    except OSError:
        pass

    try:
        with open(CPUINFO) as f:
            for line in f:
                if line.startswith("Revision"):
                    return int(line.partition(":")[2], 16)
    except (OSError, ValueError):
        pass

    return None


def check_supported_board() -> None:
    """Raise `GPIOError` unless this is a Raspberry Pi with BCM2835-style GPIO."""
    revision = read_board_revision()
    if revision is None:
        raise GPIOError(
            "Not a Raspberry Pi: no board revision code in"
            f" {DEVICE_TREE_REVISION} or {CPUINFO}"
        )

    if revision & 0x800000:
        # New-style revision code
        soc = (revision >> 12) & 0xF
    elif 0x0002 <= revision & 0xFFFFFF <= 0x0015:
        # Old-style revision codes are all Raspberry Pi 1 models
        soc = 0
    else:
        raise GPIOError(f"Unknown Raspberry Pi board revision code {revision:#x}")

    if soc not in SUPPORTED_SOCS:
        raise GPIOError(
            f"Unsupported Raspberry Pi SoC {SOC_NAMES.get(soc, soc)} (board revision"
            f" {revision:#x}): PiZiGate GPIO control supports the Raspberry Pi 1-4"
        )


class GPIOMemory:
    # Register byte offsets, from the BCM2835 ARM Peripherals datasheet, section 6.1
    GPFSEL0 = 0x00  # function select: 3 bits per pin, 10 pins per register
    GPSET0 = 0x1C  # write 1 to drive a pin high: 1 bit per pin, 32 pins per register
    GPCLR0 = 0x28  # write 1 to drive a pin low: 1 bit per pin, 32 pins per register

    FUNCTION_WIDTH = 3
    FUNCTION_MASK = 0b111
    FUNCTION_OUTPUT = 0b001

    def __enter__(self) -> "GPIOMemory":
        check_supported_board()

        try:
            fd = os.open(GPIOMEM, os.O_RDWR | os.O_SYNC)
        except OSError as exc:
            raise GPIOError(f"Cannot open {GPIOMEM}: {exc.strerror}") from exc

        try:
            self._mmap = mmap.mmap(fd, 4096)
        finally:
            os.close(fd)
        self._regs = memoryview(self._mmap).cast("I")  # native 32-bit register access
        return self

    def __exit__(self, *exc_info) -> None:
        self._regs.release()
        self._mmap.close()

    def _index(self, base: int, register: int) -> int:
        return base // 4 + register

    def set_output(self, pin: int) -> None:
        register, field = divmod(pin, 10)
        shift = field * self.FUNCTION_WIDTH
        index = self._index(self.GPFSEL0, register)

        # Other pins share this register, so only replace this pin's field
        value = self._regs[index]
        value &= ~(self.FUNCTION_MASK << shift)
        value |= self.FUNCTION_OUTPUT << shift
        self._regs[index] = value

    def write(self, pin: int, value: bool) -> None:
        register, bit = divmod(pin, 32)
        base = self.GPSET0 if value else self.GPCLR0

        # Zero bits are ignored, so this only affects `pin`
        self._regs[self._index(base, register)] = 1 << bit
