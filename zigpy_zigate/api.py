import logging
import asyncio
import binascii
import functools
import struct

from . import uart
from . import types as t

LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 3.0
ZIGATE_BAUDRATE = 115200

RESPONSES = {
    0x004D: (t.uint16_t, t.EUI64, t.uint8_t),
    0x8000: (t.uint8_t, t.uint8_t, t.uint16_t, t.Bytes),
    0x8002: (t.uint8_t, t.uint16_t, t.uint16_t, t.uint8_t, t.uint8_t,
             t.Address, t.Address, t.Bytes),
    0x8009: (t.uint16_t, t.EUI64, t.uint16_t, t.uint64_t, t.uint8_t),
    0x8010: (t.uint16_t, t.uint16_t),
    0x8048: (t.EUI64, t.uint8_t),
    0x8701: (t.uint8_t, t.uint8_t),
    0x8702: (t.uint8_t, t.uint8_t, t.uint8_t, t.Address, t.uint8_t),
}

COMMANDS = {
    0x0002: (t.uint8_t,),
}


class ZiGate:
    def __init__(self):
        self._uart = None
        self._callbacks = {}
        self._awaiting = {}
        self._status_awaiting = {}

        self.network_state = None

    async def connect(self, device, baudrate=ZIGATE_BAUDRATE):
        baudrate = ZIGATE_BAUDRATE  # fix baudrate for zigate
        assert self._uart is None
        self._uart = await uart.connect(device, baudrate, self)

    def close(self):
        return self._uart.close()

    def set_application(self, app):
        self._app = app

    def data_received(self, cmd, data, lqi):
        LOGGER.debug("data received %s %s LQI:%s", hex(cmd),
                     binascii.hexlify(data), lqi)
        if cmd not in RESPONSES:
            LOGGER.error('Received unhandled response %s', hex(cmd))
            return
        data, rest = t.deserialize(data, RESPONSES[cmd])
        if cmd == 0x8000:
            if data[2] in self._status_awaiting:
                fut = self._status_awaiting.pop(data[2])
                fut.set_result((data, lqi))
        if cmd in self._awaiting:
            fut = self._awaiting.pop(cmd)
            fut.set_result((data, lqi))
        self.handle_callback(cmd, data, lqi)

    async def command(self, cmd, data=b'', wait_response=None, wait_status=True):
        try:
            return await asyncio.wait_for(
                self._command(cmd, data, wait_response, wait_status),
                timeout=COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError:
            LOGGER.warning("No response to command 0x{:04x}".format(cmd))
            raise

    def _command(self, cmd, data=b'', wait_response=None, wait_status=True):
        self._uart.send(cmd, data)
        fut = asyncio.Future()
        if wait_status:
            self._status_awaiting[cmd] = fut
        if wait_response:
            fut = asyncio.Future()
            self._awaiting[wait_response] = fut
        if wait_status or wait_response:
            return fut

    async def version(self):
        return await self.command(0x0010, wait_response=0x8010)

    async def get_network_state(self):
        return await self.command(0x0009, wait_response=0x8009)

    async def set_raw_mode(self, enable=True):
        data = t.serialize([enable], COMMANDS[0x0002])
        await self.command(0x0002, data)

    async def reset(self):
        self._command(0x0011, wait_status=False)

    async def set_channel(self, channel):
        channels = [channel]
        mask = functools.reduce(lambda acc, x: acc ^ 2 ** x, channels, 0)
        mask = struct.pack('!I', mask)
        await self.command(0x0021, mask),

    async def set_extended_panid(self, extended_pan_id):
        data = struct.pack('!Q', extended_pan_id)
        await self.command(0x0020, data)

    async def permit_join(self, duration=60):
        data = struct.pack('!HBB', 0xfffc, duration, 0)
        await self.command(0x0049, data)

    async def remove_device(self, zigate_ieee, ieee):
        data = struct.pack('!QQ', zigate_ieee, ieee)
        await self.command(0x0026, data)

    async def raw_aps_data_request(self, addr, src_ep, dst_ep, profile,
                                   cluster, payload, addr_mode=2, security=0):
        '''
        Send raw APS Data request
        '''
        length = len(payload)
        radius = 0
        data = struct.pack('!BHBBHHBBB{}s'.format(length), addr_mode, addr,
                           src_ep, dst_ep, cluster, profile,
                           security, radius, length, payload)
        return await self.command(0x0530, data)

    def add_callback(self, cb):
        id_ = hash(cb)
        while id_ in self._callbacks:
            id_ += 1
        self._callbacks[id_] = cb
        return id_

    def remove_callback(self, id_):
        return self._callbacks.pop(id_)

    def handle_callback(self, *args):
        for callback_id, handler in self._callbacks.items():
            try:
                handler(*args)
            except Exception as e:
                LOGGER.exception("Exception running handler", exc_info=e)
