from unittest.mock import AsyncMock, patch

import pytest
import zigpy.config

from zigpy_zigate.tools import cli


@pytest.mark.parametrize(
    ("argv_port", "port"),
    [(["-p", "/dev/ttyUSB1"], "/dev/ttyUSB1"), ([], "/dev/ttyUSB0")],
)
async def test_cli_version(argv_port, port, capsys):
    with (
        patch("sys.argv", ["cli", "version", *argv_port]),
        patch.object(cli.c, "discover_port", return_value="/dev/ttyUSB0"),
        patch.object(cli, "ZiGate") as zigate_cls,
    ):
        api = zigate_cls.return_value
        api.connect = AsyncMock()
        api.version_str = AsyncMock(return_value="3.21")
        api.disconnect = AsyncMock()

        await cli.main()

    zigate_cls.assert_called_once_with(
        zigpy.config.SCHEMA_DEVICE({zigpy.config.CONF_DEVICE_PATH: port})
    )
    api.connect.assert_awaited_once_with()
    api.disconnect.assert_awaited_once_with()
    assert "Firmware version 3.21" in capsys.readouterr().out
