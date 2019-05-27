import logging
import zigate
import asyncio
import enum
import binascii
import functools
import struct

from . import uart
from . import types as t

LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 2
ZIGATE_BAUDRATE = 115200

LOGGER = logging.getLogger(__name__)


class ZiGate:
    def __init__(self):
        self._uart = None
        self._zigate = None
        self._callbacks = {}
        self._awaiting = {}
        self._status_awaiting = {}

        self.network_state = None

    async def connect(self, device, baudrate=ZIGATE_BAUDRATE):
        assert self._uart is None
        self._uart = await uart.connect(device, baudrate, self)

    def close(self):
        return self._uart.close()

    def set_application(self, app):
        self._app = app

    def data_received(self, cmd, data, lqi):
        if cmd in self._status_awaiting:
            fut = self._status_awaiting.pop(cmd)
            fut.set_result((data, lqi))
        elif cmd in self._awaiting:
            fut = self._awaiting.pop(cmd)
            fut.set_result((data, lqi))

    async def _command(self, cmd, data='', wait_response=None, wait_status=True):
        self._uart.send(cmd, data)
        fut = asyncio.Future()
        if wait_status:
            self._status_awaiting[cmd] = fut
        if wait_response:
            fut = asyncio.Future()
            self._awaiting[wait_response] = fut
        return fut

    async def version(self):
        try:
            return await asyncio.wait_for(
                self._command(0x0010, wait_response=0x8010),
                timeout=COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError:
            LOGGER.warning("No response to version command")
            raise

    async def get_network_state(self):
        try:
            return await asyncio.wait_for(
                self._command(0x0009, wait_response=0x8009),
                timeout=COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError:
            LOGGER.warning("No response to get_network_state command")
            raise

    def set_channel(self, channel):
        channels = [channel]
        mask = functools.reduce(lambda acc, x: acc ^ 2 ** x, channels, 0)
        mask = struct.pack('!I', mask)
        self._command(0x0021, mask),

    def set_extended_panid(self, extended_pan_id):
        data = struct.pack('!Q', extended_pan_id)
        self._command(0x0020, data)

    async def old_connect(self, device, baudrate=115200):
        assert self._zigate is None
        if '.' in device:  # supposed I.P:PORT
            host_port = device.split(':', 1)
            host = host_port[0]
            port = None
            if len(host_port) == 2:
                port = int(host_port[1])
            LOGGER.info('Configuring ZiGate WiFi {} {}'.format(host, port))
            self._zigate = zigate.ZiGateWiFi(host, port, auto_start=False)
        else:
            LOGGER.info('Configuring ZiGate USB {}'.format(device))
            self._zigate = zigate.ZiGate(device, auto_start=False)
        self._interpret_response = self._zigate.interpret_response  # keep link
        loop = asyncio.get_event_loop()

        def interpret_response(response):
            if response.msg == 0x8000:  # status response handle by zigate instance
                self._interpret_response(response)
            else:
                loop.call_soon_threadsafe(self.handle_callback, response)
#                 self.handle_callback(response)
        self._zigate.interpret_response = interpret_response

    def __getattr__(self, name):
        return self._zigate.__getattribute__(name)

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

    def interpret_response(self, response):
        if response.msg == 0x8000:  # status response handle by zigate instance
            self._interpret_response(response)
        else:
            self.handle_callback(response)
