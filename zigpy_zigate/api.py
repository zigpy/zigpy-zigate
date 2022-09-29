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


class CommandId(enum.IntEnum):
    SET_RAWMODE = 0x0002
    NETWORK_STATE_REQ = 0x0009
    GET_VERSION = 0x0010
    RESET = 0x0011
    ERASE_PERSISTENT_DATA = 0x0012
    GET_DEVICES_LIST = 0x0015
    SET_TIMESERVER = 0x0016
    GET_TIMESERVER = 0x0017
    SET_LED = 0x0018
    SET_CE_FCC = 0x0019
    SET_EXT_PANID = 0x0020
    SET_CHANNELMASK = 0x0021
    START_NETWORK = 0x0024
    NETWORK_REMOVE_DEVICE = 0x0026
    PERMIT_JOINING_REQUEST = 0x0049
    MANAGEMENT_NETWORK_UPDATE_REQUEST = 0x004A
    SEND_RAW_APS_DATA_PACKET = 0x0530
    AHI_SET_TX_POWER = 0x0806


class ResponseId(enum.IntEnum):
    DEVICE_ANNOUNCE = 0x004D
    STATUS = 0x8000
    LOG = 0x8001
    DATA_INDICATION = 0x8002
    PDM_LOADED = 0x0302
    NODE_NON_FACTORY_NEW_RESTART = 0x8006
    NODE_FACTORY_NEW_RESTART = 0x8007
    HEART_BEAT = 0x8008
    NETWORK_STATE_RSP = 0x8009
    VERSION_LIST = 0x8010
    ACK_DATA = 0x8011
    APS_DATA_CONFIRM = 0x8012
    PERMIT_JOIN_RSP = 0x8014
    GET_DEVICES_LIST_RSP = 0x8015
    GET_TIMESERVER_LIST = 0x8017
    NETWORK_JOINED_FORMED = 0x8024
    PDM_EVENT = 0x8035
    NODE_DESCRIPTOR_RSP = 0x8042
    LEAVE_INDICATION = 0x8048
    ROUTE_DISCOVERY_CONFIRM = 0x8701
    APS_DATA_CONFIRM_FAILED = 0x8702
    AHI_SET_TX_POWER_RSP = 0x8806
    EXTENDED_ERROR = 0x9999


class SendSecurity(t.uint8_t, enum.Enum):
    NETWORK = 0x00
    APPLINK = 0x01
    TEMP_APPLINK = 0x02


class NonFactoryNewRestartStatus(t.uint8_t, enum.Enum):
    Startup = 0
    Running = 1
    Start = 2

class FactoryNewRestartStatus(t.uint8_t, enum.Enum):
    Startup = 0
    Start = 2
    Running = 6


RESPONSES = {
    ResponseId.DEVICE_ANNOUNCE: (t.NWK, t.EUI64, t.uint8_t, t.uint8_t),
    ResponseId.STATUS: (t.Status, t.uint8_t, t.uint16_t, t.Bytes),
    ResponseId.LOG: (t.LogLevel, t.Bytes),
    ResponseId.DATA_INDICATION: (
        t.Status,
        t.uint16_t,
        t.uint16_t,
        t.uint8_t,
        t.uint8_t,
        t.Address,
        t.Address,
        t.Bytes,
    ),
    ResponseId.PDM_LOADED: (t.uint8_t,),
    ResponseId.NODE_NON_FACTORY_NEW_RESTART: (NonFactoryNewRestartStatus,),
    ResponseId.NODE_FACTORY_NEW_RESTART: (FactoryNewRestartStatus,),
    ResponseId.HEART_BEAT: (t.uint32_t,),
    ResponseId.NETWORK_STATE_RSP: (t.NWK, t.EUI64, t.uint16_t, t.uint64_t, t.uint8_t),
    ResponseId.VERSION_LIST: (t.uint16_t, t.uint16_t),
    ResponseId.ACK_DATA: (t.Status, t.NWK, t.uint8_t, t.uint16_t, t.uint8_t),
    ResponseId.APS_DATA_CONFIRM: (
        t.Status,
        t.uint8_t,
        t.uint8_t,
        t.Address,
        t.uint8_t,
    ),
    ResponseId.PERMIT_JOIN_RSP: (t.uint8_t,),
    ResponseId.GET_DEVICES_LIST_RSP: (t.DeviceEntryArray,),
    ResponseId.GET_TIMESERVER_LIST: (t.uint32_t,),
    ResponseId.NETWORK_JOINED_FORMED: (t.uint8_t, t.NWK, t.EUI64, t.uint8_t),
    ResponseId.PDM_EVENT: (t.Status, t.uint32_t),
    ResponseId.NODE_DESCRIPTOR_RSP: (
        t.uint8_t,
        t.Status,
        t.NWK,
        t.uint16_t,
        t.uint16_t,
        t.uint16_t,
        t.uint16_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
    ),
    ResponseId.LEAVE_INDICATION: (t.EUI64, t.uint8_t),
    ResponseId.ROUTE_DISCOVERY_CONFIRM: (t.uint8_t, t.uint8_t),
    ResponseId.APS_DATA_CONFIRM_FAILED: (
        t.Status,
        t.uint8_t,
        t.uint8_t,
        t.Address,
        t.uint8_t,
    ),
    ResponseId.AHI_SET_TX_POWER_RSP: (t.uint8_t,),
    ResponseId.EXTENDED_ERROR: (t.Status,),
}

COMMANDS = {
    CommandId.SET_RAWMODE: (t.uint8_t,),
    CommandId.SET_TIMESERVER: (t.uint32_t,),
    CommandId.SET_LED: (t.uint8_t,),
    CommandId.SET_CE_FCC: (t.uint8_t,),
    CommandId.SET_EXT_PANID: (t.uint64_t,),
    CommandId.SET_CHANNELMASK: (t.uint32_t,),
    CommandId.NETWORK_REMOVE_DEVICE: (t.EUI64, t.EUI64),
    CommandId.PERMIT_JOINING_REQUEST: (t.NWK, t.uint8_t, t.uint8_t),
    CommandId.MANAGEMENT_NETWORK_UPDATE_REQUEST: (
        t.NWK,
        t.uint32_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
    ),
    CommandId.SEND_RAW_APS_DATA_PACKET: (
        t.uint8_t,
        t.NWK,
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
        t.uint16_t,
        t.uint8_t,
        t.uint8_t,
        t.LBytes,
    ),
    CommandId.AHI_SET_TX_POWER: (t.uint8_t,),
}


class AutoEnum(enum.IntEnum):
    def _generate_next_value_(name, start, count, last_values):
        return count


class PDM_EVENT(enum.IntEnum):
    E_PDM_SYSTEM_EVENT_WEAR_COUNT_TRIGGER_VALUE_REACHED = 0
    E_PDM_SYSTEM_EVENT_DESCRIPTOR_SAVE_FAILED = 1
    E_PDM_SYSTEM_EVENT_PDM_NOT_ENOUGH_SPACE = 2
    E_PDM_SYSTEM_EVENT_LARGEST_RECORD_FULL_SAVE_NO_LONGER_POSSIBLE = 3
    E_PDM_SYSTEM_EVENT_SEGMENT_DATA_CHECKSUM_FAIL = 4
    E_PDM_SYSTEM_EVENT_SEGMENT_SAVE_OK = 5
    E_PDM_SYSTEM_EVENT_EEPROM_SEGMENT_HEADER_REPAIRED = 6
    E_PDM_SYSTEM_EVENT_SYSTEM_INTERNAL_BUFFER_WEAR_COUNT_SWAP = 7
    E_PDM_SYSTEM_EVENT_SYSTEM_DUPLICATE_FILE_SEGMENT_DETECTED = 8
    E_PDM_SYSTEM_EVENT_SYSTEM_ERROR = 9
    E_PDM_SYSTEM_EVENT_SEGMENT_PREWRITE = 10
    E_PDM_SYSTEM_EVENT_SEGMENT_POSTWRITE = 11
    E_PDM_SYSTEM_EVENT_SEQUENCE_DUPLICATE_DETECTED = 12
    E_PDM_SYSTEM_EVENT_SEQUENCE_VERIFY_FAIL = 13
    E_PDM_SYSTEM_EVENT_PDM_SMART_SAVE = 14
    E_PDM_SYSTEM_EVENT_PDM_FULL_SAVE = 15


class NoResponseError(zigpy.exceptions.APIException):
    pass


class NoStatusError(NoResponseError):
    pass


class CommandError(zigpy.exceptions.APIException):
    pass


class ZiGate:
    def __init__(self, device_config: Dict[str, Any]):
        self._app = None
        self._config = device_config
        self._uart = None
        self._awaiting = {}
        self._status_awaiting = {}
        self._lock = asyncio.Lock()
        self._conn_lost_task = None

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
    
    def connection_lost(self, exc: Exception) -> None:
        """Lost serial connection."""
        LOGGER.warning(
            "Serial '%s' connection lost unexpectedly: %s",
            self._config[zigpy_zigate.config.CONF_DEVICE_PATH],
            exc,
        )
        self._uart = None
        if self._conn_lost_task and not self._conn_lost_task.done():
            self._conn_lost_task.cancel()
        self._conn_lost_task = asyncio.ensure_future(self._connection_lost())

    async def _connection_lost(self) -> None:
        """Reconnect serial port."""
        try:
            await self._reconnect_till_done()
        except asyncio.CancelledError:
            LOGGER.debug("Cancelling reconnection attempt")

    async def _reconnect_till_done(self) -> None:
        attempt = 1
        while True:
            try:
                await asyncio.wait_for(self.reconnect(), timeout=10)
                break
            except (asyncio.TimeoutError, OSError) as exc:
                wait = 2 ** min(attempt, 5)
                attempt += 1
                LOGGER.debug(
                    "Couldn't re-open '%s' serial port, retrying in %ss: %s",
                    self._config[zigpy_zigate.config.CONF_DEVICE_PATH],
                    wait,
                    str(exc),
                )
                await asyncio.sleep(wait)

        LOGGER.debug(
            "Reconnected '%s' serial port after %s attempts",
            self._config[zigpy_zigate.config.CONF_DEVICE_PATH],
            attempt,
        )

    def close(self):
        if self._uart:
            self._uart.close()
            self._uart = None
        
    def reconnect(self):
        """Reconnect using saved parameters."""
        LOGGER.debug("Reconnecting '%s' serial port", self._config[zigpy_zigate.config.CONF_DEVICE_PATH])
        return self.connect()

    def set_application(self, app):
        self._app = app

    def data_received(self, cmd, data, lqi):
        LOGGER.debug("data received %s %s LQI:%s", hex(cmd),
                     binascii.hexlify(data), lqi)
        if cmd not in RESPONSES:
            LOGGER.warning('Received unhandled response 0x%04x', cmd)
            return
        cmd = ResponseId(cmd)
        data, rest = t.deserialize(data, RESPONSES[cmd])
        if cmd == ResponseId.STATUS:
            if data[2] in self._status_awaiting:
                fut = self._status_awaiting.pop(data[2])
                fut.set_result((data, lqi))
        if cmd in self._awaiting:
            fut = self._awaiting.pop(cmd)
            fut.set_result((data, lqi))
        self.handle_callback(cmd, data, lqi)

    async def wait_for_status(self, cmd):
        LOGGER.debug('Wait for status to command %s', cmd)

        if cmd in self._status_awaiting:
            self._status_awaiting[cmd].cancel()

        status_fut = asyncio.Future()
        self._status_awaiting[cmd] = status_fut

        try:
            return await status_fut
        finally:
            if cmd in self._status_awaiting:
                self._status_awaiting[cmd].cancel()
                del self._status_awaiting[cmd]

    async def wait_for_response(self, wait_response):
        LOGGER.debug('Wait for response %s', wait_response)

        if wait_response in self._awaiting:
            self._awaiting[wait_response].cancel()

        response_fut = asyncio.Future()
        self._awaiting[wait_response] = response_fut

        try:
            return await response_fut
        finally:
            if wait_response in self._awaiting:
                self._awaiting[wait_response].cancel()
                del self._awaiting[wait_response]

    async def command(self, cmd, data=b'', wait_response=None, wait_status=True, timeout=COMMAND_TIMEOUT):
        async with self._lock:
            tries = 3

            tasks = []
            status_task = None
            response_task = None

            LOGGER.debug(
                "Sending %s (%s), waiting for status: %s, waiting for response: %s",
                cmd,
                data,
                wait_status,
                wait_response,
            )

            if wait_status:
                status_task = asyncio.create_task(self.wait_for_status(cmd))
                tasks.append(status_task)

            if wait_response is not None:
                response_task = asyncio.create_task(self.wait_for_response(wait_response))
                tasks.append(response_task)

            try:
                while tries > 0:
                    if self._uart is None:
                        # connection was lost
                        raise CommandError("API is not running")

                    tries -= 1
                    self._uart.send(cmd, data)

                    done, pending = await asyncio.wait(tasks, timeout=timeout)

                    if wait_status and tries == 0 and status_task in pending:
                        raise NoStatusError()
                    elif wait_response and tries == 0 and response_task in pending:
                        raise NoResponseError()

                    if wait_response and response_task in done:
                        if wait_status and status_task in pending:
                            continue
                        elif wait_status:
                            await status_task

                        return await response_task
                    elif wait_status and status_task in done:
                        return await status_task
                    elif not wait_response and not wait_status:
                        return
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()

                await asyncio.gather(*tasks, return_exceptions=True)

    async def version(self):
        return await self.command(CommandId.GET_VERSION, wait_response=ResponseId.VERSION_LIST)

    async def version_str(self):
        version, lqi = await self.version()
        version = '{:x}'.format(version[1])
        version = '{}.{}'.format(version[0], version[1:])
        return version

    async def get_network_state(self):
        return await self.command(CommandId.NETWORK_STATE_REQ, wait_response=ResponseId.NETWORK_STATE_RSP)

    async def set_raw_mode(self, enable=True):
        data = t.serialize([enable], COMMANDS[CommandId.SET_RAWMODE])
        await self.command(CommandId.SET_RAWMODE, data)

    async def reset(self, *, wait=True):
        wait_response = ResponseId.NODE_NON_FACTORY_NEW_RESTART if wait else None
        await self.command(CommandId.RESET, wait_response=wait_response)

    async def erase_persistent_data(self):
        await self.command(CommandId.ERASE_PERSISTENT_DATA, wait_status=False, wait_response=ResponseId.PDM_LOADED, timeout=10)
        await asyncio.sleep(1)
        await self.command(CommandId.RESET, wait_response=ResponseId.NODE_FACTORY_NEW_RESTART)

    async def set_time(self, dt=None):
        """ set internal time
        if timestamp is None, now is used
        """
        dt = dt or datetime.datetime.now()
        timestamp = int((dt - datetime.datetime(2000, 1, 1)).total_seconds())
        data = t.serialize([timestamp], COMMANDS[CommandId.SET_TIMESERVER])
        await self.command(CommandId.SET_TIMESERVER, data)

    async def get_time_server(self):
        timestamp, lqi = await self.command(CommandId.GET_TIMESERVER, wait_response=ResponseId.GET_TIMESERVER_LIST)
        dt = datetime.datetime(2000, 1, 1) + datetime.timedelta(seconds=timestamp[0])
        return dt

    async def set_led(self, enable=True):
        data = t.serialize([enable], COMMANDS[CommandId.SET_LED])
        await self.command(CommandId.SET_LED, data)

    async def set_certification(self, typ='CE'):
        cert = {'CE': 1, 'FCC': 2}[typ]
        data = t.serialize([cert], COMMANDS[CommandId.SET_CE_FCC])
        await self.command(CommandId.SET_CE_FCC, data)

    async def management_network_request(self):
        data = t.serialize([0x0000, 0x07fff800, 0xff, 5, 0xff, 0x0000], COMMANDS[CommandId.MANAGEMENT_NETWORK_UPDATE_REQUEST])
        return await self.command(CommandId.MANAGEMENT_NETWORK_UPDATE_REQUEST)#, wait_response=0x804a, timeout=10)

    async def set_tx_power(self, power=63):
        if power > 63:
            power = 63
        if power < 0:
            power = 0
        data = t.serialize([power], COMMANDS[CommandId.AHI_SET_TX_POWER])
        power, lqi = await self.command(CommandId.AHI_SET_TX_POWER, data, wait_response=CommandId.AHI_SET_TX_POWER_RSP)
        return power[0]

    async def set_channel(self, channels=None):
        channels = channels or [11, 14, 15, 19, 20, 24, 25, 26]
        if not isinstance(channels, list):
            channels = [channels]
        mask = functools.reduce(lambda acc, x: acc ^ 2 ** x, channels, 0)
        data = t.serialize([mask], COMMANDS[CommandId.SET_CHANNELMASK])
        await self.command(CommandId.SET_CHANNELMASK, data)

    async def set_extended_panid(self, extended_pan_id):
        data = t.serialize([extended_pan_id], COMMANDS[CommandId.SET_EXT_PANID])
        await self.command(CommandId.SET_EXT_PANID, data)

    async def get_devices_list(self):
        (entries,), lqi = await self.command(CommandId.GET_DEVICES_LIST, wait_response=ResponseId.GET_DEVICES_LIST_RSP)

        return list(entries or [])

    async def permit_join(self, duration=60):
        data = t.serialize([0x0000, duration, 1], COMMANDS[CommandId.PERMIT_JOINING_REQUEST])
        return await self.command(CommandId.PERMIT_JOINING_REQUEST, data)

    async def start_network(self):
        return await self.command(CommandId.START_NETWORK, wait_response=ResponseId.NETWORK_JOINED_FORMED)

    async def remove_device(self, zigate_ieee, ieee):
        data = t.serialize([zigate_ieee, ieee], COMMANDS[CommandId.NETWORK_REMOVE_DEVICE])
        return await self.command(CommandId.NETWORK_REMOVE_DEVICE, data)

    async def raw_aps_data_request(self, addr, src_ep, dst_ep, profile,
                                   cluster, payload, addr_mode=t.AddressMode.NWK, security=SendSecurity.NETWORK, radius=0):
        '''
        Send raw APS Data request
        '''
        data = t.serialize([addr_mode, addr,
                           src_ep, dst_ep, cluster, profile,
                           security, radius, payload], COMMANDS[CommandId.SEND_RAW_APS_DATA_PACKET])
        return await self.command(CommandId.SEND_RAW_APS_DATA_PACKET, data)

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
