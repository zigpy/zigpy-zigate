import asyncio

import pytest
import serial
import serial_asyncio
from asynctest import CoroutineMock, mock

import zigpy_zigate.config as config
import zigpy_zigate.uart
from zigpy_zigate import api as zigate_api

DEVICE_CONFIG = config.SCHEMA_DEVICE({config.CONF_DEVICE_PATH: "/dev/null"})


@pytest.fixture
def api():
    api = zigate_api.ZiGate(DEVICE_CONFIG)
    api._uart = mock.MagicMock()
    return api


def test_set_application(api):
    api.set_application(mock.sentinel.app)
    assert api._app == mock.sentinel.app


@pytest.mark.asyncio
async def test_connect(monkeypatch):
    api = zigate_api.ZiGate(DEVICE_CONFIG)

    async def mock_conn(loop, protocol_factory, **kwargs):
        protocol = protocol_factory()
        loop.call_soon(protocol.connection_made, None)
        return None, protocol

    monkeypatch.setattr(serial_asyncio, "create_serial_connection", mock_conn)

    await api.connect()


def test_close(api):
    api._uart.close = mock.MagicMock()
    uart = api._uart
    api.close()
    assert uart.close.call_count == 1
    assert api._uart is None


@pytest.mark.asyncio
@mock.patch.object(zigpy_zigate.uart, "connect")
async def test_api_new(conn_mck):
    """Test new class method."""
    api = await zigate_api.ZiGate.new(DEVICE_CONFIG, mock.sentinel.application)
    assert isinstance(api, zigate_api.ZiGate)
    assert conn_mck.call_count == 1
    assert conn_mck.await_count == 1


@pytest.mark.asyncio
@mock.patch.object(zigate_api.ZiGate, "set_raw_mode", new_callable=CoroutineMock)
@mock.patch.object(zigpy_zigate.uart, "connect")
async def test_probe_success(mock_connect, mock_raw_mode):
    """Test device probing."""

    res = await zigate_api.ZiGate.probe(DEVICE_CONFIG)
    assert res is True
    assert mock_connect.call_count == 1
    assert mock_connect.await_count == 1
    assert mock_connect.call_args[0][0] == DEVICE_CONFIG
    assert mock_raw_mode.call_count == 1
    assert mock_connect.return_value.close.call_count == 1


@pytest.mark.asyncio
@mock.patch.object(zigate_api.ZiGate, "set_raw_mode", side_effect=asyncio.TimeoutError)
@mock.patch.object(zigpy_zigate.uart, "connect")
@pytest.mark.parametrize(
    "exception",
    (asyncio.TimeoutError, serial.SerialException, zigate_api.NoResponseError),
)
async def test_probe_fail(mock_connect, mock_raw_mode, exception):
    """Test device probing fails."""

    mock_raw_mode.side_effect = exception
    mock_connect.reset_mock()
    mock_raw_mode.reset_mock()
    res = await zigate_api.ZiGate.probe(DEVICE_CONFIG)
    assert res is False
    assert mock_connect.call_count == 1
    assert mock_connect.await_count == 1
    assert mock_connect.call_args[0][0] == DEVICE_CONFIG
    assert mock_raw_mode.call_count == 1
    assert mock_connect.return_value.close.call_count == 1
