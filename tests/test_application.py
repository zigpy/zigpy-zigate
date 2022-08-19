from unittest import mock
from .async_mock import AsyncMock, MagicMock, patch, sentinel

import pytest
import logging
import zigpy.types as zigpy_types
import zigpy.exceptions

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
    app.state.node_info.ieee = zigpy_types.EUI64(zigate_ieee)

    dst_addr = app.get_dst_address(cluster)
    assert dst_addr.serialize() == b"\x03" + data[::-1] + b"\x01"


def test_model_detection(app):
    device = zigpy_zigate.zigbee.application.ZiGateDevice(app, 0, 0)
    assert device.model == 'ZiGate USB-TTL {}'.format(FAKE_FIRMWARE_VERSION)


@pytest.mark.asyncio
async def test_form_network_success(app):
    app._api.erase_persistent_data = AsyncMock()
    app._api.set_channel = AsyncMock()
    app._api.set_extended_panid = AsyncMock()
    app._api.reset = AsyncMock()

    async def mock_start_network():
        return [[0x00, 0x1234, 0x0123456789abcdef], 0]
    app._api.start_network = mock_start_network

    async def mock_get_network_state():
        return [
            [
                0x0000,
                t.EUI64([0xef, 0xcd, 0xab, 0x89, 0x67, 0x45, 0x23, 0x01]),
                0x1234,
                0x1234abcdef012345,
                0x11,
            ],
            0,
        ]

    app._api.get_network_state = mock_get_network_state

    await app.form_network()
    await app.load_network_info()
    assert app.state.node_info.nwk == 0x0000
    assert app.state.node_info.ieee == zigpy.types.EUI64.convert(
        "01:23:45:67:89:ab:cd:ef"
    )
    assert app.state.network_info.pan_id == 0x1234
    assert app.state.network_info.extended_pan_id == zigpy.types.ExtendedPanId.convert(
        "12:34:ab:cd:ef:01:23:45"
    )
    assert app._api.reset.call_count == 0


@pytest.mark.asyncio
async def test_form_network_failed(app):
    app._api.erase_persistent_data = AsyncMock()
    app._api.set_channel = AsyncMock()
    app._api.set_extended_panid = AsyncMock()
    app._api.reset = AsyncMock()
    async def mock_start_network():
        return [[0x06], 0]
    app._api.start_network = mock_start_network
    async def mock_get_network_state():
        return [[0xffff, 0x0123456789abcdef, 0x1234, 0, 0x11], 0]
    app._api.get_network_state = mock_get_network_state

    with pytest.raises(zigpy.exceptions.FormationFailure):
        await app.form_network()


@pytest.mark.asyncio
async def test_disconnect_success(app):
    api = MagicMock()

    app._api = api
    await app.disconnect()

    api.close.assert_called_once()
    assert app._api is None


@pytest.mark.asyncio
async def test_disconnect_failure(app, caplog):
    api = MagicMock()
    api.disconnect = MagicMock(side_effect=RuntimeError("Broken"))

    app._api = api

    with caplog.at_level(logging.WARNING):
        await app.disconnect()

    assert "disconnect" in caplog.text

    api.close.assert_called_once()
    assert app._api is None


@pytest.mark.asyncio
async def test_disconnect_multiple(app):
    app._api = None

    await app.disconnect()
    await app.disconnect()
    await app.disconnect()

    assert app._api is None
