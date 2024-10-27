from __future__ import annotations

import asyncio
import binascii
import logging
import struct
from typing import Any

import zigpy.config
import zigpy.serial

from . import common as c

LOGGER = logging.getLogger(__name__)


class Gateway(zigpy.serial.SerialProtocol):
    START = b"\x01"
    END = b"\x03"

    def __init__(self, api):
        super().__init__()
        self._api = api

    def connection_lost(self, exc: Exception | None) -> None:
        """Port was closed expectedly or unexpectedly."""
        super().connection_lost(exc)

        if self._api is not None:
            self._api.connection_lost(exc)

    def close(self):
        super().close()
        self._api = None

    def send(self, cmd, data=b""):
        """Send data, taking care of escaping and framing"""
        LOGGER.debug("Send: 0x%04x %s", cmd, binascii.hexlify(data))
        length = len(data)
        byte_head = struct.pack("!HH", cmd, length)
        checksum = self._checksum(byte_head, data)
        frame = struct.pack("!HHB%ds" % length, cmd, length, checksum, data)
        LOGGER.debug("Frame to send: %s", frame)
        frame = self._escape(frame)
        LOGGER.debug("Frame escaped: %s", frame)
        self._transport.write(self.START + frame + self.END)

    def data_received(self, data):
        """Callback when there is data received from the uart"""
        super().data_received(data)
        endpos = self._buffer.find(self.END)
        while endpos != -1:
            startpos = self._buffer.rfind(self.START, 0, endpos)
            if startpos != -1 and startpos < endpos:
                frame = self._buffer[startpos : endpos + 1]
                frame = self._unescape(frame[1:-1])
                cmd, length, checksum, f_data, lqi = struct.unpack(
                    "!HHB%dsB" % (len(frame) - 6), frame
                )
                if len(frame) - 5 != length:
                    LOGGER.warning(
                        "Invalid length: %s, data: %s", length, len(frame) - 6
                    )
                    self._buffer = self._buffer[endpos + 1 :]
                    endpos = self._buffer.find(self.END)
                    continue
                if self._checksum(frame[:4], lqi, f_data) != checksum:
                    LOGGER.warning(
                        "Invalid checksum: %s, data: 0x%s",
                        checksum,
                        binascii.hexlify(frame).decode(),
                    )
                    self._buffer = self._buffer[endpos + 1 :]
                    endpos = self._buffer.find(self.END)
                    continue
                LOGGER.debug("Frame received: %s", binascii.hexlify(frame).decode())
                self._api.data_received(cmd, f_data, lqi)
            else:
                LOGGER.warning("Malformed packet received, ignore it")
            self._buffer = self._buffer[endpos + 1 :]
            endpos = self._buffer.find(self.END)

    def _unescape(self, data):
        flip = False
        ret = []
        for b in data:
            if flip:
                flip = False
                ret.append(b ^ 0x10)
            elif b == 0x02:
                flip = True
            else:
                ret.append(b)
        return bytes(ret)

    def _escape(self, data):
        ret = []
        for b in data:
            if b < 0x10:
                ret.extend([0x02, 0x10 ^ b])
            else:
                ret.append(b)
        return bytes(ret)

    def _checksum(self, *args):
        chcksum = 0
        for arg in args:
            if isinstance(arg, int):
                chcksum ^= arg
                continue
            for x in arg:
                chcksum ^= x
        return chcksum


async def connect(device_config: dict[str, Any], api, loop=None):
    loop = asyncio.get_running_loop()
    port = device_config[zigpy.config.CONF_DEVICE_PATH]

    if await c.async_is_pizigate(port):
        LOGGER.debug("PiZiGate detected")
        await c.async_set_pizigate_running_mode()
        port = port.replace("pizigate:", "", 1)
    elif await c.async_is_zigate_din(port):
        LOGGER.debug("ZiGate USB DIN detected")
        await c.async_set_zigatedin_running_mode()

    protocol = Gateway(api)
    _, protocol = await zigpy.serial.create_serial_connection(
        loop,
        lambda: protocol,
        url=port,
        baudrate=device_config[zigpy.config.CONF_DEVICE_BAUDRATE],
        flow_control=device_config[zigpy.config.CONF_DEVICE_FLOW_CONTROL],
    )

    await protocol.wait_until_connected()

    return protocol
