import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, sentinel

import pytest
import serial_asyncio
import zigpy.config as config

from zigpy_zigate import api as zigate_api
import zigpy_zigate.uart

DEVICE_CONFIG = config.SCHEMA_DEVICE({config.CONF_DEVICE_PATH: "/dev/null"})


@pytest.fixture
def api():
    api = zigate_api.ZiGate(DEVICE_CONFIG)
    api._uart = MagicMock()
    return api


def test_set_application(api):
    api.set_application(sentinel.app)
    assert api._app == sentinel.app


@pytest.mark.asyncio
async def test_connect(monkeypatch):
    api = zigate_api.ZiGate(DEVICE_CONFIG)

    async def mock_conn(loop, protocol_factory, **kwargs):
        protocol = protocol_factory()
        loop.call_soon(protocol.connection_made, None)
        return None, protocol

    monkeypatch.setattr(serial_asyncio, "create_serial_connection", mock_conn)

    await api.connect()


@pytest.mark.asyncio
async def test_disconnect(api):
    uart = api._uart
    uart.disconnect = AsyncMock()

    await api.disconnect()
    assert uart.disconnect.call_count == 1
    assert api._uart is None


@pytest.mark.asyncio
@patch.object(zigpy_zigate.uart, "connect")
async def test_api_new(conn_mck):
    """Test new class method."""
    api = await zigate_api.ZiGate.new(DEVICE_CONFIG, sentinel.application)
    assert isinstance(api, zigate_api.ZiGate)
    assert conn_mck.call_count == 1
    assert conn_mck.await_count == 1


@pytest.mark.asyncio
@patch.object(asyncio, "wait", return_value=([], []))
async def test_api_command(mock_command, api):
    """Test command method."""
    try:
        await api.set_raw_mode()
    except zigate_api.NoResponseError:
        pass
    assert mock_command.call_count == 3
