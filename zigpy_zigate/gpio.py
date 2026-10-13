"""Minimal Raspberry Pi GPIO access through `/dev/gpiomem`."""

import mmap
import os


class GPIOMemory:
    # Register byte offsets, from the BCM2835 ARM Peripherals datasheet, section 6.1
    GPFSEL0 = 0x00  # function select: 3 bits per pin, 10 pins per register
    GPSET0 = 0x1C  # write 1 to drive a pin high: 1 bit per pin, 32 pins per register
    GPCLR0 = 0x28  # write 1 to drive a pin low: 1 bit per pin, 32 pins per register

    FUNCTION_WIDTH = 3
    FUNCTION_MASK = 0b111
    FUNCTION_OUTPUT = 0b001

    def __enter__(self) -> "GPIOMemory":
        fd = os.open("/dev/gpiomem", os.O_RDWR | os.O_SYNC)
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
