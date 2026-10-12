import errno
import os
import struct

import pytest

from zigpy_zigate import gpio


class FakeChip:
    def __init__(self, label, line_names):
        self.label = label
        self.line_names = line_names


class FakeKernel:
    """Just enough of the GPIO character device uAPI v2 to drive `gpio`."""

    def __init__(self, chips):
        self.chips = chips  # path -> FakeChip
        self.fds = {}  # open fd -> chip path or ("line", request)
        self.requests = []
        self.set_values = []
        self.closed = []
        self._next_fd = 100

    def _new_fd(self, target):
        fd = self._next_fd
        self._next_fd += 1
        self.fds[fd] = target
        return fd

    def glob(self, pattern):
        assert pattern == "/dev/gpiochip[0-9]*"
        return list(self.chips)

    def open(self, path, flags):
        assert flags == os.O_RDWR | os.O_CLOEXEC
        if path not in self.chips:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
        return self._new_fd(path)

    def close(self, fd):
        self.closed.append(fd)
        del self.fds[fd]

    def ioctl(self, fd, request, arg, mutate_flag=True):
        target = self.fds[fd]

        if request == gpio.GPIO_GET_CHIPINFO_IOCTL:
            chip = self.chips[target]
            arg[:] = gpio.CHIP_INFO.pack(
                os.path.basename(target).encode(),
                chip.label.encode(),
                len(chip.line_names),
            )
        elif request == gpio.GPIO_V2_GET_LINEINFO_IOCTL:
            # the kernel rejects non-zero padding and invalid offsets with EINVAL
            assert not any(arg[240:256])
            offset = gpio.LINE_INFO.unpack(arg)[2]
            name = self.chips[target].line_names[offset]
            arg[:] = gpio.LINE_INFO.pack(name.encode(), b"", offset, 0, 0)
        elif request == gpio.GPIO_V2_GET_LINE_IOCTL:
            fields = gpio.LINE_REQUEST.unpack(arg)
            # config.padding and the request's padding must be zero
            assert not any(arg[300:320]) and not any(arg[568:588])
            assert 1 <= fields[7] <= 64  # num_lines
            assert fields[3] <= 10  # config.num_attrs
            assert fields[0] < len(self.chips[target].line_names)
            self.requests.append((target, fields))
            line_fd = self._new_fd(("line", len(self.requests) - 1))
            arg[:] = gpio.LINE_REQUEST.pack(*fields[:-1], line_fd)
        elif request == gpio.GPIO_V2_LINE_SET_VALUES_IOCTL:
            self.set_values.append((target[1], gpio.LINE_VALUES.unpack(arg)))
        else:
            raise OSError(errno.ENOTTY, os.strerror(errno.ENOTTY))

        return 0


def pi_line_names(count):
    return [f"GPIO{n}" for n in range(count)]


@pytest.fixture
def kernel(monkeypatch):
    def install(chips):
        k = FakeKernel(chips)
        monkeypatch.setattr(gpio.glob, "glob", k.glob)
        monkeypatch.setattr(gpio.os, "open", k.open)
        monkeypatch.setattr(gpio.os, "close", k.close)
        monkeypatch.setattr(gpio.fcntl, "ioctl", k.ioctl)
        return k

    monkeypatch.setattr(gpio, "_requests", {})
    return install


def test_uapi_layout():
    # Sizes and ioctl numbers of <linux/gpio.h>, printed by a C program on x86-64.
    # The v2 uAPI structs are padded to have the same layout on every architecture.
    assert gpio.CHIP_INFO.size == 68
    assert gpio.LINE_INFO.size == 256
    assert gpio.LINE_REQUEST.size == 592
    assert gpio.LINE_VALUES.size == 16
    assert gpio.GPIO_GET_CHIPINFO_IOCTL == 0x8044B401
    assert gpio.GPIO_V2_GET_LINEINFO_IOCTL == 0xC100B405
    assert gpio.GPIO_V2_GET_LINE_IOCTL == 0xC250B407
    assert gpio.GPIO_V2_LINE_SET_VALUES_IOCTL == 0xC010B40F


def test_line_request_layout():
    raw = gpio.LINE_REQUEST.pack(17, b"zigpy-zigate", 8, 1, 2, 1, 1, 1, 0, 0)

    # offsets[0] at 0, consumer at 256, config at 288, num_lines at 560, fd at 588
    assert struct.unpack_from("=I", raw, 0) == (17,)
    assert raw[256:288].rstrip(b"\0") == b"zigpy-zigate"
    # config: flags, num_attrs, then attrs[0] = {id, padding, values, mask} at +32
    assert struct.unpack_from("=QI", raw, 288) == (8, 1)
    assert struct.unpack_from("=I4xQQ", raw, 288 + 32) == (2, 1, 1)
    assert struct.unpack_from("=I", raw, 560) == (1,)
    assert struct.unpack_from("=i", raw, 588) == (0,)
    # everything else (the other offsets and attributes, padding) is zero
    assert raw.count(0) == len(raw) - len(b"zigpy-zigate") - 7


def test_set_value_requests_line_once(kernel):
    k = kernel(
        {
            "/dev/gpiochip0": FakeChip("pinctrl-bcm2711", pi_line_names(58)),
            "/dev/gpiochip1": FakeChip("raspberrypi-exp-gpio", ["BT_ON"] * 8),
        }
    )

    gpio.set_value(27, True)
    gpio.set_value(17, False)
    gpio.set_value(17, True)
    gpio.set_value(27, False)

    # each line is requested once, as an output, with the first value as its
    # initial output value
    assert [(path, f[0], f[1].rstrip(b"\0")) for path, f in k.requests] == [
        ("/dev/gpiochip0", 27, gpio.CONSUMER),
        ("/dev/gpiochip0", 17, gpio.CONSUMER),
    ]
    for _, fields in k.requests:
        assert fields[2] == gpio.GPIO_V2_LINE_FLAG_OUTPUT
        assert fields[3:5] == (1, gpio.GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES)
        assert fields[6:9] == (1, 1, 0)  # mask, num_lines, event_buffer_size
    assert [f[5] for _, f in k.requests] == [1, 0]

    # later writes go to the held requests
    assert k.set_values == [(1, (1, 1)), (0, (0, 1))]

    # chip fds are closed, the line requests are kept open
    assert sorted(k.fds) == sorted(gpio._requests.values())
    assert all(target[0] == "line" for target in k.fds.values())


def test_find_line_by_name_on_any_chip(kernel):
    # Pi 5 on Raspberry Pi kernels 6.6+: the RP1 header chip is gpiochip0, the SoC's
    # own chips follow and carry no GPIO<n> names
    k = kernel(
        {
            "/dev/gpiochip10": FakeChip("gpio-brcmstb@107d508500", ["-"] * 32),
            "/dev/gpiochip0": FakeChip("pinctrl-rp1", pi_line_names(54)),
            "/dev/gpiochip2": FakeChip("other", ["GPIO17"]),
        }
    )

    assert gpio._find_line(17) == ("/dev/gpiochip0", 17)
    assert gpio._find_line(27) == ("/dev/gpiochip0", 27)
    assert not k.fds


def test_find_line_sorts_chips_numerically(kernel):
    kernel(
        {
            "/dev/gpiochip10": FakeChip("other", ["GPIO17"]),
            "/dev/gpiochip4": FakeChip("other", ["-", "GPIO17"]),
        }
    )

    assert gpio._find_line(17) == ("/dev/gpiochip4", 1)


def test_find_line_pi5_kernel_6_1(kernel):
    # Pi 5 on its launch kernel (6.1): the RP1 header chip is gpiochip4, after the
    # SoC's own chips, and its lines are named after the header pins ("PIN11" is
    # GPIO17), so only the chip label finds it
    rp1_names = [f"PIN{n}" for n in range(54)]
    kernel(
        {
            **{
                f"/dev/gpiochip{n}": FakeChip("gpio-brcmstb@107d508500", ["-"] * 32)
                for n in range(4)
            },
            "/dev/gpiochip4": FakeChip("pinctrl-rp1", rp1_names),
        }
    )

    assert gpio._find_line(17) == ("/dev/gpiochip4", 17)
    assert gpio._find_line(27) == ("/dev/gpiochip4", 27)


def test_find_line_by_chip_label(kernel):
    kernel(
        {
            "/dev/gpiochip0": FakeChip("other", ["-"] * 64),
            "/dev/gpiochip1": FakeChip("pinctrl-bcm2835", [""] * 54),
        }
    )

    assert gpio._find_line(17) == ("/dev/gpiochip1", 17)


def test_find_line_no_chips(kernel):
    kernel({})

    with pytest.raises(gpio.GPIOError, match="No GPIO character devices"):
        gpio.set_value(17, True)


def test_find_line_not_found(kernel, monkeypatch):
    k = kernel(
        {
            "/dev/gpiochip0": FakeChip("other", ["-"] * 64),
            "/dev/gpiochip1": FakeChip("other", ["-"] * 8),
        }
    )

    def open_(path, flags):
        if path == "/dev/gpiochip1":
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        return FakeKernel.open(k, path, flags)

    monkeypatch.setattr(gpio.os, "open", open_)

    with pytest.raises(gpio.GPIOError) as exc_info:
        gpio.set_value(17, True)

    assert str(exc_info.value) == (
        "No GPIO line named GPIO17 found on /dev/gpiochip0, /dev/gpiochip1"
        " (could not read /dev/gpiochip1: Permission denied)"
    )
    assert not gpio._requests


def test_request_fails(kernel, monkeypatch):
    k = kernel({"/dev/gpiochip0": FakeChip("pinctrl-bcm2711", pi_line_names(58))})
    ioctl = k.ioctl

    def busy_ioctl(fd, request, arg, mutate_flag=True):
        if request == gpio.GPIO_V2_GET_LINE_IOCTL:
            raise OSError(errno.EBUSY, os.strerror(errno.EBUSY))
        return ioctl(fd, request, arg, mutate_flag)

    monkeypatch.setattr(gpio.fcntl, "ioctl", busy_ioctl)

    with pytest.raises(gpio.GPIOError) as exc_info:
        gpio.set_value(17, True)

    assert str(exc_info.value) == (
        "Could not request GPIO17 (/dev/gpiochip0 line 17) as an output:"
        " Device or resource busy"
    )
    assert not gpio._requests
    assert not k.fds

    # a later call tries again
    monkeypatch.setattr(gpio.fcntl, "ioctl", ioctl)
    gpio.set_value(17, True)
    assert list(gpio._requests) == [17]


def test_set_value_fails(kernel, monkeypatch):
    kernel({"/dev/gpiochip0": FakeChip("pinctrl-bcm2711", pi_line_names(58))})
    gpio.set_value(17, True)

    def failing_ioctl(fd, request, arg, mutate_flag=True):
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(gpio.fcntl, "ioctl", failing_ioctl)

    with pytest.raises(gpio.GPIOError, match="Could not set GPIO17: Input/output"):
        gpio.set_value(17, False)


def test_find_line_old_kernel(kernel, monkeypatch):
    k = kernel({"/dev/gpiochip0": FakeChip("pinctrl-bcm2711", pi_line_names(58))})
    ioctl = k.ioctl

    def v1_only_ioctl(fd, request, arg, mutate_flag=True):
        if request == gpio.GPIO_V2_GET_LINEINFO_IOCTL:
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        return ioctl(fd, request, arg, mutate_flag)

    monkeypatch.setattr(gpio.fcntl, "ioctl", v1_only_ioctl)

    with pytest.raises(gpio.GPIOError, match=r"needs Linux 5\.10\+"):
        gpio.set_value(17, True)
    assert not k.fds
