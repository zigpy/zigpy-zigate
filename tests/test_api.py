import asyncio
import functools
import logging
from unittest.mock import AsyncMock, MagicMock, patch, sentinel

import pytest
import zigpy.config as config
import zigpy.types

from zigpy_zigate import api as zigate_api, types as t
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

    monkeypatch.setattr(zigpy_zigate.uart, "create_serial_connection", mock_conn)

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


def _status_frame(status, cmd):
    return t.Status(status).serialize() + b"\x01" + t.uint16_t(cmd).serialize()


async def _command_with_replies(api, replies, **kwargs):
    """Run a GET_VERSION command, feeding each reply after the first send."""
    loop = asyncio.get_running_loop()

    def send(cmd, data):
        if api._uart.send.call_count == 1:
            for delay, rsp_cmd, rsp_data in replies:
                loop.call_later(delay, api.data_received, rsp_cmd, rsp_data, 255)

    api._uart.send.side_effect = send

    return await api.command(
        zigate_api.CommandId.GET_VERSION,
        wait_response=zigate_api.ResponseId.VERSION_LIST,
        timeout=0.1,
        **kwargs,
    )


async def test_command_status_without_response(api):
    status = _status_frame(t.Status.Success, zigate_api.CommandId.GET_VERSION)

    with pytest.raises(zigate_api.NoResponseError):
        await _command_with_replies(api, [(0, zigate_api.ResponseId.STATUS, status)])

    # The status confirmed the command, so it is not sent again
    assert api._uart.send.call_count == 1


async def test_command_late_response(api):
    status = _status_frame(t.Status.Success, zigate_api.CommandId.GET_VERSION)
    version = t.uint16_t(0x0005).serialize() + t.uint16_t(0x0321).serialize()

    rsp, lqi = await _command_with_replies(
        api,
        [
            (0, zigate_api.ResponseId.STATUS, status),
            (0.15, zigate_api.ResponseId.VERSION_LIST, version),
        ],
    )

    assert rsp == [0x0005, 0x0321]
    assert lqi == 255
    assert api._uart.send.call_count == 1


async def test_command_failed_status_returned(api):
    status = _status_frame(t.Status.UnhandledCommand, zigate_api.CommandId.GET_VERSION)

    rsp, lqi = await _command_with_replies(
        api, [(0, zigate_api.ResponseId.STATUS, status)]
    )

    assert rsp[0] == t.Status.UnhandledCommand
    assert api._uart.send.call_count == 1


async def test_reset_without_restart_message(api, caplog):
    status = _status_frame(t.Status.Success, zigate_api.CommandId.RESET)
    loop = asyncio.get_running_loop()
    api._uart.send.side_effect = lambda cmd, data: loop.call_soon(
        api.data_received, zigate_api.ResponseId.STATUS, status, 255
    )

    with (
        patch.object(api, "command", functools.partial(api.command, timeout=0.1)),
        caplog.at_level(logging.DEBUG),
    ):
        await api.reset()

    assert api._uart.send.call_count == 1
    assert "No NODE_NON_FACTORY_NEW_RESTART message after reset" in caplog.text


async def test_erase_persistent_data_without_restart_message(api, caplog):
    loop = asyncio.get_running_loop()

    def send(cmd, data):
        if cmd == zigate_api.CommandId.ERASE_PERSISTENT_DATA:
            rsp = (zigate_api.ResponseId.PDM_LOADED, t.uint8_t(0).serialize())
        else:
            rsp = (
                zigate_api.ResponseId.STATUS,
                _status_frame(t.Status.Success, zigate_api.CommandId.RESET),
            )

        loop.call_soon(api.data_received, *rsp, 255)

    api._uart.send.side_effect = send

    with (
        patch.object(api, "command", functools.partial(api.command, timeout=0.1)),
        patch.object(asyncio, "sleep", AsyncMock()),
        caplog.at_level(logging.DEBUG),
    ):
        await api.erase_persistent_data()

    assert [c.args[0] for c in api._uart.send.call_args_list] == [
        zigate_api.CommandId.ERASE_PERSISTENT_DATA,
        zigate_api.CommandId.RESET,
    ]
    assert "No NODE_FACTORY_NEW_RESTART message after reset" in caplog.text


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (t.Status.UnhandledCommand, zigate_api.CommandNotSupportedError),
        (t.Status.Busy, zigate_api.CommandError),
    ],
)
async def test_get_network_key_failed_status(api, status, exc):
    api.command = AsyncMock(return_value=([status, 1, 0x0054, None], 255))

    with pytest.raises(exc):
        await api.get_network_key()


async def test_get_network_key(api):
    key = zigpy.types.KeyData(range(16))
    api.command = AsyncMock(return_value=([key], 255))

    assert await api.get_network_key() == key


async def test_command_failed_status_in_last_wait(api):
    status = _status_frame(t.Status.CommandFailed, zigate_api.CommandId.START_NETWORK)
    loop = asyncio.get_running_loop()

    def send(cmd, data):
        # No status for the first two sends, the failed status during the last wait
        if api._uart.send.call_count == 3:
            loop.call_soon(api.data_received, zigate_api.ResponseId.STATUS, status, 255)

    api._uart.send.side_effect = send

    with patch.object(api, "command", functools.partial(api.command, timeout=0.1)):
        rsp, lqi = await api.start_network()

    assert rsp[0] == t.Status.CommandFailed
    assert api._uart.send.call_count == 3
