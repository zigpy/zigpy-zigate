import asyncio
import logging
import serial
import binascii
import struct

import serial_asyncio

LOGGER = logging.getLogger(__name__)


class Gateway(asyncio.Protocol):
    START = b'\x01'
    END = b'\x03'

    def __init__(self, api, connected_future=None):
        self._buffer = b''
        self._connected_future = connected_future
        self._api = api

    def connection_made(self, transport):
        """Callback when the uart is connected"""
        LOGGER.debug("Connection made")
        self._transport = transport
        if self._connected_future:
            self._connected_future.set_result(True)

    def close(self):
        self._transport.close()

    def send(self, cmd, data=b''):
        """Send data, taking care of escaping and framing"""
        LOGGER.debug("Send: %s %s", hex(cmd), binascii.hexlify(data))
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
                    continue
                if self._checksum(frame[:4], lqi, f_data) != checksum:
                    LOGGER.warning("Invalid checksum: %s, data: 0x%s",
                                   checksum,
                                   binascii.hexlify(frame).decode())
                    self._buffer = self._buffer[endpos + 1:]
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


async def connect(port, baudrate, api, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    connected_future = asyncio.Future()
    protocol = Gateway(api, connected_future)

    _, protocol = await serial_asyncio.create_serial_connection(
        loop,
        lambda: protocol,
        url=port,
        baudrate=baudrate,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
    )

    await connected_future

    return protocol
