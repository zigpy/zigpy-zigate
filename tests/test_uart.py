from unittest.mock import AsyncMock, MagicMock

import gpiozero
import pytest
import serial.tools.list_ports
import serial_asyncio
import zigpy.config

from zigpy_zigate import common, uart


@pytest.fixture
def gw():
    gw = uart.Gateway(MagicMock())
    gw._transport = MagicMock()
    return gw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "port",
    ("/dev/null", "pizigate:/dev/ttyAMA0"),
)
async def test_connect(port, monkeypatch):
    api = MagicMock()

    async def mock_conn(loop, protocol_factory, url, **kwargs):
        protocol = protocol_factory()
        loop.call_soon(protocol.connection_made, None)
        assert url.startswith("/") is True
        return None, protocol

    monkeypatch.setattr(serial_asyncio, "create_serial_connection", mock_conn)
    monkeypatch.setattr(common, "set_pizigate_running_mode", AsyncMock())
    DEVICE_CONFIG = zigpy.config.SCHEMA_DEVICE({zigpy.config.CONF_DEVICE_PATH: port})

    await uart.connect(DEVICE_CONFIG, api)


def test_send(gw):
    frame = b"\x01\x02\x150\x02\x10\x02\x114\x02\x10\x03"
    data = b"\x00"
    gw.send(0x0530, data)
    assert gw._transport.write.call_count == 1
    assert gw._transport.write.call_args[0][0] == frame


def test_close(gw):
    gw.close()
    assert gw._transport.close.call_count == 1


def test_data_received_chunk_frame(gw):
    data = b"\x01\x80\x10\x02\x10\x02\x15\xaa\x02\x10\x02\x1f?\xf0\xff\x03"
    gw.data_received(data[:-4])
    assert gw._api.data_received.call_count == 0
    gw.data_received(data[-4:])
    assert gw._api.data_received.call_count == 1
    assert gw._api.data_received.call_args[0] == (0x8010, b"\x00\x0f?\xf0", 255)


def test_data_received_full_frame(gw):
    data = b"\x01\x80\x10\x02\x10\x02\x15\xaa\x02\x10\x02\x1f?\xf0\xff\x03"
    gw.data_received(data)
    assert gw._api.data_received.call_count == 1
    assert gw._api.data_received.call_args[0] == (0x8010, b"\x00\x0f?\xf0", 255)


def test_data_received_incomplete_frame(gw):
    data = b"~\x00\x00"
    gw.data_received(data)
    assert gw._api.data_received.call_count == 0


def test_data_received_runt_frame(gw):
    data = b"\x02\x44\xC0"
    gw.data_received(data)
    assert gw._api.data_received.call_count == 0


def test_data_received_extra(gw):
    data = b"\x01\x80\x10\x02\x10\x02\x15\xaa\x02\x10\x02\x1f?\xf0\xff\x03\x00"
    gw.data_received(data)
    assert gw._api.data_received.call_count == 1
    assert gw._api.data_received.call_args[0] == (0x8010, b"\x00\x0f?\xf0", 255)
    assert gw._buffer == b"\x00"


def test_data_received_wrong_checksum(gw):
    data = b"\x01\x80\x10\x02\x10\x02\x15\xab\x02\x10\x02\x1f?\xf0\xff\x03"
    gw.data_received(data)
    assert gw._api.data_received.call_count == 0


def test_unescape(gw):
    data = b"\x80\x10\x02\x10\x02\x15\xaa\x02\x10\x02\x1f?\xf0\xff"
    data_unescaped = b"\x80\x10\x00\x05\xaa\x00\x0f?\xf0\xff"
    r = gw._unescape(data)
    assert r == data_unescaped


def test_escape(gw):
    data = b"\x80\x10\x00\x05\xaa\x00\x0f?\xf0\xff"
    data_escaped = b"\x80\x10\x02\x10\x02\x15\xaa\x02\x10\x02\x1f?\xf0\xff"
    r = gw._escape(data)
    assert r == data_escaped


def test_length(gw):
    data = b"\x80\x10\x00\x05\xaa\x00\x0f?\xf0\xff"
    length = 5
    r = gw._length(data)
    assert r == length


def test_checksum(gw):
    data = b"\x00\x0f?\xf0"
    checksum = 0xAA
    r = gw._checksum(b"\x80\x10", 5, 0xFF, data)
    assert r == checksum


@pytest.mark.parametrize(
    "port",
    ("/dev/ttyAMA0", "/dev/serial0", "pizigate:/dev/ttyAMA0"),
)
def test_is_pizigate(port):
    r = common.is_pizigate(port)
    assert r is True


def test_is_not_pizigate():
    port = "/dev/ttyUSB1"
    r = common.is_pizigate(port)
    assert r is False


def test_is_zigatedin(monkeypatch):
    def mock_grep(*args, **kwargs):
        device = MagicMock()
        device.description = "ZiGate"
        device.manufacturer = "FTDI"
        return iter([device])

    monkeypatch.setattr(serial.tools.list_ports, "grep", mock_grep)
    port = "/dev/ttyUSB1"
    r = common.is_zigate_din(port)
    assert r is True


@pytest.mark.parametrize(
    "port",
    ("/dev/ttyUSB1", "/dev/ttyAMA0", "/dev/serial0"),
)
def test_is_not_zigatedin(port, monkeypatch):
    def mock_grep(*args, **kwargs):
        device = MagicMock()
        device.description = "Other"
        device.manufacturer = "FTDI"
        return iter([device])

    monkeypatch.setattr(serial.tools.list_ports, "grep", mock_grep)
    r = common.is_zigate_din(port)
    assert r is False


def test_is_zigate_wifi():
    port = "socket://192.168.1.10:9999"
    r = common.is_zigate_wifi(port)
    assert r is True


def test_is_not_zigate_wifi():
    port = "/dev/ttyUSB1"
    r = common.is_zigate_wifi(port)
    assert r is False


def test_startup_gpio_toggling(monkeypatch):
    monkeypatch.setattr(gpiozero.Device, "_default_pin_factory", MagicMock())

    common.set_pizigate_running_mode()
    common.set_pizigate_flashing_mode()
