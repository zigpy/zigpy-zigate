import asyncio
import binascii
import logging
import struct
from typing import Any, Dict

import zigpy.serial

from .config import CONF_DEVICE_PATH
from . import common as c

LOGGER = logging.getLogger(__name__)
ZIGATE_BAUDRATE = 115200


class Gateway(asyncio.Protocol):
    START = b'\x01'
    END = b'\x03'

    def __init__(self, api, connected_future=None):
        self._buffer = b''
        self._connected_future = connected_future
        self._api = api

    def connection_lost(self, exc) -> None:
        """Port was closed expecteddly or unexpectedly."""
        if self._connected_future and not self._connected_future.done():
            if exc is None:
                self._connected_future.set_result(True)
            else:
                self._connected_future.set_exception(exc)
        if exc is None:
            LOGGER.debug("Closed serial connection")
            return

        LOGGER.error("Lost serial connection: %s", exc)
        self._api.connection_lost(exc)

    def connection_made(self, transport):
        """Callback when the uart is connected"""
        LOGGER.debug("Connection made")
        self._transport = transport
        if self._connected_future:
            self._connected_future.set_result(True)

    def close(self):
        if self._transport:
            self._transport.close()

    def send(self, cmd, data=b''):
        """Send data, taking care of escaping and framing"""
        LOGGER.debug("Send: 0x%04x %s", cmd, binascii.hexlify(data))
        length = len(data)
        byte_head = struct.pack('!HH', cmd, length)
        checksum = self._checksum(byte_head, data)
        frame = struct.pack('!HHB%ds' % length, cmd, length, checksum, data)
        LOGGER.debug('Frame to send: %s', frame)
        frame = self._escape(frame)
        LOGGER.debug('Frame escaped: %s', frame)
        self._transport.write(self.START + frame + self.END)

    def data_received(self, data):
        """Callback when there is data received from the uart"""
        self._buffer += data
#         LOGGER.debug('data_received %s', self._buffer)
        endpos = self._buffer.find(self.END)
        while endpos != -1:
            startpos = self._buffer.rfind(self.START, 0, endpos)
            if startpos != -1 and startpos < endpos:
                frame = self._buffer[startpos:endpos + 1]
                frame = self._unescape(frame[1:-1])
                cmd, length, checksum, f_data, lqi = struct.unpack('!HHB%dsB' % (len(frame) - 6), frame)
                if self._length(frame) != length:
                    LOGGER.warning("Invalid length: %s, data: %s",
                                   length,
                                   len(frame) - 6)
                    self._buffer = self._buffer[endpos + 1:]
                    endpos = self._buffer.find(self.END)
                    continue
                if self._checksum(frame[:4], lqi, f_data) != checksum:
                    LOGGER.warning("Invalid checksum: %s, data: 0x%s",
                                   checksum,
                                   binascii.hexlify(frame).decode())
                    self._buffer = self._buffer[endpos + 1:]
                    endpos = self._buffer.find(self.END)
                    continue
                LOGGER.debug("Frame received: %s", binascii.hexlify(frame).decode())
                self._api.data_received(cmd, f_data, lqi)
            else:
                LOGGER.warning('Malformed packet received, ignore it')
            self._buffer = self._buffer[endpos + 1:]
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

    def _length(self, frame):
        length = len(frame) - 5
        return length


async def connect(device_config: Dict[str, Any], api, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    connected_future = asyncio.Future()
    protocol = Gateway(api, connected_future)

    port = device_config[CONF_DEVICE_PATH]
    if port == 'auto':
        port = c.discover_port()

    if c.is_pizigate(port):
        LOGGER.debug('PiZiGate detected')
        await c.async_set_pizigate_running_mode()
        # in case of pizigate:/dev/ttyAMA0 syntax
        if port.startswith('pizigate:'):
            port = port.replace('pizigate:', '', 1)
    elif c.is_zigate_din(port):
        LOGGER.debug('ZiGate USB DIN detected')
        await c.async_set_zigatedin_running_mode()
    elif c.is_zigate_wifi(port):
        LOGGER.debug('ZiGate WiFi detected')

    _, protocol = await zigpy.serial.create_serial_connection(
        loop,
        lambda: protocol,
        url=port,
        baudrate=ZIGATE_BAUDRATE,
        xonxoff=False,
    )

    await connected_future

    return protocol
