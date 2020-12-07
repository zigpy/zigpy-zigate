from unittest import mock
from .async_mock import AsyncMock, MagicMock, patch, sentinel

import pytest
import zigpy.types as zigpy_types

import zigpy_zigate.config as config
import zigpy_zigate.types as t
import zigpy_zigate.zigbee.application

APP_CONFIG = zigpy_zigate.zigbee.application.ControllerApplication.SCHEMA(
    {
        config.CONF_DEVICE: {config.CONF_DEVICE_PATH: "/dev/null"},
        config.CONF_DATABASE: None,
    }
)
FAKE_FIRMWARE_VERSION = '3.1z'


@pytest.fixture
def app():
    a = zigpy_zigate.zigbee.application.ControllerApplication(APP_CONFIG)
    a.version = FAKE_FIRMWARE_VERSION
    a._api = MagicMock()
    return a


def test_zigpy_ieee(app):
    cluster = mock.MagicMock()
    cluster.cluster_id = 0x0000
    data = b"\x01\x02\x03\x04\x05\x06\x07\x08"

    zigate_ieee, _ = t.EUI64.deserialize(data)
    app._ieee = zigpy_types.EUI64(zigate_ieee)

    dst_addr = app.get_dst_address(cluster)
    assert dst_addr.serialize() == b"\x03" + data[::-1] + b"\x01"


def test_model_detection(app):
    device = zigpy_zigate.zigbee.application.ZiGateDevice(app, 0, 0)
    assert device.model == 'ZiGate USB-TTL {}'.format(FAKE_FIRMWARE_VERSION)


@pytest.mark.asyncio
async def test_form_network_success(app):
    app._api.set_channel = AsyncMock()
    app._api.reset = AsyncMock()
    async def mock_start_network():
        return [[0x00, 0x1234, 0x0123456789abcdef], 0]
    app._api.start_network = mock_start_network
    await app.form_network()
    assert app._nwk == 0x1234
    assert app._ieee == 0x0123456789abcdef
    assert app._api.reset.call_count == 0


@pytest.mark.asyncio
async def test_form_network_failed(app):
    app._api.set_channel = AsyncMock()
    app._api.reset = AsyncMock()
    async def mock_start_network():
        return [[0x06], 0]
    app._api.start_network = mock_start_network
    async def mock_get_network_state():
        return [[0xffff, 0x0123456789abcdef, 0x1234, 0, 0x11], 0]
    app._api.get_network_state = mock_get_network_state
    await app.form_network()
    assert app._nwk == 0
    assert app._ieee == 0
    assert app._api.reset.call_count == 1
