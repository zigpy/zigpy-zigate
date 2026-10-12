"""Minimal GPIO output support using the Linux GPIO character device.

This only implements what the PiZiGate needs: drive a header GPIO pin as an output and
keep driving it. It talks to `/dev/gpiochipN` with the GPIO v2 uAPI (Linux 5.10+) and
has no third-party dependencies.

Line requests are kept open for the lifetime of the process: closing one hands the line
back to the kernel, which may stop driving the pin.
"""

from __future__ import annotations

import errno
import fcntl
import glob
import logging
import os
import re
import struct
import threading

LOGGER = logging.getLogger(__name__)

CONSUMER = b"zigpy-zigate"

# GPIO chips that expose the Raspberry Pi header with line offset == BCM GPIO number.
# Only used if no line carries the expected "GPIO<n>" name.
PI_HEADER_CHIP_LABELS = frozenset(
    {
        "pinctrl-bcm2835",  # Pi 1-3, Zero
        "pinctrl-bcm2711",  # Pi 4
        "pinctrl-rp1",  # Pi 5
    }
)

GPIO_V2_LINE_FLAG_OUTPUT = 1 << 3
GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES = 2


def _ioc(direction: int, nr: int, size: int) -> int:
    """`_IOC()` from `asm-generic/ioctl.h`, used by ARM and x86."""
    return (direction << 30) | (size << 16) | (0xB4 << 8) | nr


_IOC_WRITE = 1
_IOC_READ = 2

# struct gpiochip_info: name[32], label[32], lines
CHIP_INFO = struct.Struct("=32s32sI")
# struct gpio_v2_line_info: name[32], consumer[32], offset, num_attrs, flags,
# attrs[10] (16 bytes each), padding[4]
LINE_INFO = struct.Struct("=32s32sIIQ160x16x")
# struct gpio_v2_line_request for a single line with a single config attribute:
# offsets[64], consumer[32],
# config { flags, num_attrs, padding[5], attrs[10] { id, padding, value, mask } },
# num_lines, event_buffer_size, padding[5], fd
LINE_REQUEST = struct.Struct("=I252x32sQI20xI4xQQ216xII20xi")
# struct gpio_v2_line_values: bits, mask
LINE_VALUES = struct.Struct("=QQ")

GPIO_GET_CHIPINFO_IOCTL = _ioc(_IOC_READ, 0x01, CHIP_INFO.size)
GPIO_V2_GET_LINEINFO_IOCTL = _ioc(_IOC_READ | _IOC_WRITE, 0x05, LINE_INFO.size)
GPIO_V2_GET_LINE_IOCTL = _ioc(_IOC_READ | _IOC_WRITE, 0x07, LINE_REQUEST.size)
GPIO_V2_LINE_SET_VALUES_IOCTL = _ioc(_IOC_READ | _IOC_WRITE, 0x0F, LINE_VALUES.size)


class GPIOError(RuntimeError):
    """A GPIO line could not be found or driven."""


# BCM GPIO number -> file descriptor of the line request, held until the process exits
_requests: dict[int, int] = {}
_lock = threading.Lock()


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def _chip_paths() -> list[str]:
    def chip_number(path: str) -> int:
        return int(re.sub(r"\D", "", os.path.basename(path)) or 0)

    return sorted(glob.glob("/dev/gpiochip[0-9]*"), key=chip_number)


def _find_line(pin: int) -> tuple[str, int]:
    """Find the chip and line offset of header GPIO `pin` (BCM numbering)."""
    name = f"GPIO{pin}"
    chips = _chip_paths()
    if not chips:
        raise GPIOError(
            "No GPIO character devices (/dev/gpiochip*) found, cannot control the"
            " PiZiGate GPIO pins"
        )

    fallback = None
    errors = []

    for path in chips:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        except OSError as exc:
            errors.append(f"{path}: {exc.strerror}")
            continue

        try:
            buf = bytearray(CHIP_INFO.size)
            fcntl.ioctl(fd, GPIO_GET_CHIPINFO_IOCTL, buf, True)
            _, label, num_lines = CHIP_INFO.unpack(buf)

            for offset in range(num_lines):
                buf = bytearray(LINE_INFO.pack(b"", b"", offset, 0, 0))
                fcntl.ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, buf, True)
                if _cstr(LINE_INFO.unpack(buf)[0]) == name:
                    return path, offset

            if fallback is None and _cstr(label) in PI_HEADER_CHIP_LABELS:
                if pin < num_lines:
                    fallback = (path, pin)
        except OSError as exc:
            # kernels without the v2 uAPI reject its ioctls with EINVAL
            if exc.errno in (errno.EINVAL, errno.ENOTTY):
                errors.append(f"{path}: GPIO v2 uAPI not supported (needs Linux 5.10+)")
            else:
                errors.append(f"{path}: {exc.strerror}")
        finally:
            os.close(fd)

    if fallback is not None:
        LOGGER.debug("No GPIO line named %s, using %s line %d", name, *fallback)
        return fallback

    msg = f"No GPIO line named {name} found on {', '.join(chips)}"
    if errors:
        msg += f" (could not read {'; '.join(errors)})"
    raise GPIOError(msg)


def _request_output(path: str, offset: int, value: bool) -> int:
    """Request a line as an output, driving `value` right away."""
    request = bytearray(
        LINE_REQUEST.pack(
            offset,
            CONSUMER,
            GPIO_V2_LINE_FLAG_OUTPUT,  # config.flags
            1,  # config.num_attrs
            GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES,  # config.attrs[0].attr.id
            int(value),  # config.attrs[0].attr.values
            1,  # config.attrs[0].mask
            1,  # num_lines
            0,  # event_buffer_size
            0,  # fd
        )
    )

    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, GPIO_V2_GET_LINE_IOCTL, request, True)
    finally:
        # the line request has its own file descriptor and outlives the chip's
        os.close(fd)

    return LINE_REQUEST.unpack(request)[-1]


def set_value(pin: int, value: bool) -> None:
    """Drive header GPIO `pin` (BCM numbering) to `value` and keep driving it.

    The line is requested on first use, with `value` as its initial output value, so
    no other level is ever driven onto the pin.
    """
    with _lock:
        fd = _requests.get(pin)

        if fd is None:
            path, offset = _find_line(pin)
            try:
                _requests[pin] = _request_output(path, offset, value)
            except OSError as exc:
                raise GPIOError(
                    f"Could not request GPIO{pin} ({path} line {offset}) as an"
                    f" output: {exc.strerror}"
                ) from exc

            LOGGER.debug(
                "Requested GPIO%d (%s line %d) as an output", pin, path, offset
            )
            return

        try:
            fcntl.ioctl(
                fd, GPIO_V2_LINE_SET_VALUES_IOCTL, LINE_VALUES.pack(int(value), 1)
            )
        except OSError as exc:
            raise GPIOError(f"Could not set GPIO{pin}: {exc.strerror}") from exc
