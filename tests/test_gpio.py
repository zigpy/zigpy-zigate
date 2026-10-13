import pytest

from zigpy_zigate import gpio


@pytest.fixture
def board(tmp_path, monkeypatch):
    """Point the board revision sources at temporary files, both missing initially."""
    device_tree = tmp_path / "linux,revision"
    cpuinfo = tmp_path / "cpuinfo"
    monkeypatch.setattr(gpio, "DEVICE_TREE_REVISION", str(device_tree))
    monkeypatch.setattr(gpio, "CPUINFO", str(cpuinfo))
    return device_tree, cpuinfo


@pytest.mark.parametrize(
    "revision",
    [
        0x0002,  # Pi 1 B, old-style
        0x0015,  # Pi 1 A+, old-style
        0x1000010,  # Pi 1 B+, old-style with the warranty bit set
        0x900093,  # Zero 1.3 (BCM2835)
        0xA21041,  # Pi 2 B (BCM2836)
        0xA02082,  # Pi 3 B (BCM2837)
        0x902120,  # Zero 2 W (BCM2837)
        0xB03114,  # Pi 4 B (BCM2711)
        0xA03140,  # CM4 (BCM2711)
        0x2C03114,  # Pi 4 B with the warranty bit set
    ],
)
def test_supported_board_device_tree(board, revision):
    device_tree, _ = board
    device_tree.write_bytes(revision.to_bytes(4, "big"))

    assert gpio.read_board_revision() == revision
    gpio.check_supported_board()


def test_supported_board_cpuinfo(board):
    _, cpuinfo = board
    cpuinfo.write_text(
        "processor\t: 0\nHardware\t: BCM2835\nRevision\t: c03114\n"
        "Serial\t\t: 100000001234abcd\nModel\t\t: Raspberry Pi 4 Model B Rev 1.4\n"
    )

    assert gpio.read_board_revision() == 0xC03114
    gpio.check_supported_board()


def test_device_tree_preferred_over_cpuinfo(board):
    device_tree, cpuinfo = board
    device_tree.write_bytes((0xB03114).to_bytes(4, "big"))
    cpuinfo.write_text("Revision\t: d04170\n")

    assert gpio.read_board_revision() == 0xB03114


def test_truncated_device_tree_falls_back_to_cpuinfo(board):
    device_tree, cpuinfo = board
    device_tree.write_bytes(b"\x00\xb0")
    cpuinfo.write_text("Revision\t: b03114\n")

    assert gpio.read_board_revision() == 0xB03114


@pytest.mark.parametrize("revision", [0xC04170, 0xD04170])  # Pi 5 4GB, 8GB
def test_pi5_unsupported(board, revision):
    device_tree, _ = board
    device_tree.write_bytes(revision.to_bytes(4, "big"))

    with pytest.raises(gpio.GPIOError, match="BCM2712"):
        gpio.check_supported_board()


def test_unknown_soc(board):
    device_tree, _ = board
    device_tree.write_bytes((0xA05170).to_bytes(4, "big"))

    with pytest.raises(gpio.GPIOError, match="SoC 5 "):
        gpio.check_supported_board()


@pytest.mark.parametrize("revision", [0x0000, 0x0001, 0x0016])
def test_unknown_old_style_revision(board, revision):
    _, cpuinfo = board
    cpuinfo.write_text(f"Revision\t: {revision:04x}\n")

    with pytest.raises(gpio.GPIOError, match="Unknown Raspberry Pi board revision"):
        gpio.check_supported_board()


@pytest.mark.parametrize(
    "cpuinfo_text",
    [
        None,  # no /proc/cpuinfo
        "processor\t: 0\nBogoMIPS\t: 48.00\n",  # e.g. x86 or a mainline arm64 kernel
        "Revision\t: not-hex\n",
    ],
)
def test_not_a_raspberry_pi(board, cpuinfo_text):
    _, cpuinfo = board
    if cpuinfo_text is not None:
        cpuinfo.write_text(cpuinfo_text)

    assert gpio.read_board_revision() is None
    with pytest.raises(gpio.GPIOError, match="Not a Raspberry Pi"):
        gpio.check_supported_board()


def test_board_checked_before_opening_gpiomem(board, tmp_path, monkeypatch):
    gpiomem = tmp_path / "gpiomem"
    gpiomem.write_bytes(bytes(4096))
    monkeypatch.setattr(gpio, "GPIOMEM", str(gpiomem))

    with pytest.raises(gpio.GPIOError, match="Not a Raspberry Pi"):
        with gpio.GPIOMemory():
            pass


def test_missing_gpiomem(board, tmp_path, monkeypatch):
    device_tree, _ = board
    device_tree.write_bytes((0xB03114).to_bytes(4, "big"))
    monkeypatch.setattr(gpio, "GPIOMEM", str(tmp_path / "gpiomem"))

    with pytest.raises(gpio.GPIOError, match="Cannot open .*gpiomem"):
        with gpio.GPIOMemory():
            pass
