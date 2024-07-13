import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import zigpy.config as config
import zigpy.exceptions
import zigpy.types as zigpy_t

import zigpy_zigate.api
import zigpy_zigate.types as t
import zigpy_zigate.zigbee.application

APP_CONFIG = zigpy_zigate.zigbee.application.ControllerApplication.SCHEMA(
    {
        config.CONF_DEVICE: {config.CONF_DEVICE_PATH: "/dev/null"},
        config.CONF_DATABASE: None,
    }
)
FAKE_FIRMWARE_VERSION = "3.1z"


@pytest.fixture
def app():
    a = zigpy_zigate.zigbee.application.ControllerApplication(APP_CONFIG)
    a.version = FAKE_FIRMWARE_VERSION
    a._api = MagicMock(spec_set=zigpy_zigate.api.ZiGate)
    return a


def test_zigpy_ieee(app):
    cluster = MagicMock()
    cluster.cluster_id = 0x0000
    data = b"\x01\x02\x03\x04\x05\x06\x07\x08"

    zigate_ieee, _ = t.EUI64.deserialize(data)
    app.state.node_info.ieee = zigpy_t.EUI64(zigate_ieee)

    dst_addr = app.get_dst_address(cluster)
    assert dst_addr.serialize() == b"\x03" + data[::-1] + b"\x01"


@pytest.mark.asyncio
async def test_form_network_success(app):
    app._api.erase_persistent_data = AsyncMock()
    app._api.set_channel = AsyncMock()
    app._api.set_extended_panid = AsyncMock()
    app._api.reset = AsyncMock()

    async def mock_start_network():
        return [[0x00, 0x1234, 0x0123456789ABCDEF], 0]

    app._api.start_network = mock_start_network

    async def mock_get_network_state():
        return [
            [
                0x0000,
                t.EUI64([0xEF, 0xCD, 0xAB, 0x89, 0x67, 0x45, 0x23, 0x01]),
                0x1234,
                0x1234ABCDEF012345,
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
    assert app.state.node_info.version == "3.1z"
    assert app.state.node_info.model == "ZiGate USB-TTL"
    assert app.state.node_info.manufacturer == "ZiGate"
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
        return [[0xFFFF, 0x0123456789ABCDEF, 0x1234, 0, 0x11], 0]

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


@pytest.mark.asyncio
@patch("zigpy_zigate.zigbee.application.ZiGate.new")
@pytest.mark.parametrize(
    "version_rsp, expected_version",
    [[((261, 798), 0), "3.1e"], [((5, 801), 0), "3.21"]],
)
async def test_startup_connect(zigate_new, app, version_rsp, expected_version):
    api = zigate_new.return_value
    api.version.return_value = version_rsp

    await app.connect()

    assert app.version == expected_version


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "version, addr_mode",
    [
        ["3.1z", t.AddressMode.NWK_NO_ACK],
        ["3.1d", t.AddressMode.NWK],
    ],
)
async def test_send_unicast_request(app, version, addr_mode):
    packet = zigpy_t.ZigbeePacket(
        src=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0x0000),
        src_ep=1,
        dst=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0xFA5D),
        dst_ep=1,
        source_route=None,
        extended_timeout=False,
        tsn=20,
        profile_id=260,
        cluster_id=6,
        data=zigpy_t.SerializableBytes(b"\x01\x14\x00"),
        tx_options=zigpy_t.TransmitOptions.NONE,
        radius=0,
        non_member_radius=0,
        lqi=None,
        rssi=None,
    )

    app.version = version
    app._api.raw_aps_data_request.return_value = (
        [t.Status.Success, 163, 1328, b"\x00\x00"],
        0,
    )
    await app.send_packet(packet)

    # The packet was sent with ACKs, even though zigpy didn't ask for it
    assert app._api.raw_aps_data_request.mock_calls[0].kwargs["addr_mode"] == addr_mode

    app._api.raw_aps_data_request.assert_called_once()


@pytest.mark.asyncio
async def test_send_group_request(app):
    packet = zigpy_t.ZigbeePacket(
        src=None,
        src_ep=1,
        dst=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.Group, address=0x0002),
        dst_ep=None,
        source_route=None,
        extended_timeout=False,
        tsn=21,
        profile_id=260,
        cluster_id=6,
        data=zigpy_t.SerializableBytes(b"\x01\x15\x00"),
        tx_options=zigpy_t.TransmitOptions.NONE,
        radius=0,
        non_member_radius=3,
        lqi=None,
        rssi=None,
    )

    app._api.raw_aps_data_request.return_value = (
        [t.Status.Success, 0, 1328, b"\x01\xea\x00\x00"],
        0,
    )
    await app.send_packet(packet)

    app._api.raw_aps_data_request.assert_called_once()


@pytest.mark.asyncio
async def test_energy_scanning(app, caplog):
    with caplog.at_level(logging.WARNING):
        scan_results = await app.energy_scan(
            channels=zigpy_t.Channels.ALL_CHANNELS, duration_exp=2, count=5
        )

    assert scan_results == {c: 0 for c in zigpy_t.Channels.ALL_CHANNELS}

    # We never send a request when scanning
    assert len(app._api.raw_aps_data_request.mock_calls) == 0

    assert "does not support energy scanning" in caplog.text


@pytest.mark.asyncio
async def test_channel_migration(app, caplog):
    app._api.set_channel = AsyncMock()
    await app._move_network_to_channel(17, new_nwk_update_id=2)

    assert app._api.set_channel.mock_calls == [call(17)]
