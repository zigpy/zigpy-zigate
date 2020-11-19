import asyncio
import binascii
import functools
import logging
import enum
import datetime
from typing import Any, Dict

import serial
import zigpy.exceptions

import zigpy_zigate.config
import zigpy_zigate.uart

from . import types as t

LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 1.5
PROBE_TIMEOUT = 3.0

RESPONSES = {
    0x004D: (t.NWK, t.EUI64, t.uint8_t, t.uint8_t),
    0x8000: (t.uint8_t, t.uint8_t, t.uint16_t, t.Bytes),
    0x8002: (t.uint8_t, t.uint16_t, t.uint16_t, t.uint8_t, t.uint8_t,
             t.Address, t.Address, t.Bytes),
    0x8009: (t.NWK, t.EUI64, t.uint16_t, t.uint64_t, t.uint8_t),
    0x8010: (t.uint16_t, t.uint16_t),
    0x8011: (t.uint8_t, t.NWK, t.uint8_t, t.uint16_t, t.uint8_t),
    0x8017: (t.uint32_t,),
    0x8024: (t.uint8_t, t.NWK, t.EUI64, t.uint8_t),
    0x8035: (t.uint8_t, t.uint32_t),
    0x8048: (t.EUI64, t.uint8_t),
    0x8701: (t.uint8_t, t.uint8_t),
    0x8702: (t.uint8_t, t.uint8_t, t.uint8_t, t.Address, t.uint8_t),
    0x8806: (t.uint8_t,),
}

COMMANDS = {
    0x0002: (t.uint8_t,),
    0x0016: (t.uint32_t,),
    0x0018: (t.uint8_t,),
    0x0019: (t.uint8_t,),
    0x0020: (t.uint64_t,),
    0x0021: (t.uint32_t,),
    0x0026: (t.EUI64, t.EUI64),
    0x0049: (t.NWK, t.uint8_t, t.uint8_t),
    0x0530: (t.uint8_t, t.NWK, t.uint8_t, t.uint8_t, t.uint16_t, t.uint16_t, t.uint8_t, t.uint8_t, t.LBytes),
    0x0806: (t.uint8_t,),
}


class AutoEnum(enum.IntEnum):
    def _generate_next_value_(name, start, count, last_values):
        return count


class PDM_EVENT(AutoEnum):
    E_PDM_SYSTEM_EVENT_WEAR_COUNT_TRIGGER_VALUE_REACHED = enum.auto()
    E_PDM_SYSTEM_EVENT_DESCRIPTOR_SAVE_FAILED = enum.auto()
    E_PDM_SYSTEM_EVENT_PDM_NOT_ENOUGH_SPACE = enum.auto()
    E_PDM_SYSTEM_EVENT_LARGEST_RECORD_FULL_SAVE_NO_LONGER_POSSIBLE = enum.auto()
    E_PDM_SYSTEM_EVENT_SEGMENT_DATA_CHECKSUM_FAIL = enum.auto()
    E_PDM_SYSTEM_EVENT_SEGMENT_SAVE_OK = enum.auto()
    E_PDM_SYSTEM_EVENT_EEPROM_SEGMENT_HEADER_REPAIRED = enum.auto()
    E_PDM_SYSTEM_EVENT_SYSTEM_INTERNAL_BUFFER_WEAR_COUNT_SWAP = enum.auto()
    E_PDM_SYSTEM_EVENT_SYSTEM_DUPLICATE_FILE_SEGMENT_DETECTED = enum.auto()
    E_PDM_SYSTEM_EVENT_SYSTEM_ERROR = enum.auto()
    E_PDM_SYSTEM_EVENT_SEGMENT_PREWRITE = enum.auto()
    E_PDM_SYSTEM_EVENT_SEGMENT_POSTWRITE = enum.auto()
    E_PDM_SYSTEM_EVENT_SEQUENCE_DUPLICATE_DETECTED = enum.auto()
    E_PDM_SYSTEM_EVENT_SEQUENCE_VERIFY_FAIL = enum.auto()
    E_PDM_SYSTEM_EVENT_PDM_SMART_SAVE = enum.auto()
    E_PDM_SYSTEM_EVENT_PDM_FULL_SAVE = enum.auto()


class NoResponseError(zigpy.exceptions.APIException):
    pass


class ZiGate:
    def __init__(self, device_config: Dict[str, Any]):
        self._app = None
        self._config = device_config
        self._uart = None
        self._awaiting = {}
        self._status_awaiting = {}
        self._lock = asyncio.Lock()

        self.network_state = None

    @classmethod
    async def new(cls, config: Dict[str, Any], application=None) -> "ZiGate":
        api = cls(config)
        await api.connect()
        api.set_application(application)
        return api

    async def connect(self):
        assert self._uart is None
        self._uart = await zigpy_zigate.uart.connect(self._config, self)

    def close(self):
        if self._uart:
            self._uart.close()
            self._uart = None

    def set_application(self, app):
        self._app = app

    def data_received(self, cmd, data, lqi):
        LOGGER.debug("data received %s %s LQI:%s", hex(cmd),
                     binascii.hexlify(data), lqi)
        if cmd not in RESPONSES:
            LOGGER.error('Received unhandled response 0x%04x', cmd)
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
        tries = 2
        while tries > 0:
            tries -= 1
            await self._lock.acquire()
            try:
                return await asyncio.wait_for(
                    self._command(cmd, data, wait_response, wait_status),
                    timeout=COMMAND_TIMEOUT
                )
            except asyncio.TimeoutError:
                LOGGER.warning("No response to command 0x%04x", cmd)
                if tries > 0:
                    LOGGER.warning("Retry command 0x%04x", cmd)
                else:
                    raise NoResponseError
            finally:
                self._lock.release()

    def _command(self, cmd, data=b'', wait_response=None, wait_status=True):
        self._uart.send(cmd, data)
        if wait_status:
            fut = asyncio.Future()
            self._status_awaiting[cmd] = fut
        if wait_response:
            fut = asyncio.Future()
            self._awaiting[wait_response] = fut
        if wait_status or wait_response:
            return fut

    async def version(self):
        return await self.command(0x0010, wait_response=0x8010)

    async def version_str(self):
        version, lqi = await self.version()
        version = '{:x}'.format(version[1])
        version = '{}.{}'.format(version[0], version[1:])
        return version

    async def get_network_state(self):
        return await self.command(0x0009, wait_response=0x8009)

    async def set_raw_mode(self, enable=True):
        data = t.serialize([enable], COMMANDS[0x0002])
        await self.command(0x0002, data)

    async def reset(self):
        self._command(0x0011, wait_status=False)

    async def erase_persistent_data(self):
        self._command(0x0012, wait_status=False)

    async def set_time(self, dt=None):
        """ set internal time
        if timestamp is None, now is used
        """
        dt = dt or datetime.datetime.now()
        timestamp = int((dt - datetime.datetime(2000, 1, 1)).total_seconds())
        data = t.serialize([timestamp], COMMANDS[0x0016])
        self._command(0x0016, data)

    async def get_time_server(self):
        timestamp, lqi = await self._command(0x0017, wait_response=0x8017)
        dt = datetime.datetime(2000, 1, 1) + datetime.timedelta(seconds=timestamp[0])
        return dt

    async def set_led(self, enable=True):
        data = t.serialize([enable], COMMANDS[0x0018])
        await self.command(0x0018, data)

    async def set_certification(self, typ='CE'):
        cert = {'CE': 1, 'FCC': 2}[typ]
        data = t.serialize([cert], COMMANDS[0x0019])
        await self.command(0x0019, data)

    async def set_tx_power(self, power=63):
        if power > 63:
            power = 63
        if power < 0:
            power = 0
        data = t.serialize([power], COMMANDS[0x0806])
        power, lqi = await self.command(0x0806, data, wait_response=0x8806)
        return power[0]

    async def set_channel(self, channels=None):
        channels = channels or [11, 14, 15, 19, 20, 24, 25, 26]
        if not isinstance(channels, list):
            channels = [channels]
        mask = functools.reduce(lambda acc, x: acc ^ 2 ** x, channels, 0)
        data = t.serialize([mask], COMMANDS[0x0021])
        await self.command(0x0021, data),

    async def set_extended_panid(self, extended_pan_id):
        data = t.serialize([extended_pan_id], COMMANDS[0x0020])
        await self.command(0x0020, data)

    async def permit_join(self, duration=60):
        data = t.serialize([0xfffc, duration, 0], COMMANDS[0x0049])
        return await self.command(0x0049, data)

    async def start_network(self):
        return await self.command(0x0024, wait_response=0x8024)

    async def remove_device(self, zigate_ieee, ieee):
        data = t.serialize([zigate_ieee, ieee], COMMANDS[0x0026])
        return await self.command(0x0026, data)

    async def raw_aps_data_request(self, addr, src_ep, dst_ep, profile,
                                   cluster, payload, addr_mode=2, security=0):
        '''
        Send raw APS Data request
        '''
        radius = 0
        data = t.serialize([addr_mode, addr,
                           src_ep, dst_ep, cluster, profile,
                           security, radius, payload], COMMANDS[0x0530])
        return await self.command(0x0530, data)

    def handle_callback(self, *args):
        """run application callback handler"""
        if self._app:
            try:
                self._app.zigate_callback_handler(*args)
            except Exception as e:
                LOGGER.exception("Exception running handler", exc_info=e)

    @classmethod
    async def probe(cls, device_config: Dict[str, Any]) -> bool:
        """Probe port for the device presence."""
        api = cls(zigpy_zigate.config.SCHEMA_DEVICE(device_config))
        try:
            await asyncio.wait_for(api._probe(), timeout=PROBE_TIMEOUT)
            return True
        except (
            asyncio.TimeoutError,
            serial.SerialException,
            zigpy.exceptions.ZigbeeException,
        ) as exc:
            LOGGER.debug(
                "Unsuccessful radio probe of '%s' port",
                device_config[zigpy_zigate.config.CONF_DEVICE_PATH],
                exc_info=exc,
            )
        finally:
            api.close()

        return False

    async def _probe(self) -> None:
        """Open port and try sending a command"""
        try:
            device = next(serial.tools.list_ports.grep(self._config[zigpy_zigate.config.CONF_DEVICE_PATH]))
            if device.description == 'ZiGate':
                return
        except StopIteration:
            pass
        await self.connect()
        await self.set_raw_mode()
